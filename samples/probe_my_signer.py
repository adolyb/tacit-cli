"""Run my signer.py against the REAL captured PSBTs, with a WRONG key.
Expected: validation passes, sign_with returns 0 sigs (key mismatch),
then my safety check raises SignerError. This confirms the safety net.
"""

import json
import sys
sys.path.insert(0, r"D:/code/claudecode/BITCOIN/tacit-cli")

from tacit_cli.signer import WifSigner, SignerError

with open(r"D:/code/claudecode/BITCOIN/tacit-cli/samples/build_resp_real.json", "rb") as f:
  resp = json.loads(f.read().decode("utf-8"))

commit_hex = resp["chains"][0]["commit"]["psbt"]["hex"]
reveal_hex = resp["chains"][0]["reveals"][0]["psbt"]["hex"]
asset_id = "c4a678d6d674cdd0f4a1a9df0cb5980bd1255bd0b62f8ddc886e61bd43f56b83"
etch_txid = "c2542e7fbaa8c0c9fa632d8720ebf0ba602f9cda8a4c4b1e5ca5d9e41acc4067"
from_addr = "bc1p7z6snxwjv9cv7kduae5sqd07zvsc3y9pwxqc5sgdrqnza67tuxgs26kzv2"
receiver = from_addr  # mint to self in this sample

# Generate a synthetic WIF (mainnet, compressed, key=0x42*32) just for the test
from embit import ec
def make_wif(privkey_bytes: bytes) -> str:
  payload = b"\x80" + privkey_bytes + b"\x01"
  import hashlib
  ck = hashlib.sha256(hashlib.sha256(payload).digest()).digest()[:4]
  from embit import base58
  return base58.encode(payload + ck)

wif = make_wif(b"\x42" * 32)
print("synthetic test wif:", wif)

signer = WifSigner(wif)
print("signer xonly:", signer.xonly_pubkey_hex)
print("signer p2tr addr:", signer.address)
print()

print("=== sign_commit_psbt ===")
try:
  signed_commit = signer.sign_commit_psbt(commit_hex, from_addr)
  print("UNEXPECTED success, signed hex prefix:", signed_commit[:60])
except SignerError as e:
  print("SignerError (expected):", e)
print()

print("=== sign_reveal_psbt ===")
try:
  signed_reveal = signer.sign_reveal_psbt(reveal_hex, receiver, asset_id, etch_txid)
  print("UNEXPECTED success, signed hex prefix:", signed_reveal[:60])
except SignerError as e:
  print("SignerError (expected):", e)
