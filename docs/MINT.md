# Tacit Mint CLI

Headless, wallet-free mint automation for Tacit (FAIR and other PMINT assets).
Signs PSBTs locally with a WIF private key and broadcasts via mempool.space.

## Security checklist (read before first run)

- **Never commit your WIF.** Pass it via `--wif` from a `.env` file or a
  shell env var, e.g. `--wif "$TACIT_WIF"`. The CLI does not log the WIF
  and the `mint_log_*.jsonl` files do not contain it.
- **Always run `mint plan` first.** It only hits `/api/mint/build`; no
  signing, no broadcast. Verify the asset, the count, the fee, and the
  receiver address.
- **Start with `--count 1`.** Confirm the first commit + reveal pair
  appear on mempool.space before scaling up.
- **The signer refuses PSBTs that do not pay your `--receiver`.** This
  guards against a compromised indexer trying to redirect outputs.
- **Decode PSBTs before high-value runs.** You can pipe `mint plan
  --json` into a wallet's PSBT inspector, or decode hex via:

  ```
  bitcoin-cli decodepsbt $(python -c 'import base64,sys;print(base64.b64encode(bytes.fromhex(sys.argv[1])).decode())' <hex>)
  ```

## Commands

```
# dry-run: build PSBTs, print plan summary, do nothing else.
python -m tacit_cli.mint_cli mint plan \
  --address bc1p... \
  --asset FAIR \
  --count 1 \
  --fee-rate 2 \
  --pubkey-hex <32-byte-xonly>

# full flow: build + sign + extract + broadcast.
python -m tacit_cli.mint_cli mint run \
  --address bc1p... \
  --wif "$TACIT_WIF" \
  --asset FAIR \
  --count 1 \
  --fee-rate 2 \
  --yes        # skips the interactive YES confirmation
```

`--asset` accepts either the ticker (e.g. `FAIR`) or the full 64-hex
asset_id. `--receiver` defaults to `--address` if omitted.

## Fee rate guidance

Mainnet feerate is volatile; check
<https://mempool.space/api/v1/fees/recommended> before running.

- relaxed: `--fee-rate 1` to `2`
- normal: `3` to `8`
- congested: `15` and up

A higher `--fee-rate` rebuilds both commit and reveal at the new rate.

## Failure recovery

Every broadcast appends a record to `mint_log_<ts>.jsonl` in the
working directory:

```
{"ts":...,"kind":"commit","chain":0,"status":"broadcast","txid":"..."}
{"ts":...,"kind":"commit","chain":0,"status":"mempool","txid":"..."}
{"ts":...,"kind":"reveal","chain":0,"index":0,"status":"broadcast","txid":"..."}
```

If the run dies between commit and reveal:

1. Look up the last `commit` `mempool` record and its `txid`.
2. Wait for it to confirm on mempool.space.
3. Find the matching reveal raw hex from `request_extract`'s response
   (you may need to re-run `mint run` with the same UTXOs - the indexer
   will re-issue the same chain, or you can manually replay the saved
   reveal raw hex via `curl -X POST -d <hex> https://mempool.space/api/tx`).

## Operational notes

- The script signs all PSBTs in memory and immediately discards the
  WIF-derived `PrivateKey` when the process exits. Do not run on shared
  hosts.
- `embit` does most heavy lifting (P2WPKH ECDSA, Taproot key-path
  Schnorr, Taproot script-path). If a reveal contains a tap-script-path
  variant `embit` cannot handle, the signer raises `NotImplementedError`
  - in that case fall back to UniSat/OKX wallet UI for that batch.
- The CLI never broadcasts without an explicit `--yes` flag or an
  interactive `YES` confirmation.
