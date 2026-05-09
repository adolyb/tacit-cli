import logging
import time
from typing import Optional

import requests

logger = logging.getLogger("tacit_cli.broadcast")

DEFAULT_BASE = "https://mempool.space/api"
RETRYABLE_STATUS = (500, 502, 503, 504)


class BroadcastError(Exception):
  def __init__(self, status: int, message: str):
    super().__init__(f"[{status}] {message}")
    self.status = status
    self.message = message


class MempoolBroadcaster:
  def __init__(
    self,
    base: str = DEFAULT_BASE,
    session: Optional[requests.Session] = None,
    timeout: int = 20,
  ):
    self.base = base.rstrip("/")
    self.session = session or requests.Session()
    self.timeout = timeout

  def push_tx(self, raw_hex: str, max_retries: int = 3) -> str:
    url = f"{self.base}/tx"
    last_exc = None
    for attempt in range(1, max_retries + 1):
      resp = self.session.post(
        url,
        data=raw_hex,
        headers={"Content-Type": "text/plain"},
        timeout=self.timeout,
      )
      if resp.status_code == 200:
        return resp.text.strip()
      if 400 <= resp.status_code < 500:
        # Validation/dust/already-known errors are not retryable.
        raise BroadcastError(resp.status_code, resp.text.strip())
      if resp.status_code in RETRYABLE_STATUS:
        last_exc = BroadcastError(resp.status_code, resp.text.strip())
        sleep = 2 ** attempt
        logger.warning("push_tx %s -> %s, retry %d in %ds", url, resp.status_code, attempt, sleep)
        time.sleep(sleep)
        continue
      raise BroadcastError(resp.status_code, resp.text.strip())
    raise last_exc or BroadcastError(0, "unreachable")

  def wait_in_mempool(self, txid: str, timeout: int = 120, interval: int = 3) -> dict:
    """Poll /tx/{txid} until it returns 200 or timeout."""
    url = f"{self.base}/tx/{txid}"
    deadline = time.time() + timeout
    while time.time() < deadline:
      resp = self.session.get(url, timeout=self.timeout)
      if resp.status_code == 200:
        return resp.json()
      if resp.status_code == 404:
        time.sleep(interval)
        continue
      # 4xx other than 404 = something is wrong with the txid itself.
      if 400 <= resp.status_code < 500:
        raise BroadcastError(resp.status_code, resp.text.strip())
      time.sleep(interval)
    raise BroadcastError(0, f"timeout waiting for {txid} in mempool")
