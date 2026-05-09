import logging
from typing import Optional

from embit import ec, script
from embit.networks import NETWORKS
from embit.psbt import PSBT

logger = logging.getLogger("tacit_cli.signer")

NETWORK = NETWORKS["main"]
DUST_THRESHOLD = 546

# BIP-341 NUMS point H — internal key for any taproot output that should NOT
# be key-path spendable. Tacit commit addresses always use this so the only
# way to spend them is via the script-path leaf containing the user pubkey.
NUMS_H = bytes.fromhex(
  "50929b74c1a04954b78b4b6035e97a5e078a5a0f28ec96d547bfee9ace803ac0"
)
TACIT_MAGIC = b"TACIT"
TACIT_VERSION = 0x01


class SignerError(Exception):
  pass


class WifSigner:
  """In-memory WIF signer for Tacit PSBTs.

  Two distinct entry points (commit vs reveal) so output-validation rules
  cannot be cross-applied. embit handles the actual secp256k1 work; we only
  parse and verify what the server sent.
  """

  def __init__(self, wif: str):
    self._key = ec.PrivateKey.from_wif(wif)
    self._pub = self._key.get_public_key()

  @property
  def pubkey_hex(self) -> str:
    return self._pub.sec().hex()

  @property
  def xonly_pubkey_hex(self) -> str:
    return self._key.xonly().hex()

  @property
  def address(self) -> str:
    return script.p2tr(self._pub).address(NETWORK)

  @property
  def p2wpkh_address(self) -> str:
    return script.p2wpkh(self._pub).address(NETWORK)

  def sign_commit_psbt(self, psbt_hex: str, expected_from_address: str) -> str:
    """Sign a commit PSBT after verifying outputs only flow to commit/change."""
    psbt = _load_psbt(psbt_hex)
    _verify_commit_outputs(psbt, expected_from_address)
    return _sign_and_serialize(psbt, self._key)

  def sign_reveal_psbt(
    self,
    psbt_hex: str,
    expected_receiver_address: str,
    expected_asset_id_hex: str,
    expected_etch_txid_hex: str,
    allowed_extra_scripts: Optional[set] = None,
  ) -> str:
    """Sign a reveal PSBT after verifying outputs and envelope payload.

    `allowed_extra_scripts` is a set of scriptPubKey bytes that are
    permitted as non-receiver outputs (e.g. chained-reveal funding for
    count>1 mints, or known service-fee recipient script).
    """
    psbt = _load_psbt(psbt_hex)
    _verify_reveal_outputs(psbt, expected_receiver_address, allowed_extra_scripts or set())
    _verify_reveal_envelope(
      psbt,
      bytes.fromhex(expected_asset_id_hex),
      bytes.fromhex(expected_etch_txid_hex),
    )
    return _sign_and_serialize(psbt, self._key)


def _load_psbt(psbt_hex: str) -> PSBT:
  try:
    raw = bytes.fromhex(psbt_hex.strip())
  except ValueError as exc:
    raise SignerError(f"psbt is not valid hex: {exc}")
  return PSBT.parse(raw)


def _sign_and_serialize(psbt: PSBT, key) -> str:
  signed_count = psbt.sign_with(key)
  unsigned = []
  for i, inp in enumerate(psbt.inputs):
    has_sig = bool(
      getattr(inp, "partial_sigs", None)
      or getattr(inp, "taproot_key_sig", None)
      or getattr(inp, "taproot_sigs", None)
      or getattr(inp, "final_scriptwitness", None)
    )
    if not has_sig:
      unsigned.append(i)
  if unsigned:
    # Treat as fatal — silently returning a half-signed PSBT to the server
    # leads to extract failure or a broadcast that cannot finalize.
    raise SignerError(
      f"psbt inputs {unsigned} unsigned after sign_with (signed={signed_count}); "
      f"server PSBT likely missing BIP-371 fields or wrong key"
    )
  return psbt.serialize().hex()


# ---- output validators ------------------------------------------------------

def _verify_commit_outputs(psbt: PSBT, expected_from_address: str) -> None:
  """Commit must have one P2TR commit output (NUMS-H taproot) plus only
  fromAddress change. Anything else means the indexer is trying to redirect
  funds.
  """
  from_script = script.Script.from_address(expected_from_address)
  saw_commit = False
  for i, vout in enumerate(psbt.tx.vout):
    spk = vout.script_pubkey
    if spk.data == from_script.data:
      continue
    if _is_p2tr(spk):
      if saw_commit:
        raise SignerError(f"commit output {i}: multiple P2TR outputs")
      saw_commit = True
      continue
    if vout.value <= DUST_THRESHOLD and _is_op_return(spk):
      continue
    raise SignerError(
      f"commit output {i} ({vout.value} sats) is neither commit nor change: "
      f"{spk.data.hex()}"
    )
  if not saw_commit:
    raise SignerError("commit psbt has no P2TR commit output")


