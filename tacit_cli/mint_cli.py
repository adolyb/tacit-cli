import argparse
import json
import logging
import os
import re
import sys
from typing import Optional

from .broadcast import BroadcastError, MempoolBroadcaster
from .client import TacitAPIError, TacitClient
from .envload import load_dotenv
from .mint import MintConfig, fetch_utxos, request_build, run_mint

# Load .env before argparse defaults read os.environ. Walks up from CWD so
# putting .env at the project root or one level up both work.
load_dotenv()

logger = logging.getLogger("tacit_cli.mint_cli")

ASSET_ID_RE = re.compile(r"^[0-9a-fA-F]{64}$")
DEFAULT_ASSET = "FAIR"


def _resolve_asset(client: TacitClient, query: str) -> tuple:
  """Return (asset_id, etch_txid). The signer needs etch_txid to verify the
  reveal envelope payload anchors to the right asset.
  """
  data = client.get_assets()
  if ASSET_ID_RE.match(query):
    for asset in data.get("assets", []):
      if asset.get("asset_id") == query:
        return asset["asset_id"], asset.get("etch_txid", "")
    raise SystemExit(f"asset_id not found in indexer: {query}")
  query_upper = query.upper()
  for asset in data.get("assets", []):
    if (asset.get("ticker") or "").upper() == query_upper:
      return asset["asset_id"], asset.get("etch_txid", "")
  raise SystemExit(f"ticker not found: {query}")


def _make_signer(wif: str):
  # Imported lazily so the CLI still loads even if embit is missing in plan-only mode.
  from .signer import WifSigner
  return WifSigner(wif)


