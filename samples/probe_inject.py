"""Inject TAP_BIP32_DERIVATION into the reveal PSBT and test if embit will
then attempt to sign. Uses a key whose xonly == the leaf-embedded pubkey
so we can confirm the codepath, even though we don't have the user's WIF.

Trick: we generate a NEW random key, compute its xonly, and PATCH the
leaf script to have OUR xonly instead of the original. This makes the
PSBT invalid for the original commit address but lets us test the signer
codepath end-to-end.
"""

import json
import hashlib
from embit import ec
from embit.psbt import PSBT

with open(r"D:/code/claudecode/BITCOIN/tacit-cli/samples/build_resp_real.json", "rb") as f:
  resp = json.loads(f.read().decode("utf-8"))

reveal_hex = resp["chains"][0]["reveals"][0]["psbt"]["hex"]


def tagged_hash(tag: str, data: bytes) -> bytes:
  th = hashlib.sha256(tag.encode()).digest()
  return hashlib.sha256(th + th + data).digest()


def compact_size(n: int) -> bytes:
  if n < 0xfd:
    return bytes([n])
  if n <= 0xffff:
    return b"\xfd" + n.to_bytes(2, "little")
  if n <= 0xffffffff:
    return b"\xfe" + n.to_bytes(4, "little")
  return b"\xff" + n.to_bytes(8, "little")


def tapleaf_hash(leaf_ver: int, script_bytes: bytes) -> bytes:
  return tagged_hash("TapLeaf", bytes([leaf_ver]) + compact_size(len(script_bytes)) + script_bytes)


# Parse reveal
psbt = PSBT.parse(bytes.fromhex(reveal_hex))
inp = psbt.inputs[0]

# Pull the only leaf entry
ts = inp.taproot_scripts
control_block, leaf_blob = list(ts.items())[0]
leaf_ver = leaf_blob[-1]
leaf_script = leaf_blob[:-1]
print("leaf_ver:", hex(leaf_ver))
print("leaf script len:", len(leaf_script))
leaf_h = tapleaf_hash(leaf_ver, leaf_script)
print("leaf_hash:", leaf_h.hex())

# xonly_pk in the leaf is at offset 1..33
xonly_in_leaf = leaf_script[1:33]
print("xonly in leaf:", xonly_in_leaf.hex())

# To confirm the codepath we need a privkey whose xonly == xonly_in_leaf.
# We obviously don't have it. Instead, we'll manually compute what a sign
# attempt SHOULD do: compute the BIP-341 sighash for the script-path spend,
# then a Schnorr signature.
# embit exposes this as inp.taproot_bip32_derivations[xonly] = (leaves, (fp, path)).
# Let's stuff a fake derivation in and see if embit then attempts to sign
# (it should pick up our test_key and try, then fail because test_key's
# xonly != xonly_in_leaf).

test_key = ec.PrivateKey(b"\x42" * 32)
print("test_key xonly:", test_key.xonly().hex())

# Inject derivation pointing at our test_key's xonly so embit sees:
#   "this key's xonly is in derivations, and it's mapped to this leaf"
inp.taproot_bip32_derivations[test_key.xonly()] = ([leaf_h], (b"\x00\x00\x00\x00", "m"))

print("\n--- after injecting derivation, sign_with(test_key) ---")
signed = psbt.sign_with(test_key)
print("returned:", signed)
for a in ("partial_sigs", "taproot_key_sig", "taproot_sigs", "taproot_script_sigs", "final_scriptwitness"):
  v = getattr(inp, a, None)
  print(f"  {a}:", repr(v)[:200] if v else v)
