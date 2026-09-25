# 混合思考模型的思考内容进了正文，会把基线吃掉

## 现象

Qwen3.6-35B-A3B（以及同类的混合思考模型）在服务端**默认开启思考**时，
思考过程会写在 `message.content` 里（**不是** `reasoning_content`），
而且它同样占用 `max_tokens`。`baseline.py` 固定的上限是 8192，
于是一道题的大部分预算被思考吃掉，模型还没开始写代码就被截断。

实测（vLLM 0.27.0，`--max-model-len 32768`，未加任何思考相关参数）：

```
请求：{"messages":[{"role":"user","content":"Write a one-line Verilog assign for a 2-input AND."}],
      "max_tokens":300,"temperature":0}
响应：finish_reason = "length"    completion_tokens = 300
      message.reasoning_content 不存在
      content = "Here's a thinking process:\n\n1.  **Analyze User Request:**\n   - **Language:** Verilog\n..."
```

也就是说：**`content` 里全是思考，没有代码**，`finish_reason` 是 `length`。
按 `baseline.py` 的抽取逻辑（优先取 ``` 围栏，其次取 `module TopModule ... endmodule`），
这种情况下什么都抽不到，最终写成空的 `solution.v`，判定为 **L0**。

## 证据

- 上面的请求/响应是 2026-09-25 在模板 `qwen`（id 4477）的实例上直接 curl 得到的
- 同一镜像、同一权重，加上 `--default-chat-template-kwargs '{"enable_thinking":false}'`
  之后，同一个问题的响应变成 `finish_reason="stop"`、`completion_tokens=14`、
  `content = "```verilog\nassign out = a & b;\n```"`，完全干净

## 原因

1. 模型的 chat template 默认 `enable_thinking=true`；思考与回答在同一个 content 流里，
   服务端只有把它**解析到单独的字段**（`--reasoning-parser`）才分得开，
   而分不分得开都不改变「思考也占 `max_tokens`」这一点。
2. `baseline.py` 只发标准字段（`temperature` / `top_p` / `max_tokens`），
   **不会**带 `chat_template_kwargs`，所以每题的思考开关只能由服务端默认值决定。

## 尝试过的办法

| 做法 | 结果 |
| --- | --- |
| 不管它，按默认跑 | 回复全是思考，`finish_reason=length`，判定 L0；基线分数会被截断主导，而不是能力 |
| 在 vLLM 0.16.1（旧镜像）上加 `--reasoning-parser qwen3` | 那是旧镜像的做法，能把思考分流到 `reasoning_content`；但对「思考占满预算」没有帮助 |
| 在 vLLM 0.27.0 上找 `--default-chat-template-kwargs` | **可用**：`--default-chat-template-kwargs '{"enable_thinking":false}'` 实测把思考关掉，回复干净（14 token 直接给代码） |
| 找 EngineArgs 的字段 | 找不到：0.27 里它不是 dataclass 字段，而是 CLI 层的选项，所以按字段名去查会误判为「不支持」 |

## 为什么要写进方案

- **必须写进 `MODEL.md`**：思考开关属于服务配置，而它直接决定基线看到什么；
  不声明、不固定，增益的分子分母就不可比（`SCORING.md` 第 3.2 节）。
- **对混合思考模型，这是一票否决的配置项**：开着思考跑基线，等于把 40 分的分母按 L0 计。
- 反过来，如果在服务端关掉思考、而 agent 又通过请求参数打开（`chat_template_kwargs`
  是请求级字段，`baseline.py` 不发、agent 可以发），就会人为拉大分子分母的差距。
  这一点在计划 §7 第 3 条里列为需要团队确认的合规口径，**本轮一律按「两边都关」处理**。