def _verify_reveal_outputs(
  psbt: PSBT,
  expected_receiver_address: str,
  allowed_extra_scripts: set,
) -> None:
  """Reveal must pay receiver at vout[0]. Other non-dust outputs are rejected
  unless they are OP_RETURN data carriers OR explicitly whitelisted (used
  for chained reveals: vout[1] funds the next reveal in a count>1 plan).
  """
  receiver_script = script.Script.from_address(expected_receiver_address)
  if not psbt.tx.vout:
    raise SignerError("reveal psbt has no outputs")
  if psbt.tx.vout[0].script_pubkey.data != receiver_script.data:
    raise SignerError(
      f"reveal vout[0] does not pay receiver {expected_receiver_address}"
    )
  for i, vout in enumerate(psbt.tx.vout[1:], start=1):
    spk = vout.script_pubkey
    if spk.data == receiver_script.data:
      continue
    if _is_op_return(spk):
      continue
    if spk.data in allowed_extra_scripts:
      continue
    if vout.value > DUST_THRESHOLD:
      raise SignerError(
        f"reveal output {i} ({vout.value} sats) is third-party: {spk.data.hex()}"
      )


def _is_p2tr(spk: "script.Script") -> bool:
  data = spk.data
  return len(data) == 34 and data[0] == 0x51 and data[1] == 0x20


def _is_op_return(spk: "script.Script") -> bool:
  data = spk.data
  return bool(data) and data[0] == 0x6a


# ---- envelope payload verification -----------------------------------------

def _verify_reveal_envelope(
  psbt: PSBT,
  expected_asset_id: bytes,
  expected_etch_txid: bytes,
) -> None:
  """Walk reveal inputs, find the Tacit leaf script, and confirm the envelope
  identifies our asset. Catches an indexer that returns a structurally valid
  PSBT but for a different asset.
  """
  for inp_idx, inp in enumerate(psbt.inputs):
    leaves = _collect_leaf_scripts(inp)
    for leaf_script in leaves:
      payload = _parse_tacit_envelope(leaf_script)
      if payload is None:
        continue
      # Payload layout (from sample reveal RE):
      #   [0]      single tag byte (often 0x28)
      #   [1:33]   asset_id (32 bytes)
      #   [33:65]  etch_txid (32 bytes)
      # Remaining ~73 bytes encode amount/receiver/nonce; not RE'd yet,
      # so we only assert the two anchors we know.
      if len(payload) < 65:
        raise SignerError(
          f"input {inp_idx}: tacit envelope payload too short ({len(payload)})"
        )
      if payload[1:33] != expected_asset_id:
        raise SignerError(
          f"input {inp_idx}: envelope asset_id mismatch "
          f"(got {payload[1:33].hex()}, want {expected_asset_id.hex()})"
        )
      if payload[33:65] != expected_etch_txid:
        raise SignerError(
          f"input {inp_idx}: envelope etch_txid mismatch "
          f"(got {payload[33:65].hex()}, want {expected_etch_txid.hex()})"
        )
      return
  raise SignerError("no Tacit envelope found in any reveal input leaf script")


def _collect_leaf_scripts(inp) -> list:
  """Return raw leaf script bytes from embit's taproot_scripts container.

  embit stores it as {control_block_bytes: leaf_script + leaf_ver_byte}.
  Strip the trailing leaf-version byte before returning. We tolerate older
  embit schemas (tuple keys, swapped key/val) as a fallback.
  """
  out = []
  for attr in ("taproot_scripts", "taproot_leaf_scripts"):
    container = getattr(inp, attr, None)
    if not container or not isinstance(container, dict):
      continue
    for key, val in container.items():
      # Modern embit: key=control_block, val=leaf_script||leaf_ver
      if isinstance(val, (bytes, bytearray)) and len(val) >= 2:
        out.append(bytes(val[:-1]))
        continue
      # Older shapes: (script, leaf_ver) tuple in either key or value
      if isinstance(val, tuple) and isinstance(val[0], (bytes, bytearray)):
        out.append(bytes(val[0]))
        continue
      if isinstance(key, tuple) and isinstance(key[0], (bytes, bytearray)):
        out.append(bytes(key[0]))
  return out


def _parse_tacit_envelope(leaf_script: bytes) -> Optional[bytes]:
  """Match the inscription-style envelope and return the payload bytes.

  Expected layout (sample reveal `b381f9dd...`):
    20 <32B xonly_pk> ac 00 63 05 "TACIT" 01 <ver> 4c <len> <payload> 68
  Anything that does not match this exact shape returns None.
  """
  s = leaf_script
  i = 0
  n = len(s)
  if n < 47:
    return None
  if s[i] != 0x20:
    return None
  i += 1 + 32  # skip xonly pubkey
  if i >= n or s[i] != 0xac:  # OP_CHECKSIG
    return None
  i += 1
  if i >= n or s[i] != 0x00:  # OP_0 / FALSE
    return None
  i += 1
  if i >= n or s[i] != 0x63:  # OP_IF
    return None
  i += 1
  if i + 1 >= n or s[i] != 0x05 or s[i + 1:i + 1 + 5] != TACIT_MAGIC:
    return None
  i += 1 + 5
  if i + 1 >= n or s[i] != 0x01 or s[i + 1] != TACIT_VERSION:
    return None
  i += 2
  if i >= n or s[i] != 0x4c:  # OP_PUSHDATA1
    return None
  i += 1
  if i >= n:
    return None
  payload_len = s[i]
  i += 1
  if i + payload_len + 1 > n:
    return None
  payload = s[i:i + payload_len]
  if s[i + payload_len] != 0x68:  # OP_ENDIF
    return None
  return payload
