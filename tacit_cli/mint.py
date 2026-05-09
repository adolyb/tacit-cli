import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

from .broadcast import BroadcastError, MempoolBroadcaster
from .client import TacitAPIError, TacitClient

logger = logging.getLogger("tacit_cli.mint")


@dataclass
class MintConfig:
  asset_id: str
  from_address: str
  receiver_address: str
  wallet_pubkey_hex: str
  # etch_txid is needed by the signer to verify the envelope payload anchors
  # to the right asset. Resolve from /api/assets in the CLI layer.
  etch_txid: str = ""
  repeat_count: int = 1
  fee_rate: int = 2

  def to_build_payload(self, utxos: list) -> dict:
    return {
      "asset_id": self.asset_id,
      "fromAddress": self.from_address,
      "receiverAddress": self.receiver_address,
      "walletPubkeyHex": self.wallet_pubkey_hex,
      "repeatCount": self.repeat_count,
      "feeRate": self.fee_rate,
      "utxos": utxos,
    }


@dataclass
class MintLog:
  path: str
  records: list = field(default_factory=list)

  def append(self, record: dict) -> None:
    record = {"ts": int(time.time()), **record}
    # Defensive scrub: never let secrets land here even if a caller is sloppy.
    for k in ("wif", "pubkey", "wallet_pubkey", "wallet_pubkey_hex"):
      record.pop(k, None)
    self.records.append(record)
    with open(self.path, "a", encoding="utf-8") as fp:
      fp.write(json.dumps(record) + "\n")


def fetch_utxos(client: TacitClient, address: str) -> list:
  data = client.get_utxos(address)
  return data.get("utxos") or []


def request_build(client: TacitClient, config: MintConfig, utxos: list) -> dict:
  url = f"{client.base_url}/api/mint/build"
  resp = client.session.post(
    url,
    json=config.to_build_payload(utxos),
    timeout=client.timeout,
  )
  if 400 <= resp.status_code < 500:
    try:
      payload = resp.json()
      message = payload.get("error") or payload.get("message") or resp.text
    except ValueError:
      message = resp.text or resp.reason
    raise TacitAPIError(resp.status_code, message)
  resp.raise_for_status()
  return resp.json()


def request_extract(
  client: TacitClient,
  chains: list,
  signed_commits: list,
  signed_reveals: list,
) -> dict:
  url = f"{client.base_url}/api/mint/extract"
  body = {
    "chains": chains,
    "signed": {"commits": signed_commits, "reveals": signed_reveals},
  }
  resp = client.session.post(url, json=body, timeout=client.timeout)
  if 400 <= resp.status_code < 500:
    try:
      payload = resp.json()
      message = payload.get("error") or payload.get("message") or resp.text
    except ValueError:
      message = resp.text or resp.reason
    raise TacitAPIError(resp.status_code, message)
  resp.raise_for_status()
  return resp.json()


def _extract_psbt_hex(psbt_field) -> str:
  # Build response wraps PSBT as {"hex": "..."}; tolerate string fallback too.
  if isinstance(psbt_field, dict):
    return psbt_field.get("hex") or psbt_field.get("psbt") or ""
  return psbt_field or ""


def _extract_raw_hex(tx_field) -> str:
  # Server may name this field rawTxHex / raw_tx_hex / rawHex / hex / tx_hex.
  if isinstance(tx_field, dict):
    for k in ("rawTxHex", "raw_tx_hex", "rawHex", "raw_hex", "hex", "tx_hex", "tx"):
      v = tx_field.get(k)
      if v:
        return v
    return ""
  return tx_field or ""


def _extract_chain_txs(out_chain: dict) -> tuple:
  """Return ((commit_raw, commit_txid), [(reveal_raw, reveal_txid), ...]).

  Real /api/mint/extract response uses items=[{kind, rawTxHex, txid, ...}]
  with commits and reveals interleaved. Fall back to the older assumed
  {commit, reveals} layout if items is absent.
  """
  items = out_chain.get("items")
  if isinstance(items, list):
    commit = ("", "")
    reveals = []
    for item in items:
      raw = _extract_raw_hex(item)
      txid = (item or {}).get("txid", "")
      kind = (item or {}).get("kind")
      if kind == "commit":
        commit = (raw, txid)
      elif kind == "reveal":
        reveals.append((raw, txid))
    return commit, reveals
  c = out_chain.get("commit") or {}
  commit = (_extract_raw_hex(c), c.get("txid", "") if isinstance(c, dict) else "")
  reveals = []
  for r in out_chain.get("reveals") or []:
    reveals.append((_extract_raw_hex(r), (r or {}).get("txid", "")))
  return commit, reveals


def _summarize_plan(build: dict) -> str:
  plan = build.get("plan") or {}
  chains = build.get("chains") or []
  total_reveal = plan.get("totalRevealCount", sum(len(c.get("reveals") or []) for c in chains))
  fee_per_reveal = plan.get("revealFeePerTx")
  total_commit_fee = sum((c.get("commit") or {}).get("fee") or 0 for c in chains)
  lines = [
    f"chains: {len(chains)}",
    f"reveals total: {total_reveal} (repeat={plan.get('repeatCount')})",
    f"reveal fee per tx: {fee_per_reveal}",
    f"commit fee total: {total_commit_fee} sats",
  ]
  return "\n".join(lines)


