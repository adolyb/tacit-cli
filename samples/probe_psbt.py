"""Probe the real PSBTs to see what embit can do with them.

Loads commit and reveal PSBTs from the captured /api/mint/build response
and reports what BIP-371 fields are present and whether sign_with would
attempt to sign each input.
"""

import json
from embit.psbt import PSBT
from embit import ec, script, networks

with open(r"D:/code/claudecode/BITCOIN/tacit-cli/samples/build_resp_real.json", "rb") as f:
  resp = json.loads(f.read().decode("utf-8"))

commit_hex = resp["chains"][0]["commit"]["psbt"]["hex"]
reveal_hex = resp["chains"][0]["reveals"][0]["psbt"]["hex"]


def dump_input(label, psbt):
  print(f"=== {label} ===")
  for i, inp in enumerate(psbt.inputs):
    print(f"  input[{i}]:")
    for attr in dir(inp):
      if attr.startswith("_"):
        continue
      val = getattr(inp, attr, None)
      if callable(val):
        continue
      try:
        if val is None:
          continue
        if isinstance(val, (list, dict, set, bytes)) and len(val) == 0:
          continue
      except Exception:
        pass
      preview = repr(val)
      if len(preview) > 200:
        preview = preview[:200] + "...[truncated]"
      print(f"    {attr}: {preview}")
  print(f"  outputs:")
  for i, vout in enumerate(psbt.tx.vout):
    print(f"    [{i}] value={vout.value} spk={vout.script_pubkey.data.hex()}")
  print()


print("commit raw len:", len(commit_hex) // 2)
psbt_commit = PSBT.parse(bytes.fromhex(commit_hex))
dump_input("COMMIT", psbt_commit)

print("reveal raw len:", len(reveal_hex) // 2)
psbt_reveal = PSBT.parse(bytes.fromhex(reveal_hex))
dump_input("REVEAL", psbt_reveal)


# Try sign_with using a key whose xonly == the wallet pubkey from the leaf.
# We don't have the user's privkey; use a random one and observe what embit
# does. The signature won't be valid but we want to see whether embit
# RECOGNIZES the input as signable.
print("=== signing probe with a throwaway random key ===")
test_key = ec.PrivateKey(b"\x42" * 32)
print("test xonly:", test_key.xonly().hex())
print()
for label, psbt_hex in [("commit", commit_hex), ("reveal", reveal_hex)]:
  p = PSBT.parse(bytes.fromhex(psbt_hex))
  signed = p.sign_with(test_key)
  print(f"{label}: sign_with returned {signed} signatures")
  for i, inp in enumerate(p.inputs):
    sigs = []
    for a in ("partial_sigs", "taproot_key_sig", "taproot_sigs", "final_scriptwitness"):
      v = getattr(inp, a, None)
      if v:
        sigs.append(a)
    print(f"  input[{i}] populated sig fields: {sigs}")
  print()


# Now try with a key that matches. We have the xonly pk from the leaf; if
# we can construct a private key whose xonly == that pubkey... we can't
# (one-way). So the only meaningful test is whether sign_with would attempt
# anything. The "signed=N" count tells us: if N>0 with the WRONG key, embit
# is naive (would sign anything); if N=0, embit correctly refuses.
print("=== inject TAP_BIP32_DERIVATION manually and re-test ===")
# Pull leaf and xonly from the leaf script for reveal[0]
xonly_in_leaf = bytes.fromhex(
  "9d2a1670e79e7ff6ee16aa34fe151a3a879be9758be240e5110371a118e1fd39"
)
p = PSBT.parse(bytes.fromhex(reveal_hex))
inp = p.inputs[0]
# Find the (script, leaf_ver) and compute leaf_hash
for attr in ("taproot_scripts", "taproot_leaf_scripts"):
  ts = getattr(inp, attr, None)
  if ts:
    print(f"  reveal taproot scripts container: .{attr} = {type(ts).__name__}, len={len(ts)}")
    for k, v in ts.items():
      print(f"    key type: {type(k).__name__}; key preview:", k if isinstance(k, bytes) else k)
      print(f"    val type: {type(v).__name__}; val len:", len(v) if hasattr(v, '__len__') else 'n/a')
    break
print()
print("inp.taproot_internal_key:", getattr(inp, "taproot_internal_key", None))
print("inp.taproot_bip32_derivations:", getattr(inp, "taproot_bip32_derivations", None))
