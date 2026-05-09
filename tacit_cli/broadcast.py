import hashlib
import logging
import re
import time
from typing import Optional

import requests

logger = logging.getLogger("tacit_cli.broadcast")

# Default to blockstream.info (Esplora API) because mempool.space's TLS has
# been flaky from this host. Both expose identical /api/tx endpoints.
# Override at runtime via TACIT_BROADCASTER env or MempoolBroadcaster(base=...).
DEFAULT_BASE = "https://blockstream.info/api"
FALLBACK_BASES = ("https://mempool.space/api",)
RETRYABLE_STATUS = (500, 502, 503, 504)
RETRYABLE_NETWORK_EXCEPTIONS = (
  requests.exceptions.SSLError,
  requests.exceptions.ConnectionError,
  requests.exceptions.Timeout,
)

# Mempool/Bitcoin Core idempotency markers — when seen on a 4xx, treat as
# success (the tx is already known to the network) and recover the txid
# locally instead of failing the run.
_ALREADY_KNOWN_PATTERNS = (
  re.compile(r"already in (?:the )?mempool", re.I),
  re.compile(r"already in (?:the )?block ?chain", re.I),
  re.compile(r"transaction already exists", re.I),
  re.compile(r"txn-already-known", re.I),
  re.compile(r"txn-already-in-mempool", re.I),
)


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
    last_exc = None
    bases = [self.base] + [b for b in FALLBACK_BASES if b != self.base]
    for base in bases:
      url = f"{base}/tx"
      for attempt in range(1, max_retries + 1):
        try:
          resp = self.session.post(
            url,
            data=raw_hex,
            headers={"Content-Type": "text/plain"},
            timeout=self.timeout,
          )
        except RETRYABLE_NETWORK_EXCEPTIONS as e:
          # SSL/Connection/Timeout: retry within this base, then fall through
          # to the next base if all attempts fail.
          last_exc = e
          sleep = 2 ** attempt
          logger.warning("push_tx %s network error: %s; retry %d in %ds", url, e, attempt, sleep)
          time.sleep(sleep)
          continue
        if resp.status_code == 200:
          return resp.text.strip()
        if 400 <= resp.status_code < 500:
          msg = resp.text.strip()
          if _is_already_known(msg):
            txid = _txid_from_raw(raw_hex)
            logger.info("push_tx: tx already known, recovered txid=%s", txid)
            return txid
          raise BroadcastError(resp.status_code, msg)
        if resp.status_code in RETRYABLE_STATUS:
          last_exc = BroadcastError(resp.status_code, resp.text.strip())
          sleep = 2 ** attempt
          logger.warning("push_tx %s -> %s, retry %d in %ds", url, resp.status_code, attempt, sleep)
          time.sleep(sleep)
          continue
        raise BroadcastError(resp.status_code, resp.text.strip())
      logger.warning("push_tx exhausted retries on %s, trying next base", base)
    if isinstance(last_exc, BroadcastError):
      raise last_exc
    raise BroadcastError(0, f"all broadcasters failed: {last_exc}")

  def wait_in_mempool(self, txid: str, timeout: int = 120, interval: int = 3) -> dict:
    """Poll /tx/{txid} until it returns 200 or timeout. Tries primary base
    first, falls back to other Esplora hosts on connection failures.
    """
    bases = [self.base] + [b for b in FALLBACK_BASES if b != self.base]
    deadline = time.time() + timeout
    while time.time() < deadline:
      for base in bases:
        url = f"{base}/tx/{txid}"
        try:
          resp = self.session.get(url, timeout=self.timeout)
        except RETRYABLE_NETWORK_EXCEPTIONS:
          continue
        if resp.status_code == 200:
          return resp.json()
        if resp.status_code == 404:
          break
        if 400 <= resp.status_code < 500:
          raise BroadcastError(resp.status_code, resp.text.strip())
      time.sleep(interval)
    raise BroadcastError(0, f"timeout waiting for {txid} in mempool")


def _is_already_known(message: str) -> bool:
  return any(p.search(message) for p in _ALREADY_KNOWN_PATTERNS)


def _txid_from_raw(raw_hex: str) -> str:
  """Compute Bitcoin txid from raw tx hex.

  txid = double-SHA256 over tx without witness, displayed little-endian.
  Implementing this manually so we don't add a heavy dep just for recovery.
  """
  raw = bytes.fromhex(raw_hex.strip())
  stripped = _strip_witness(raw)
  digest = hashlib.sha256(hashlib.sha256(stripped).digest()).digest()
  return digest[::-1].hex()


def _strip_witness(raw: bytes) -> bytes:
  # Pre-segwit format starts with 4-byte version, then varint input count.
  # Segwit format: 4-byte version, 1-byte 0x00 marker, 1-byte 0x01 flag,
  # then varint inputs ... then witnesses ... then locktime.
  if len(raw) < 10 or raw[4] != 0x00 or raw[5] != 0x01:
    return raw
  out = bytearray(raw[:4])
  pos = 6
  ic, pos = _read_varint(raw, pos)
  out += _encode_varint(ic)
  inputs_start = pos
  for _ in range(ic):
    pos += 36  # txid + vout
    sl, pos = _read_varint(raw, pos)
    pos += sl + 4  # scriptSig + sequence
  out += raw[inputs_start:pos]
  oc, pos = _read_varint(raw, pos)
  out += _encode_varint(oc)
  outputs_start = pos
  for _ in range(oc):
    pos += 8  # value
    sl, pos = _read_varint(raw, pos)
    pos += sl
  out += raw[outputs_start:pos]
  # Skip witness fields (one per input, each is a varint count of items).
  for _ in range(ic):
    wc, pos = _read_varint(raw, pos)
    for _ in range(wc):
      il, pos = _read_varint(raw, pos)
      pos += il
  out += raw[pos:pos + 4]  # locktime
  return bytes(out)


def _read_varint(buf: bytes, pos: int):
  b = buf[pos]
  if b < 0xfd:
    return b, pos + 1
  if b == 0xfd:
    return int.from_bytes(buf[pos + 1:pos + 3], "little"), pos + 3
  if b == 0xfe:
    return int.from_bytes(buf[pos + 1:pos + 5], "little"), pos + 5
  return int.from_bytes(buf[pos + 1:pos + 9], "little"), pos + 9


def _encode_varint(n: int) -> bytes:
  if n < 0xfd:
    return bytes([n])
  if n <= 0xffff:
    return b"\xfd" + n.to_bytes(2, "little")
  if n <= 0xffffffff:
    return b"\xfe" + n.to_bytes(4, "little")
  return b"\xff" + n.to_bytes(8, "little")
