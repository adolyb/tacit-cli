"""End-to-end synthetic test: build a Tacit-shape PSBT keyed to a known
test private key and see if embit signs it via sign_with.
"""

import hashlib
from embit import ec
from embit.psbt import PSBT, InputScope, OutputScope
from embit.transaction import Transaction, TransactionInput, TransactionOutput
from embit.script import Script

NUMS_H = bytes.fromhex(
  "50929b74c1a04954b78b4b6035e97a5e078a5a0f28ec96d547bfee9ace803ac0"
)


def tagged_hash(tag, data):
  th = hashlib.sha256(tag.encode()).digest()
  return hashlib.sha256(th + th + data).digest()


def cs(n):
  if n < 0xfd: return bytes([n])
  if n <= 0xffff: return b"\xfd" + n.to_bytes(2, "little")
  if n <= 0xffffffff: return b"\xfe" + n.to_bytes(4, "little")
  return b"\xff" + n.to_bytes(8, "little")


def tapleaf_hash(ver, script):
  return tagged_hash("TapLeaf", bytes([ver]) + cs(len(script)) + script)


def tweak_pubkey(internal_xonly, merkle):
  pk = ec.PublicKey.from_xonly(internal_xonly)
  out = pk.taproot_tweak(merkle)
  return out.xonly(), out.sec()[0] == 0x03


# --- generate a test wallet
sk = ec.PrivateKey(b"\x07" * 32)
pk = sk.get_public_key()
xonly = sk.xonly()
print("user xonly:", xonly.hex())

# --- build Tacit-shaped leaf script with our xonly inside the envelope
PAYLOAD = bytes.fromhex(
  "28"
  + "c4a678d6d674cdd0f4a1a9df0cb5980bd1255bd0b62f8ddc886e61bd43f56b83"
  + "c2542e7fbaa8c0c9fa632d8720ebf0ba602f9cda8a4c4b1e5ca5d9e41acc4067"
  + "02a72225e567dfc94a8853bafed0256192a75ce88420941475c439c60bb1b3f5d6"
  + "6400000000000000"
  + "d19d2bc900be4e79902fa705c8cc4a570ea67ca11ddd601d250185504afaa80b"
)
assert len(PAYLOAD) == 138

leaf = (
  b"\x20" + xonly + b"\xac"
  + b"\x00\x63\x05" + b"TACIT"
  + b"\x01\x01"
  + b"\x4c" + bytes([len(PAYLOAD)]) + PAYLOAD
  + b"\x68"
)
leaf_h = tapleaf_hash(0xc0, leaf)
print("leaf_hash:", leaf_h.hex())

# --- compute commit P2TR address (NUMS-H + leaf)
out_xonly, parity = tweak_pubkey(NUMS_H, leaf_h)
commit_spk = b"\x51\x20" + out_xonly
print("commit spk:", commit_spk.hex())

# --- build a fake commit tx whose output 0 is the commit
fake_prev = bytes(32)
prev_in = TransactionInput(fake_prev, 0, Script(b""), 0xfffffffd)
out0 = TransactionOutput(1874, Script(commit_spk))
fake_commit = Transaction(version=2, vin=[prev_in], vout=[out0], locktime=0)
commit_txid = fake_commit.txid()

# --- build the reveal: input spends fake_commit:0, output 1 to receiver xonly
reveal_recipient = b"\x51\x20" + xonly  # send back to ourselves
reveal_in = TransactionInput(commit_txid, 0, Script(b""), 0xfffffffd)
reveal_out = TransactionOutput(546, Script(reveal_recipient))
reveal_tx = Transaction(version=2, vin=[reveal_in], vout=[reveal_out], locktime=0)

# --- build PSBT and populate input field
psbt = PSBT(reveal_tx)
inp = psbt.inputs[0]
inp.witness_utxo = TransactionOutput(1874, Script(commit_spk))

control_block = bytes([0xc0 | (1 if parity else 0)]) + NUMS_H
inp.taproot_scripts = {control_block: leaf + bytes([0xc0])}

# Inject TAP_BIP32_DERIVATION
inp.taproot_bip32_derivations[xonly] = ([leaf_h], (b"\x00\x00\x00\x00", "m"))

print("\n--- sign_with on synthetic PSBT ---")
signed = psbt.sign_with(sk)
print("signatures:", signed)
print("taproot_sigs:", inp.taproot_sigs)
print("taproot_script_sigs:", getattr(inp, "taproot_script_sigs", None))
print("final_scriptwitness:", inp.final_scriptwitness)
print("partial_sigs:", inp.partial_sigs)

# --- attempt without injection (control)
print("\n--- without TAP_BIP32_DERIVATION ---")
psbt2 = PSBT(reveal_tx)
i2 = psbt2.inputs[0]
i2.witness_utxo = TransactionOutput(1874, Script(commit_spk))
i2.taproot_scripts = {control_block: leaf + bytes([0xc0])}
signed = psbt2.sign_with(sk)
print("signatures:", signed)
print("taproot_sigs:", i2.taproot_sigs)