def run_mint(
  client: TacitClient,
  config: MintConfig,
  signer,
  broadcaster: Optional[MempoolBroadcaster] = None,
  *,
  dry_run: bool = False,
  prompt_confirm: bool = True,
  log_dir: str = ".",
  confirm_fn: Optional[Callable[[str], str]] = None,
) -> dict:
  broadcaster = broadcaster or MempoolBroadcaster()
  confirm_fn = confirm_fn or input

  # 1. UTXOs
  print(f"[1/5] fetching UTXOs for {config.from_address}")
  utxos = fetch_utxos(client, config.from_address)
  if not utxos:
    raise SystemExit("no spendable UTXOs at fromAddress")
  print(f"      got {len(utxos)} utxos, total {sum(u.get('value', 0) for u in utxos)} sats")

  # 2. build
  print(f"[2/5] requesting /api/mint/build (count={config.repeat_count}, feeRate={config.fee_rate})")
  build = request_build(client, config, utxos)
  chains = build.get("chains") or []
  if not chains:
    raise SystemExit(f"server returned no chains: {build}")
  print(_summarize_plan(build))

  if dry_run:
    return {"build": build}

  if prompt_confirm:
    answer = confirm_fn("type YES to sign and broadcast: ")
    if answer.strip() != "YES":
      print("aborted by user")
      return {"build": build, "aborted": True}

  log_path = os.path.join(log_dir, f"mint_log_{int(time.time())}.jsonl")
  mlog = MintLog(log_path)
  print(f"[3/5] signing {len(chains)} chain(s) -> log: {log_path}")

  if not config.etch_txid:
    raise SystemExit("MintConfig.etch_txid must be set before signing reveals")

  signed_commits = []
  signed_reveals = []
  for chain in chains:
    commit_hex = _extract_psbt_hex((chain.get("commit") or {}).get("psbt"))
    if not commit_hex:
      raise SystemExit(f"chain {chain.get('chainIndex')} missing commit psbt")
    signed_commit = signer.sign_commit_psbt(commit_hex, config.from_address)
    signed_commits.append(signed_commit)
    for r in chain.get("reveals") or []:
      reveal_hex = _extract_psbt_hex(r.get("psbt"))
      if not reveal_hex:
        raise SystemExit(f"chain {chain.get('chainIndex')} reveal missing psbt hex")
      signed_reveal = signer.sign_reveal_psbt(
        reveal_hex,
        config.receiver_address,
        config.asset_id,
        config.etch_txid,
      )
      signed_reveals.append(signed_reveal)

  # 4. extract
  print(f"[4/5] requesting /api/mint/extract ({len(signed_commits)} commits, {len(signed_reveals)} reveals)")
  extracted = request_extract(client, chains, signed_commits, signed_reveals)
  out_chains = extracted.get("chains") or []
  if len(out_chains) != len(chains):
    logger.warning("extract returned %d chains, expected %d", len(out_chains), len(chains))

  # 4b. persist raw hex BEFORE any broadcast so a crash mid-loop can resume
  # without re-asking the indexer to rebuild (which may not be deterministic).
  per_chain = []
  for ci, out_chain in enumerate(out_chains):
    commit, reveals = _extract_chain_txs(out_chain)
    per_chain.append((commit, reveals))
    mlog.append({
      "kind": "raw",
      "chain": ci,
      "commit_raw": commit[0],
      "commit_txid": commit[1],
      "reveal_raws": [r[0] for r in reveals],
      "reveal_txids": [r[1] for r in reveals],
    })

  # 5. broadcast
  print(f"[5/5] broadcasting via {broadcaster.base}")
  results = []
  for ci, (commit, reveals) in enumerate(per_chain):
    commit_raw, server_commit_txid = commit
    if not commit_raw:
      raise SystemExit(f"chain {ci} extract response missing commit raw hex")
    print(f"  chain {ci}: pushing commit ({len(commit_raw)//2} bytes, server-txid {server_commit_txid[:16]}...)")
    try:
      commit_txid = broadcaster.push_tx(commit_raw)
    except BroadcastError as e:
      mlog.append({"kind": "commit", "chain": ci, "status": "error", "error": str(e)})
      raise
    mlog.append({"kind": "commit", "chain": ci, "status": "broadcast", "txid": commit_txid})
    print(f"           commit txid={commit_txid}, waiting for mempool...")
    broadcaster.wait_in_mempool(commit_txid)
    mlog.append({"kind": "commit", "chain": ci, "status": "mempool", "txid": commit_txid})

    reveal_txids = []
    for ri, (reveal_raw, server_reveal_txid) in enumerate(reveals):
      if not reveal_raw:
        raise SystemExit(f"chain {ci} reveal {ri} missing raw hex")
      print(f"  chain {ci}: pushing reveal {ri} (server-txid {server_reveal_txid[:16]}...)")
      try:
        rev_txid = broadcaster.push_tx(reveal_raw)
      except BroadcastError as e:
        mlog.append({"kind": "reveal", "chain": ci, "index": ri, "status": "error", "error": str(e)})
        raise
      mlog.append({"kind": "reveal", "chain": ci, "index": ri, "status": "broadcast", "txid": rev_txid})
      reveal_txids.append(rev_txid)
      print(f"           reveal txid={rev_txid}")

    results.append({"chain": ci, "commit_txid": commit_txid, "reveal_txids": reveal_txids})

  print(f"done. log: {log_path}")
  return {"build": build, "results": results, "log": log_path}
