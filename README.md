# tacit-cli

Headless CLI for the [Tacit](https://tacit.unode.one) PMINT token protocol on
Bitcoin mainnet. Read the indexer (assets / holders / addresses) and mint
tokens locally without a browser wallet.

Status: works end-to-end on mainnet. The mint pipeline was reverse-engineered
from real on-chain Tacit transactions, validated against the live
`/api/mint/build` and `/api/mint/extract` responses, and successfully minted
FAIR (see `docs/PROTOCOL_NOTES.md`).

## What works

- `tacit assets` / `tacit holders <ticker>` / `tacit address <btc_addr>` — pure
  read access, no key needed
- `tacit mint plan` — call `/api/mint/build`, print the plan, never sign
- `tacit mint run` — full pipeline: fetch UTXOs → build → sign PSBTs locally
  with a WIF private key → extract → broadcast via Esplora (blockstream.info,
  with mempool.space fallback)

Mint signing handles:

- Commit tx: BIP-86 P2TR key-path Schnorr
- Reveal tx: tap-script-path Schnorr against the inscription-style Tacit
  envelope (`<xonly_pk> CHECKSIG OP_0 OP_IF "TACIT" 01 <payload> OP_ENDIF`)
- Chained reveals for `count > 1` (single commit funds N reveals)

Safety nets in `tacit_cli/signer.py`:

- Per-tx-type output validation (commit must pay NUMS-H taproot + change to
  `fromAddress`; reveal must pay `receiver` at `vout[0]`)
- Whitelist for chained-reveal funding outputs (no third-party redirection)
- Envelope payload check: leaf payload bytes 1..33 must equal `asset_id` and
  bytes 33..65 must equal the asset's `etch_txid`
- Fatal raise (not a warning) if any input remains unsigned after `sign_with`

## Install

```bash
# Windows
setup_env.bat
activate.bat

# Linux / macOS / Git Bash
./setup_env.sh
source ./activate.sh
```

Both scripts create `.venv/` and install `requirements.txt` (`requests`,
`embit`).

## Read commands (no key needed)

```bash
tacit assets                                      # tokens + indexer overview
tacit assets --json
tacit holders FAIR                                # paginated
tacit holders FAIR --all --csv fair-holders.csv   # walk every page, dump CSV
tacit holders <asset_id_hex> --page 2 --page-size 50
tacit address bc1q7n644hxtjfsvk2vygmyda9tqrcu0v8q6zhnsw3
tacit address bc1p... --json
```

Also runs as a module: `python -m tacit_cli assets`.

## Mint (irreversible — handle with care)

1. Put your WIF in `.env` at the project root or one directory up:

   ```
   TACIT_WIF=Kx...your-WIF...
   ```

   The loader only imports keys starting with `TACIT_` and never logs
   values. `.env` is gitignored.

2. Dry-run plan (no signing, no broadcast):

   ```bash
   tacit mint plan --address bc1p7z6s... --asset FAIR --count 1 --fee-rate 8 \
     --pubkey-hex <your-xonly-32B-hex>
   ```

3. Real mint (asks for a `YES` confirmation unless `--yes` is passed):

   ```bash
   tacit mint run --address bc1p7z6s... --asset FAIR --count 1 --fee-rate 8
   ```

   `--count >= 5` triggers the protocol's service-fee output; the build
   response shows the recipient and amount, and the signer whitelists that
   address so it does not trigger third-party-output rejection.

4. Mint logs are written to `mint_log_<ts>.jsonl` (configurable with
   `--log-dir`). They contain raw signed tx hex and txids — useful for
   resuming a partial run if the process dies between commit and reveal.

See `docs/MINT.md` for fee tuning, recovery, and edge cases.

## Repository layout

```
tacit_cli/
  client.py        # read-only HTTP client (assets, holders, address, utxos)
  cli.py           # main 'tacit' entry point + read subcommands
  mint.py          # build → sign → extract → broadcast orchestration
  mint_cli.py      # 'tacit mint plan|run' subcommands
  signer.py        # WifSigner: validates and signs commit/reveal PSBTs
  broadcast.py     # Esplora client with fallback + idempotency
  envload.py       # minimal .env loader
docs/
  PROTOCOL_NOTES.md    # reverse-engineered Tacit envelope structure
  MINT.md              # mint usage + recovery
  REVIEW_FINDINGS.md   # codex review findings + how each was fixed
samples/
  build_resp_real.json # captured /api/mint/build success response
  probe_*.py           # protocol-level tests
```

## Acknowledgements

Protocol RE based on real on-chain Tacit reveal transactions and the public
indexer at `https://tacit.unode.one`. Independent project — not affiliated
with the Tacit indexer operator.
