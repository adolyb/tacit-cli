# tacit-cli

Read-only CLI for the [Tacit](https://tacit.unode.one) PMINT indexer on Bitcoin,
plus an upcoming FAIR mint helper. The indexer client wraps the public JSON
endpoints (`/api/assets`, `/api/holders`, `/api/address`, `/api/utxos`) and
exposes a small `tacit` command.

## Install

This project must run inside a virtual environment (see global rule).

Windows:

```
setup_env.bat
activate.bat
```

Linux / macOS / Git Bash:

```
./setup_env.sh
source ./activate.sh
```

Both scripts create `.venv/` and install `requirements.txt`.

## Read commands

```
tacit assets
tacit assets --json

tacit holders FAIR
tacit holders FAIR --all --csv fair-holders.csv
tacit holders <asset_id_hex> --page 2 --page-size 50

tacit address bc1q7n644hxtjfsvk2vygmyda9tqrcu0v8q6zhnsw3
tacit address bc1p... --json
```

You can also run via module form: `python -m tacit_cli assets`.

## Mint FAIR (dangerous)

See `docs/MINT.md` (added by the mint module). It requires a private key
(`TACIT_WIF` in `.env`); always test with a tiny amount first before scaling.

## Notes

- Repository ships with a private GitHub remote per project convention
  (`gh repo create <name> --private --source=. --push`).
- Copy `.env.example` to `.env` for local config; `.env` is gitignored.
