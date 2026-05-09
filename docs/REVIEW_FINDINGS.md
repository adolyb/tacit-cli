# Codex Review Findings

来源：`codex exec` 真 OpenAI Codex CLI（codex-cli 0.130.0），prompt 见 `.codex_review_prompt.md`，原始输出见 `.codex_review_output.md`。

## Critical（小额试跨前必修）

### C1. commit 与 reveal 用同一套输出校验
**位置**：`tacit_cli/mint.py:177` 和 `tacit_cli/signer.py:80-99`

commit PSBT 的输出是 `[NUMS-H taproot commit, 找零回 fromAddress]`，**没有付 receiver_address 的输出**。`_assert_outputs_safe(expected_receiver=receiver_address)` 会直接 raise，commit 永远签不出。

**修法**：拆成两个函数：
```python
sign_commit_psbt(psbt, expected_from_address, expected_commit_script)
sign_reveal_psbt(psbt, expected_receiver_address)
```
- commit 校验：output[0] == 本地 `taproot(NUMS_H, leaf_hash)` 重算结果；其余输出只能付 fromAddress
- reveal 校验：vout[0] == receiver_address

### C2. `_assert_outputs_safe` 不抵御额外恶意输出
**位置**：`tacit_cli/signer.py:80-99`

只检查"至少一个输出付 receiver"。服务器完全可以加一个 5000 sat 输出给攻击者地址，receiver 仍然有 dust 输出，校验就过了。

**修法**：白名单制，所有非 dust 输出必须是 receiver / OP_RETURN / 已知 service-fee 地址，否则 raise。

### C3. embit 自动签依赖 BIP-371 字段，缺字段静默失败
**位置**：`tacit_cli/signer.py:49-76`

reveal 全靠 `psbt.sign_with(self._key)` 自动判定。**如果服务器返回的 PSBT 没填 `PSBT_IN_TAP_LEAF_SCRIPT (0x15)`、`PSBT_IN_TAP_BIP32_DERIVATION (0x16)`、`PSBT_IN_WITNESS_UTXO`，embit 找不到 leaf_hash 就不签**，当前代码只 `logger.warning`，照样把没签好的 PSBT 返回给 extract，结果交易广播失败。

**修法**：
1. 签前检查每个 reveal 输入：必须有上述 3 个字段
2. 缺字段时**自己注入**（用 PROTOCOL_NOTES 里的常量重建 leaf_script + 计算 leaf_hash + 拼 control_block）
3. 签完每个输入都校验已有 partial_sig / taproot_key_sig，未签的**raise，不 warn**

### C4. envelope 载荷无校验
**位置**：`tacit_cli/signer.py:80-99` 和 `tacit_cli/mint.py:177-183`

reveal leaf script 里嵌着 asset_id + etch_txid + receiver scriptPubKey。代码完全没检查载荷内容，服务器换 asset_id（指向另一种代币）也能过。

**修法**：签 reveal 前解 leaf script，断言：
```python
payload[:32] == bytes.fromhex(config.asset_id)
payload[32:64] == KNOWN_FAIR_ETCH_TXID  # c2542e7fbaa8c0c9fa632d8720ebf0ba602f9cda8a4c4b1e5ca5d9e41acc4067
embedded_receiver_spk == Script.from_address(config.receiver_address).data
```

## Warning（count > 1 批量前修）

### W5. raw_tx_hex 不落盘
**位置**：`tacit_cli/broadcast.py:31-52`、`tacit_cli/mint.py:193-225`

只记 txid。如果 commit 已发但 reveal 还没发就挂了，下次重启没原始 hex 可重发。

**修法**：extract 拿到 raw 后立即写 mint_log 一条 `{"kind":"raw","chain":i,"commit_raw":...,"reveal_raws":[...]}`。

### W6. 4xx 全致命，缺幂等处理
**位置**：`tacit_cli/broadcast.py:43-45`

mempool.space 的 `already in mempool` / `already in block chain` 错误也是 4xx，重跑断点续传时直接挂。

**修法**：识别这两条消息，计算 raw 的 txid 返回，继续走 wait_in_mempool。

### W7. `--wif` 没读 `TACIT_WIF` 环境变量
**位置**：`tacit_cli/mint_cli.py:134`

`.env.example` 和 README 都说支持 `TACIT_WIF`，CLI 没接。

**修法**：`--wif` default = `os.environ.get("TACIT_WIF")`，显式 `--wif` 覆盖 env。

### W8. embit 没进 pyproject 依赖
**位置**：`pyproject.toml:10-12`

`pip install .` 不装 embit，CLI 装上也不能签。

**修法**：`[project].dependencies` 加 `embit>=0.7.0`。
