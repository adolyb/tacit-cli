import argparse
import csv
import json
import logging
import re
import sys
from typing import Optional

from .client import TacitAPIError, TacitClient

ASSET_ID_RE = re.compile(r"^[0-9a-fA-F]{64}$")


def _resolve_asset_id(client: TacitClient, query: str) -> str:
  # Hex 64 == raw asset_id, otherwise treat as ticker and look it up.
  if ASSET_ID_RE.match(query):
    return query
  data = client.get_assets()
  query_upper = query.upper()
  for asset in data.get("assets", []):
    if (asset.get("ticker") or "").upper() == query_upper:
      return asset["asset_id"]
  raise SystemExit(f"ticker not found: {query}")


def _cmd_assets(args: argparse.Namespace, client: TacitClient) -> int:
  data = client.get_assets()
  if args.json:
    json.dump(data, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0
  overview = data.get("overview", {})
  print(
    f"indexed height={overview.get('max_indexed_height')} "
    f"assets={overview.get('asset_count')} "
    f"pmints={overview.get('pmint_count')}"
  )
  print("-" * 72)
  print(f"{'TICKER':<8} {'MINTED/CAP':<28} {'HOLDERS':>8}  ASSET_ID")
  for asset in data.get("assets", []):
    minted = asset.get("cumulative_minted", "0")
    cap = asset.get("cap_amount", "0")
    progress = f"{minted}/{cap}"
    print(
      f"{(asset.get('ticker') or '?'):<8} "
      f"{progress:<28} "
      f"{asset.get('holder_count', 0):>8}  "
      f"{asset.get('asset_id', '')}"
    )
  return 0


def _cmd_holders(args: argparse.Namespace, client: TacitClient) -> int:
  asset_id = _resolve_asset_id(client, args.asset)

  if args.all:
    holders = list(client.iter_holders(asset_id, page_size=max(args.page_size, 100)))
    asset_meta = client.get_holders(asset_id, page=1, page_size=1).get("asset", {})
  else:
    page_data = client.get_holders(asset_id, page=args.page, page_size=args.page_size)
    holders = page_data.get("holders", [])
    asset_meta = page_data.get("asset", {})

  if args.csv:
    with open(args.csv, "w", newline="", encoding="utf-8") as fp:
      writer = csv.writer(fp)
      writer.writerow(["rank", "address", "script_pubkey", "amount", "percentage"])
      for h in holders:
        writer.writerow([
          h.get("rank"),
          h.get("address"),
          h.get("script_pubkey"),
          h.get("amount"),
          h.get("percentage"),
        ])
    print(f"wrote {len(holders)} rows -> {args.csv}")
    return 0

  ticker = asset_meta.get("ticker") or asset_id[:8]
  total = asset_meta.get("holder_count", len(holders))
  print(f"{ticker} holders shown={len(holders)} total={total}")
  print("-" * 72)
  print(f"{'RANK':>5}  {'ADDRESS':<46} {'AMOUNT':>14}  PCT")
  for h in holders:
    print(
      f"{h.get('rank', 0):>5}  "
      f"{(h.get('address') or ''):<46} "
      f"{h.get('amount', '0'):>14}  "
      f"{h.get('percentage', 0):.4f}"
    )
  return 0


def _cmd_address(args: argparse.Namespace, client: TacitClient) -> int:
  try:
    data = client.get_address(args.address)
  except TacitAPIError as e:
    # Bad addresses come back as 400; surface message cleanly.
    print(f"error: {e.message}", file=sys.stderr)
    return 2

  if args.json:
    json.dump(data, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0

  print(f"address {data.get('address')} ({data.get('kind')}, {data.get('network')})")
  print(f"script_pubkey {data.get('script_pubkey')}")
  tokens = data.get("tokens") or []
  if not tokens:
    print("no tacit holdings")
    return 0
  print("-" * 72)
  print(f"{'TICKER':<8} {'CREDITED':>14} {'PENDING':>14} {'EVENTS':>8}")
  for t in tokens:
    events = t.get("events") or []
    print(
      f"{(t.get('ticker') or '?'):<8} "
      f"{t.get('credited_amount', '0'):>14} "
      f"{t.get('pending_amount', '0'):>14} "
      f"{len(events):>8}"
    )
  return 0


def _build_parser() -> argparse.ArgumentParser:
  parser = argparse.ArgumentParser(prog="tacit", description="Tacit indexer read-only CLI")
  parser.add_argument("--base-url", default=None, help="override Tacit indexer base URL")
  parser.add_argument("--timeout", type=int, default=15)
  parser.add_argument("-v", "--verbose", action="store_true")

  sub = parser.add_subparsers(dest="cmd", required=True)

  p_assets = sub.add_parser("assets", help="list all indexed Tacit assets")
  p_assets.add_argument("--json", action="store_true")
  p_assets.set_defaults(func=_cmd_assets)

  p_holders = sub.add_parser("holders", help="list holders of an asset")
  p_holders.add_argument("asset", help="asset_id (64 hex) or ticker (e.g. FAIR)")
  p_holders.add_argument("--page", type=int, default=1)
  p_holders.add_argument("--page-size", type=int, default=25)
  p_holders.add_argument("--all", action="store_true", help="walk every page")
  p_holders.add_argument("--csv", default=None, help="write CSV to this path")
  p_holders.set_defaults(func=_cmd_holders)

  p_addr = sub.add_parser("address", help="show Tacit holdings of a BTC address")
  p_addr.add_argument("address")
  p_addr.add_argument("--json", action="store_true")
  p_addr.set_defaults(func=_cmd_address)

  return parser


def main(argv: Optional[list] = None) -> int:
  parser = _build_parser()
  args = parser.parse_args(argv)

  logging.basicConfig(
    level=logging.DEBUG if args.verbose else logging.WARNING,
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
