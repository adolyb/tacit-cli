# Tacit PMINT 协议结构（实测反推）

样本：`bc1p7z6snxwjv9cv7kduae5sqd07zvsc3y9pwxqc5sgdrqnza67tuxgs26kzv2` 的一笔 FAIR mint。
- commit txid: `91a7df7f08f73a6618867d563786bf62e2f5f0d85af70e19b84afd9e96117554`
- reveal txid: `b381f9dd88b2f02daa33868cb8529ce7bb13e262b0217148d4d447f23acf37c7`

## Commit tx

普通 P2TR key-path 花费。

- 输入：用户 P2TR UTXO（`bc1p7z6s...`）
- witness：1 项 64-byte = key-path Schnorr 签名（BIP-341）
- 输出 0：`878 sat` → commit 地址（taproot(NUMS_H, [leaf]))
- 输出 1：找零回原 P2TR

签名要点：标准 BIP-341 key-path，embit `psbt.sign_with(root_key)` 直接搞定。

## Reveal tx — Tacit envelope

输入：花 commit 输出 0。witness 是 tap-script-path 标准 3 项：
```
[0] schnorr_sig         (64 字节)
[1] leaf_script         (变长)
[2] control_block       (33 字节起，1 leaf 时正好 33)
```

### Leaf script 结构

```
20 <32-byte xonly user pubkey>   ; OP_PUSHBYTES_32
ac                               ; OP_CHECKSIG
00                               ; OP_0 / OP_FALSE
63                               ; OP_IF
05 5441434954                    ; "TACIT" magic
01 01                            ; version byte 0x01
4c <len> <payload>               ; OP_PUSHDATA1 + 1-byte length + payload
68                               ; OP_ENDIF
```

`OP_0 OP_IF ... OP_ENDIF` 让 body 永不执行 ⇒ 纯数据载体（inscription envelope 风格）。

### Payload (138 字节示例)

| 偏移 | 字节数 | 含义 |
|------|-------|------|
| 0    | 32    | asset_id（FAIR = `c4a678d6...`） |
| 32   | 32    | etch_txid（`c2542e7f...`） |
| 64   | ?     | 后续 74 字节包含 amount / receiver scriptPubKey / nonce 等，**未完全 RE，原样从服务器 PSBT 里拷过来即可** |

### Control block

`c1 50929b74c1a04954b78b4b6035e97a5e078a5a0f28ec96d547bfee9ace803ac0`

- 第一字节 `c1` = leaf_version(0xc0) | parity(1)
- 后 32 字节 = **BIP-341 NUMS 点 H** （常量）：保证 commit 输出**没有 key-path 花费可能**，必须走 script-path

### 签名要点

leaf 只有 `<pk> CHECKSIG`，所以 reveal 签名 = 标准 BIP-341 tap-script-path Schnorr：

```
sighash = TapSighash(tx, input_index, prevouts, leaf_hash, sighash_type=DEFAULT)
sig     = Schnorr(privkey, sighash)
```

embit 在 PSBT 里只要看到下列 BIP-371 字段就能自动签：
- `PSBT_IN_TAP_LEAF_SCRIPT` (0x15)：(script, leaf_ver) 元组
- `PSBT_IN_TAP_BIP32_DERIVATION` (0x16)：把 user xonly_pk 关联到 leaf hash
- `PSBT_IN_WITNESS_UTXO` (0x01)：commit 输出（用于 sighash 用到的 prevout 数据）

### 校验防恶意 PSBT

签名前必做：

1. **校验 commit 地址**：用本地计算的 leaf_hash + NUMS H 重算 `taproot()`，应等于服务器返回的 commit 输出 scriptPubKey。
2. **校验 reveal 输出**：reveal 的 vout[0] 必须是 `config.receiver_address`（FAIR 接收）。
3. **校验载荷前 64 字节**：必须是 `<config.asset_id> + <known_etch_txid>`，防服务器偷换资产。
4. **载荷里如果有 receiver scriptPubKey 字段**：和 receiver_address 解码后的 scriptPubKey 比对。

NUMS H 常量（写死）：
```python
NUMS_H = bytes.fromhex("50929b74c1a04954b78b4b6035e97a5e078a5a0f28ec96d547bfee9ace803ac0")
```

## 费用观察

样本是 `--count 1` 的最小批：
- commit：205 vbytes，310 sat fee（约 1.5 sat/vB，慢）
- reveal：382 字节 / 664 weight = 166 vBytes，332 sat fee（约 2 sat/vB）

mempool 当前若需快确认建议 ≥ 5 sat/vB。

## 服务费 reveal（待 RE）

`/api/mint/build` 响应里有 `serviceFeeRevealCount`：可能是某些 reveal 由用户付费但收益给协议方。当前样本里没看到（serviceFeeRevealCount=0），先按"全部 reveal 都签 + 全部传回 extract"处理，发现服务器报错再细化。

## 总结：脚本可行性

| 部分 | 可行性 | 说明 |
|------|-------|------|
| Commit 签名 | 高 | 标准 P2TR key-path，embit OK |
| Reveal 签名 | 高 | tap-script-path with single CHECKSIG leaf，embit OK，需要 PSBT 含 BIP-371 字段 |
| commit 地址校验 | 高 | NUMS H 写死，本地 taproot 计算 |
| envelope 载荷校验 | 中 | asset_id+etch_txid 容易；其余字段需要再多看几个样本 RE |
| 广播顺序 | 高 | 先 commit 入 mempool，等 1 conf 或入 mempool，再发 reveal |
