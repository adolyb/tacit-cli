"""Verify that TACIT_WIF in env (loaded from .env) derives the expected xonly
pubkey. Never prints the WIF or any secret material.
"""

import os
import sys
sys.path.insert(0, r"D:/code/claudecode/BITCOIN/tacit-cli")

from tacit_cli.envload import load_dotenv

load_dotenv()

EXPECTED_XONLY = "9d2a1670e79e7ff6ee16aa34fe151a3a879be9758be240e5110371a118e1fd39"
EXPECTED_ADDRESS = "bc1p7z6snxwjv9cv7kduae5sqd07zvsc3y9pwxqc5sgdrqnza67tuxgs26kzv2"

wif = os.environ.get("TACIT_WIF")
print("TACIT_WIF set:", "YES" if wif else "NO")
if not wif:
  sys.exit(0)

print("WIF length    :", len(wif))
print("WIF prefix    :", wif[0])

from tacit_cli.signer import WifSigner
signer = WifSigner(wif)

derived_xonly = signer.xonly_pubkey_hex
print("derived xonly :", derived_xonly)
print("expected xonly:", EXPECTED_XONLY)
print("xonly match   :", "YES" if derived_xonly == EXPECTED_XONLY else "NO")

print("derived addr  :", signer.address)
print("expected addr :", EXPECTED_ADDRESS)
print("addr match    :", "YES" if signer.address == EXPECTED_ADDRESS else "NO")
