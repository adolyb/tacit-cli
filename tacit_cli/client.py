import logging
from typing import Iterator, Optional

import requests

DEFAULT_BASE_URL = "https://tacit.unode.one"
DEFAULT_TIMEOUT = 15
DEFAULT_USER_AGENT = "tacit-cli/0.1.0 (+https://tacit.unode.one)"

logger = logging.getLogger("tacit_cli.client")


class TacitAPIError(Exception):
  """Raised on 4xx responses from the Tacit indexer."""

  def __init__(self, status: int, message: str):
    super().__init__(f"[{status}] {message}")
    self.status = status
    self.message = message


class TacitClient:
  def __init__(
    self,
    base_url: str = DEFAULT_BASE_URL,
    timeout: int = DEFAULT_TIMEOUT,
    session: Optional[requests.Session] = None,
  ):
    # Strip trailing slash so endpoint joining stays predictable.
    self.base_url = base_url.rstrip("/")
    self.timeout = timeout
    self.session = session or requests.Session()
    self.session.headers.setdefault("User-Agent", DEFAULT_USER_AGENT)
    self.session.headers.setdefault("Accept", "application/json")

  def _get(self, path: str, params: Optional[dict] = None) -> dict:
    url = f"{self.base_url}{path}"
    logger.debug("GET %s params=%s", url, params)
    resp = self.session.get(url, params=params, timeout=self.timeout)
    if 400 <= resp.status_code < 500:
      # Indexer always returns JSON with `error` key on 4xx, but be defensive.
      try:
        payload = resp.json()
        message = payload.get("error") or payload.get("message") or resp.text
      except ValueError:
        message = resp.text or resp.reason
      raise TacitAPIError(resp.status_code, message)
    resp.raise_for_status()
    return resp.json()

  def get_assets(self) -> dict:
    """Return overview + all indexed assets."""
    return self._get("/api/assets")

  def get_holders(self, asset_id: str, page: int = 1, page_size: int = 25) -> dict:
    """Return one page of holders for the given asset_id."""
    return self._get(
      "/api/holders",
      params={"asset_id": asset_id, "page": page, "page_size": page_size},
    )

  def iter_holders(self, asset_id: str, page_size: int = 100) -> Iterator[dict]:
    """Yield every holder, paging until exhausted."""
    page = 1
    total = None
    while True:
      data = self.get_holders(asset_id, page=page, page_size=page_size)
      if total is None:
        # holder_count drives termination; response itself has no total_pages.
        total = int(data.get("asset", {}).get("holder_count") or 0)
      holders = data.get("holders") or []
      if not holders:
        return
      for h in holders:
        yield h
      if page * page_size >= total:
        return
      page += 1

  def get_address(self, address: str) -> dict:
    """Return Tacit holdings + mint events for a Bitcoin address."""
    return self._get("/api/address", params={"address": address})

  def get_utxos(self, address: str) -> dict:
    """Return spendable UTXOs for an address; shared with the mint module."""
    return self._get("/api/utxos", params={"address": address})
