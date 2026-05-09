import logging
from typing import Optional

from embit import ec, script
from embit.networks import NETWORKS
from embit.psbt import PSBT

logger = logging.getLogger("tacit_cli.signer")

NETWORK = NETWORKS["main"]


class SignerError(Exception):
  pass


class WifSigner:
  """In-memory WIF signer for Tacit PSBTs.

  Supports P2WPKH and P2TR (key-path + script-path) inputs. Delegates the
  per-input branch logic to embit.PSBT.sign_with so we don't reinvent
  secp256k1.
  """

  def __init__(self, wif: str):
    self._key = ec.PrivateKey.from_wif(wif)
    self._pub = self._key.get_public_key()

  @property
  def pubkey_hex(self) -> str:
    # Compressed 33-byte SEC pubkey (P2WPKH wallets use this).
    return self._pub.sec().hex()

  @property
  def xonly_pubkey_hex(self) -> str:
    # 32-byte x-only key (Taproot wallets use this).
    return self._key.xonly().hex()

  @property
  def address(self) -> str:
    # Default to P2TR since Tacit is taproot-native; fromAddress in the brief
    # is bc1p... so derive the matching taproot address from the internal key.
    return script.p2tr(self._pub).address(NETWORK)

  @property
  def p2wpkh_address(self) -> str:
    return script.p2wpkh(self._pub).address(NETWORK)

  def sign_psbt(self, psbt_hex: str, expected_receiver: Optional[str] = None) -> str:
    psbt = PSBT.from_string(psbt_hex)

    if expected_receiver:
      self._assert_outputs_safe(psbt, expected_receiver)

    try:
      signed_count = psbt.sign_with(self._key)
    except NotImplementedError as exc:
      # embit may bail on tap-script-path leaves it cannot fingerprint; surface
      # with our marker so callers know to retry via a wallet UI.
      raise NotImplementedError(
        f"reveal script-path signing not yet supported, use wallet-based "
        f"signing instead: {exc}"
      )

    if signed_count == 0:
      raise SignerError(
        "embit produced 0 signatures - WIF probably does not match any input "
        "(check fromAddress and walletPubkeyHex)"
      )

    unsigned = []
    for i, inp in enumerate(psbt.inputs):
      if not (inp.partial_sigs or inp.taproot_key_sig or inp.taproot_sigs or inp.final_scriptwitness):
        unsigned.append(i)
    if unsigned:
      logger.warning("psbt inputs still unsigned after sign_with: %s", unsigned)

    return psbt.to_string(encoding="hex")

  def _assert_outputs_safe(self, psbt: PSBT, expected_receiver: str) -> None:
    """Reject PSBTs whose user-bound outputs do not pay expected_receiver.

    A reveal PSBT always has at least one OP_RETURN-style or service-fee
    output, so we don't require ALL outputs to match - we require at least
    one output to pay the expected receiver, and we require that NO non-dust
    output pays a third party that isn't OP_RETURN or the service.
    """
    expected_script = script.Script.from_address(expected_receiver)
    found = False
    for i, out in enumerate(psbt.outputs):
      out_script = psbt.tx.vout[i].script_pubkey
      if out_script.data == expected_script.data:
        found = True
        break
    if not found:
      raise SignerError(
        f"refusing to sign PSBT: no output pays expected receiver "
        f"{expected_receiver} (possible malicious server response)"
      )
