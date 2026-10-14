> 2026-10-14 整理补注：以下是历史选型或失败分析，不能作为当前服务配置。后续证据见[AutoDL 实测](2026-10-11-autodl-qwen3-results.md)与[输出额度补测](2026-10-11-qwen3-output-budget.md)，运行方式见[手册](../user-manual.md)；最终提交模型仍须独立确认。

> **文档状态：归档笔记：结论、路径与命令反映当时实验或设计。** 历史证据保留，当前框架用法与限制以[详细参考](../user-manual.md)为准。

# 混合思考模型的思考内容进了正文，会把基线吃掉

| 项 | 内容 |
| --- | --- |
| 状态 | **已解决**（服务端关思考即可）；**提交层面待办**见文末 |
| 影响 | 基线口径——开着思考跑基线，等于把 40 分的分母按 L0 计 |
| 最后更新 | 2026-09-27 |
| 相关运行 | `20260925-194130`（`Qwen3.6-35B-A3B` 关思考后跑通全题集）、`20260927-152225`（`gpt-oss-20b` 默认即无思考） |
| 相关决策 | [`../decisions/0002-model-choice.md`](0002-model-choice.md)（服务配置口径） |

## 问题

Qwen3.6-35B-A3B 这类**混合思考模型**在服务端默认开启思考时，思考过程会写进
`message.content`（**不是** `reasoning_content`），而且同样占用 `max_tokens`。
`baseline.py` 固定的上限是 8192，于是一道题的大部分预算被思考吃掉，模型还没开始写代码
就被截断。

实测（vLLM 0.27.0，`--max-model-len 32768`，未加任何思考相关参数）：

```
请求：{"messages":[{"role":"user","content":"Write a one-line Verilog assign for a 2-input AND."}],
      "max_tokens":300,"temperature":0}
响应：finish_reason = "length"    completion_tokens = 300
      message.reasoning_content 不存在
      content = "Here's a thinking process:\n\n1.  **Analyze User Request:**\n   - **Language:** Verilog\n..."
```

`content` 里全是思考、没有代码，`finish_reason` 是 `length`。按 `baseline.py` 的抽取逻辑
（优先取 ``` 围栏，其次取 `module TopModule ... endmodule`），这种情况下什么都抽不到，
最终写成空的 `solution.v`，判定为 **L0**。

**原因**：

1. 模型的 chat template 默认 `enable_thinking=true`；思考与回答在同一个 content 流里，
   服务端只有把它**解析到单独的字段**（`--reasoning-parser`）才分得开——而分不分得开
   都不改变「思考也占 `max_tokens`」这一点。
2. `baseline.py` 只发标准字段（`temperature` / `top_p` / `max_tokens`），**不会**带
   `chat_template_kwargs`，所以每题的思考开关只能由**服务端默认值**决定。

## 已解决

**做法**：起服务时加

```bash
--default-chat-template-kwargs '{"enable_thinking":false}'
```

**验证**（同一镜像、同一权重、同一个问题）：

| 配置 | 结果 |
| --- | --- |
| 默认（开思考） | `finish_reason="length"`、`completion_tokens=300`、正文全是思考 |
| 加 `enable_thinking=false` | `finish_reason="stop"`、`completion_tokens=14`、`content = "```verilog\nassign out = a & b;\n```"`（干净） |

之后 `Qwen3.6-35B-A3B`、`Qwen3.5-35B-A3B`、`Qwen3.5-9B` 全部按这个配置跑通全题集
（例如 `20260925-194130` 得 0.610）。

**两个排查要点**（当时踩过）：

- `--default-chat-template-kwargs` 在 vLLM 0.27 里**不是** `EngineArgs` 的 dataclass 字段，
  而是 CLI 层选项——按字段名去查会误判为「不支持」。
- 旧镜像（vLLM 0.16.1）的习惯做法是加 `--reasoning-parser qwen3` 把思考分流到
  `reasoning_content`；那只改变字段位置，**对「思考占满预算」没有帮助**。

**不是所有模型都要关**：`gpt-oss-20b` 用默认配置跑就没有思考内容（`reasoning_content`
为空、回复是干净的代码块，运行 `20260927-152225` 得 0.689）。所以「默认是否开思考」
要**逐模型确认**，不能一律假设。

## 未解决

### 提交层面必须做的事

1. **把口径写进 `MODEL.md`**：思考开关属于服务配置，直接决定基线看到什么；不声明、不固定，
   增益的分子分母就不可比（`SCORING.md` 第 3.2 节）。
2. **确认最终选定模型的默认行为**：若它默认开思考，`serve/vllm.sh` 必须带上关闭参数；
   若默认不开（如 gpt-oss），则不需要，但要写明依据。
3. **合规口径要团队确认**：如果在服务端关掉思考、而 agent 又通过请求级参数
   (`chat_template_kwargs`，`baseline.py` 不发、agent 可以发) 打开，就会**人为拉大**分子分母的
   差距。计划第 7 节第 3 条把它列为待确认项，**本轮一律按「两边都关」处理**。

## 证据

- 上面的请求/响应是 2026-09-25 在模板 `qwen`（id 4477）的实例上直接 curl 得到的
- 运行目录：`../runs/20260925-194130-…/`、`../runs/20260927-152225-…/`
