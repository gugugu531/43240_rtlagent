# Agent trace 格式

本文描述 `agent` 模式生成的 `trace.jsonl`。主办方提供的 baseline 文件保持不变，baseline
trace 继续使用官方格式。

## 1. 版本规则

当前 `schema_version` 为整数 `1`。

- 新增可选字段或新的 `tool` 类型仍保持当前版本；
- 删除字段、重命名字段或改变已有字段含义时才增加版本；
- 分析程序必须忽略不认识的字段和 `tool`；
- 没有 `schema_version` 的历史 trace 按旧格式读取，不能直接判为损坏。

## 2. 每条事件都有的字段

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `schema_version` | integer | 格式版本，当前为 `1` |
| `run_id` | string | 一次 Agent 运行的标识，同一文件内不变 |
| `seq` | integer | 从 1 开始连续递增，用于恢复事件顺序 |
| `ts` | number | 事件写入时的 Unix 时间戳 |
| `tool` | string | 事件来源或类别 |

调用者即使传入同名字段，也不能覆盖这些公共字段。

## 3. 第一条元数据事件

正常运行的第一条事件为：

```json
{
  "schema_version": 1,
  "run_id": "...",
  "seq": 1,
  "ts": 0,
  "tool": "run",
  "event": "metadata",
  "mode": "agent",
  "task_id": "ex03_lfsr8",
  "config": {
    "agent": {},
    "model_request": {},
    "rtl": {}
  },
  "git": {
    "commit": "...",
    "dirty": false,
    "source": "repository"
  }
}
```

`config` 只保存允许公开的配置，包括轮数、现有时间参数、解析出的顶层模块、开发产物开关、
模型名、模型服务地址和器件型号。它不会保存 API key、Cookie、Authorization 或完整环境变量。

开发仓库中会直接读取 Git commit 和参赛目录的 dirty 状态。打包镜像没有 `.git` 时，可以在
构建阶段设置 `AGENT_GIT_COMMIT` 和 `AGENT_GIT_DIRTY`；两者都没有时明确记录 `null`，不会伪造
版本信息。远端仓库地址不会进入 trace，避免地址中意外包含凭据。

## 4. 秘密处理

写入任何事件前会递归检查字典和列表：

- 敏感字段名的值统一变为 `[redacted]`；
- 已知环境密钥即使出现在错误文本中也会被替换；
- 模型服务 URL 中的用户名、密码、查询参数和 fragment 不会被记录；
- `tokens_in`、`tokens_out` 等普通统计字段不会因为包含单词 `token` 而被误删。

这层保护是最后一道保险。调用者仍应只把必要摘要传给 trace，不应主动传入提示词全文、模型
回复全文、Verilog 正文或秘密。

## 5. 分析器兼容方式

`dev/eval/analyze.py` 会：

- 继续读取没有版本字段的历史 trace；
- 从 `run/metadata` 读取 schema version、run ID 和 Git commit；
- 将这些值写入 `analysis.json` 和 `samples.csv`；
- 忽略不认识的字段；
- 不把 `run` 元数据事件计为 lint、综合等工具调用。
