from itertools import islice

from tacit_cli.client import TacitClient


def main() -> None:
  client = TacitClient()
  assets = client.get_assets().get("assets", [])
  fair = next((a for a in assets if (a.get("ticker") or "").upper() == "FAIR"), None)
  if fair is None:
    raise SystemExit("FAIR asset not found in indexer response")

  print(f"FAIR asset_id={fair['asset_id']} holders={fair.get('holder_count')}")
  print("-" * 72)
  for h in islice(client.iter_holders(fair["asset_id"], page_size=100), 50):
    print(
      f"{h['rank']:>4}  {h['address']:<46} "
      f"{h['amount']:>14}  {h['percentage']:.4f}%"
    )


if __name__ == "__main__":
  main()
