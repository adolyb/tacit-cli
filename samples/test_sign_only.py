"""Sign-only test: build->sign, no extract, no broadcast. Confirms my
signer can produce valid signatures against the live server with the real
wallet WIF, without spending any sats.
"""

import json
import os
import sys
sys.path.insert(0, r"D:/code/claudecode/BITCOIN/tacit-cli")

from tacit_cli.envload import load_dotenv
load_dotenv()

from tacit_cli.client import TacitClient
from tacit_cli.mint import MintConfig, fetch_utxos, request_build, _extract_psbt_hex
from tacit_cli.signer import WifSigner

ASSET_ID = "c4a678d6d674cdd0f4a1a9df0cb5980bd1255bd0b62f8ddc886e61bd43f56b83"
ETCH_TXID = "c2542e7fbaa8c0c9fa632d8720ebf0ba602f9cda8a4c4b1e5ca5d9e41acc4067"
FROM_ADDR = "bc1p7z6snxwjv9cv7kduae5sqd07zvsc3y9pwxqc5sgdrqnza67tuxgs26kzv2"

wif = os.environ.get("TACIT_WIF")
if not wif:
  raise SystemExit("TACIT_WIF missing from env")

signer = WifSigner(wif)
print(f"signer xonly = {signer.xonly_pubkey_hex}")
print(f"signer addr  = {signer.address}")
print()

client = TacitClient()
print("[1] fetching UTXOs...")
utxos = fetch_utxos(client, FROM_ADDR)
print(f"    got {len(utxos)} utxos, total {sum(u['value'] for u in utxos)} sats")
print()

config = MintConfig(
  asset_id=ASSET_ID,
  etch_txid=ETCH_TXID,
  from_address=FROM_ADDR,
  receiver_address=FROM_ADDR,
  wallet_pubkey_hex=signer.pubkey_hex,
  repeat_count=1,
  fee_rate=8,
)

print("[2] requesting /api/mint/build...")
build = request_build(client, config, utxos)
chains = build.get("chains", [])
plan = build.get("plan", {})
print(f"    chains          : {len(chains)}")
print(f"    repeatCount     : {plan.get('repeatCount')}")
print(f"    serviceFee.applies: {plan.get('serviceFee', {}).get('applies')}")
print(f"    feeRate         : {plan.get('feeRate')}")
print()

# Save the live build response for forensic comparison
with open(r"D:/code/claudecode/BITCOIN/tacit-cli/samples/live_build.json", "w", encoding="utf-8") as f:
  json.dump(build, f, ensure_ascii=False, indent=2)

print("[3] signing all PSBTs in memory (no extract, no broadcast)...")
total_signed = 0
for i, chain in enumerate(chains):
  commit_hex = _extract_psbt_hex(chain.get("commit", {}).get("psbt"))
  print(f"    chain[{i}] commit psbt len = {len(commit_hex)//2} bytes")
  signed_commit = signer.sign_commit_psbt(commit_hex, FROM_ADDR)
  print(f"      -> signed commit len = {len(signed_commit)//2} bytes")
  total_signed += 1
  for j, r in enumerate(chain.get("reveals", [])):
    reveal_hex = _extract_psbt_hex(r.get("psbt"))
    print(f"    chain[{i}] reveal[{j}] psbt len = {len(reveal_hex)//2} bytes")
    signed_reveal = signer.sign_reveal_psbt(
      reveal_hex, FROM_ADDR, ASSET_ID, ETCH_TXID
    )
    print(f"      -> signed reveal len = {len(signed_reveal)//2} bytes")
    total_signed += 1

print()
print(f"DONE. {total_signed} PSBTs signed and validated. No on-chain effect.")