def _cmd_plan(args: argparse.Namespace, client: TacitClient) -> int:
  asset_id, etch_txid = _resolve_asset(client, args.asset)
  # We need a wallet pubkey for build; if user provided --wif use it, otherwise
  # require explicit --pubkey-hex (avoids forcing private key for plan-only).
  pubkey_hex = args.pubkey_hex
  if not pubkey_hex and args.wif:
    pubkey_hex = _make_signer(args.wif).xonly_pubkey_hex
  if not pubkey_hex:
    raise SystemExit("plan needs --pubkey-hex (32-byte x-only) or --wif")

  receiver = args.receiver or args.address
  config = MintConfig(
    asset_id=asset_id,
    etch_txid=etch_txid,
    from_address=args.address,
    receiver_address=receiver,
    wallet_pubkey_hex=pubkey_hex,
    repeat_count=args.count,
    fee_rate=args.fee_rate,
  )
  utxos = fetch_utxos(client, args.address)
  if not utxos:
    raise SystemExit("no spendable UTXOs")
  build = request_build(client, config, utxos)
  if args.json:
    json.dump(build, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0
  plan = build.get("plan") or {}
  chains = build.get("chains") or []
  print(f"asset_id      {asset_id}")
  print(f"from          {args.address}")
  print(f"receiver      {receiver}")
  print(f"repeatCount   {plan.get('repeatCount', args.count)}")
  print(f"chains        {len(chains)}")
  print(f"reveals total {plan.get('totalRevealCount', sum(len(c.get('reveals') or []) for c in chains))}")
  print(f"reveal fee/tx {plan.get('revealFeePerTx')}")
  print(f"commit fees   {sum((c.get('commit') or {}).get('fee') or 0 for c in chains)} sats")
  return 0


def _cmd_run(args: argparse.Namespace, client: TacitClient) -> int:
  if not args.wif:
    raise SystemExit("missing WIF: pass --wif or set TACIT_WIF in env")
  asset_id, etch_txid = _resolve_asset(client, args.asset)
  if not etch_txid:
    raise SystemExit(f"indexer returned no etch_txid for asset {asset_id}; cannot verify envelope")
  signer = _make_signer(args.wif)
  receiver = args.receiver or args.address

  # Default pubkey: x-only for taproot fromAddress, compressed for P2WPKH.
  pubkey_hex = args.pubkey_hex
  if not pubkey_hex:
    pubkey_hex = signer.xonly_pubkey_hex if args.address.startswith("bc1p") else signer.pubkey_hex

  config = MintConfig(
    asset_id=asset_id,
    etch_txid=etch_txid,
    from_address=args.address,
    receiver_address=receiver,
    wallet_pubkey_hex=pubkey_hex,
    repeat_count=args.count,
    fee_rate=args.fee_rate,
  )

  broadcaster = MempoolBroadcaster()
  try:
    result = run_mint(
      client,
      config,
      signer,
      broadcaster,
      dry_run=False,
      prompt_confirm=not args.yes,
      log_dir=args.log_dir,
    )
  except BroadcastError as e:
    print(f"broadcast error: {e}", file=sys.stderr)
    return 3
  except TacitAPIError as e:
    print(f"api error: {e}", file=sys.stderr)
    return 2
  if result.get("aborted"):
    return 1
  return 0


def register_subcommands(sub: argparse._SubParsersAction) -> None:
  """Hook used by the read-only CLI to graft mint commands onto its parser."""
  p_mint = sub.add_parser("mint", help="Tacit mint (sign + broadcast)")
  mint_sub = p_mint.add_subparsers(dest="mint_cmd", required=True)

  p_plan = mint_sub.add_parser("plan", help="dry-run: build PSBTs and show plan, no signing")
  p_plan.add_argument("--address", required=True)
  p_plan.add_argument("--asset", default=DEFAULT_ASSET)
  p_plan.add_argument("--count", type=int, default=1)
  p_plan.add_argument("--fee-rate", type=int, default=2)
  p_plan.add_argument("--receiver", default=None)
  p_plan.add_argument("--pubkey-hex", default=None, help="x-only (32B) or compressed (33B) hex")
  p_plan.add_argument("--wif", default=None, help="optional, only used to derive pubkey")
  p_plan.add_argument("--json", action="store_true")
  p_plan.set_defaults(func=_cmd_plan)

  p_run = mint_sub.add_parser("run", help="full mint: build + sign + extract + broadcast")
  p_run.add_argument("--address", required=True)
  # Explicit --wif overrides env so a leaked TACIT_WIF can be locally shadowed.
  p_run.add_argument("--wif", default=os.environ.get("TACIT_WIF"),
                     help="WIF private key; falls back to $TACIT_WIF (NEVER log/commit)")
  p_run.add_argument("--asset", default=DEFAULT_ASSET)
  p_run.add_argument("--count", type=int, default=1)
  p_run.add_argument("--fee-rate", type=int, default=2)
  p_run.add_argument("--receiver", default=None)
  p_run.add_argument("--pubkey-hex", default=None)
  p_run.add_argument("--yes", action="store_true", help="skip the YES confirmation prompt")
  p_run.add_argument("--log-dir", default=".")
  p_run.set_defaults(func=_cmd_run)


def main(argv: Optional[list] = None) -> int:
  """Standalone entry point for `python -m tacit_cli.mint_cli ...`."""
  parser = argparse.ArgumentParser(prog="tacit-mint", description="Tacit mint sign+broadcast CLI")
  parser.add_argument("--base-url", default=None)
  parser.add_argument("--timeout", type=int, default=15)
  parser.add_argument("-v", "--verbose", action="store_true")
  sub = parser.add_subparsers(dest="cmd", required=True)
  register_subcommands(sub)
  # The register_subcommands path nests under "mint"; flatten for standalone mode.
  args = parser.parse_args(argv)

  logging.basicConfig(
    level=logging.DEBUG if args.verbose else logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
  )
  client = TacitClient(
    base_url=args.base_url or "https://tacit.unode.one",
    timeout=args.timeout,
  )
  try:
    return args.func(args, client)
  except TacitAPIError as e:
    print(f"api error: {e}", file=sys.stderr)
    return 2


if __name__ == "__main__":
  raise SystemExit(main())
