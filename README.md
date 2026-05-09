# tacit-cli

[Tacit](https://tacit.unode.one) PMINT 协议（Bitcoin 主网代币协议）的命令行
工具。读索引器（资产 / 持有人 / 地址）+ 本地用 WIF 私钥签名直接 mint，
不依赖任何浏览器钱包扩展。

状态：主网端到端跑通。Mint 流程是从真实链上 Tacit 交易反推出来的，
对照实测 `/api/mint/build` 和 `/api/mint/extract` 响应验证过，已成功
mint FAIR（详见 `docs/PROTOCOL_NOTES.md`）。

## 能干啥

- `tacit assets` / `tacit holders <ticker>` / `tacit address <btc_addr>`
  ——纯只读，不需要私钥
- `tacit mint plan`——调 `/api/mint/build`，打印计划，**不签名不广播**
- `tacit mint run`——完整流程：拉 UTXO → build → 本地签 PSBT → extract
  → 通过 Esplora 广播（默认 blockstream.info，自动 fallback 到
  mempool.space）

签名覆盖：

- Commit 交易：BIP-86 P2TR key-path Schnorr
- Reveal 交易：tap-script-path Schnorr，对应 inscription 风格的 Tacit
  envelope（`<xonly_pk> CHECKSIG OP_0 OP_IF "TACIT" 01 <payload> OP_ENDIF`）
- count > 1 时的 chained reveal（一笔 commit 资助 N 笔级联 reveal）

`tacit_cli/signer.py` 里的安全网：

- 按交易类型分别校验输出（commit 必须付 NUMS-H taproot + 找零回
  `fromAddress`；reveal 必须 `vout[0]` 付 `receiver`）
- chained reveal 资助输出走白名单（防第三方地址重定向）
- envelope 载荷锚点校验：leaf payload 第 1..33 字节必须等于 `asset_id`，
  第 33..65 字节必须等于该资产的 `etch_txid`
- `sign_with` 后任何输入未签 → 直接 raise（不 warn 不静默）

## 安装

```bash
# Windows
setup_env.bat
activate.bat

# Linux / macOS / Git Bash
./setup_env.sh
source ./activate.sh
```

两个脚本都会建 `.venv/` 并装 `requirements.txt`（`requests`、`embit`）。

## 只读命令（不需要私钥）

```bash
tacit assets                                      # 资产列表 + 索引概览
tacit assets --json
tacit holders FAIR                                # 分页持有人
tacit holders FAIR --all --csv fair-holders.csv   # 翻完所有页导 CSV
tacit holders <asset_id_hex> --page 2 --page-size 50
tacit address bc1q7n644hxtjfsvk2vygmyda9tqrcu0v8q6zhnsw3
tacit address bc1p... --json
```

也可以用模块方式跑：`python -m tacit_cli assets`。

## Mint（不可逆，谨慎操作）

1. 把 WIF 放进项目根目录或上一层目录的 `.env`：

   ```
   TACIT_WIF=Kx...你的WIF...
   ```

   加载器**只读** `TACIT_` 开头的 key，**绝不**打印任何值。`.env`
   已 gitignore。

2. 干跑（不签名、不广播）：

   ```bash
   tacit mint plan --address bc1p7z6s... --asset FAIR --count 1 --fee-rate 8 \
     --pubkey-hex <你的-xonly-32B-hex>
   ```

3. 实跑（默认要打 `YES` 确认，加 `--yes` 跳过）：

   ```bash
   tacit mint run --address bc1p7z6s... --asset FAIR --count 1 --fee-rate 8
   ```

   `--count >= 5` 会触发协议的服务费输出；build 响应里会显示收款地址
   和金额，签名器会把这个地址加白名单，不会被"第三方输出"规则拒掉。

4. mint 日志写到 `mint_log_<ts>.jsonl`（用 `--log-dir` 改路径）。
   日志里包含已签名的 raw tx hex 和 txid——commit 已发 reveal 没发的
   时候就崩了，靠这个能恢复。

费率调优、故障恢复和边界情况见 `docs/MINT.md`。

## 项目结构

```
tacit_cli/
  client.py        # 只读 HTTP 客户端（assets / holders / address / utxos）
  cli.py           # 主入口 'tacit' + 只读子命令
  mint.py          # build → sign → extract → broadcast 编排
  mint_cli.py      # 'tacit mint plan|run' 子命令
  signer.py        # WifSigner：校验并签 commit / reveal PSBT
  broadcast.py     # Esplora 客户端，带 fallback 和幂等处理
  envload.py       # 极简 .env 加载器
docs/
  PROTOCOL_NOTES.md    # Tacit envelope 反推过程
  MINT.md              # mint 用法 + 故障恢复
  REVIEW_FINDINGS.md   # codex review 发现的问题及修复
samples/
  build_resp_real.json # 实测 /api/mint/build 成功响应
  probe_*.py           # 协议层验证脚本
```

## 致谢

协议反推基于真实链上 Tacit reveal 交易和公开索引器
`https://tacit.unode.one`。**独立项目，与 Tacit 索引器运营方无关**。
