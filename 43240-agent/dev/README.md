# dev/ — 团队开发区（不提交）

`43240-agent/` 是要提交给赛事方的方案目录，本目录是其中唯一**不随方案一起提交**的
部分：`.dockerignore` 已经排除了 `dev/`，整理提交文件时也要把它去掉。

> **为什么必须分开放：** 这里会记录失败的题目，还可能摘录 VerilogEval（本赛道用于
> 自测的公开题库）参考答案的片段。这些内容一旦进入提交的方案，就可能被认定为「在
> 技能包或智能体中预置答案」（见 `SCORING.md` 第 2.9、2.10 条），整个赛道（track）
> 的成绩作废。**凡是包含参考答案的内容，只能放在 `dev/`。**

---

## 目录说明

| 路径 | 放什么 | 是否提交到 git |
| --- | --- | --- |
| `notes/` | 开发日志，文件名 `YYYY-MM-DD-<主题>.md` | 是 |
| `experiments/` | 每次跑分一份记录，由脚本自动生成模板，结论手动填写 | 是 |
| `failures/` | 失败原因分析，一类问题一个文件；是 `REPORT.md` 中失败分析的素材 | 是 |
| `remote/` | 远端服务器测试脚本，见下文 | 是（`remote.env` 除外） |
| `runs/` | 跑分生成的文件：solution.v、trace.jsonl（工具调用记录）、Vivado 日志、score.json | 否 |

文件名用英文（与提交规则一致），正文用中文。

## 官方文档索引

仓库根目录和 `../../example/` 都是主办方提供的原始文件，**只读，不要修改**。

| 想查什么 | 看哪里 |
| --- | --- |
| 赛题、提交结构、提交检查清单 | `../../README.md` |
| 评分公式、提交条件、作弊判定 | `../../SCORING.md` |
| 投题接口 `/v1/health`、`/v1/solve`，trace 格式，运行环境 | `../../docs/API_CONTRACT.md` |
| 常见问题 | `../../docs/FAQ.md` |
| 本地判定工具的用法、VerilogEval 题目转换 | `../../selftest/README.md` |
| 设计报告模板 | `../../REPORT_TEMPLATE.md` |
| 示例方案原版（用来对照自己改了什么） | `../../example/`，命令 `diff -r ../../example ..` |

**有两个文件绝对不能改：** `baseline.py` 和 `run_baseline.sh`。可以用
`diff ../../example/baseline.py ../baseline.py` 检查。

---

## 用远端服务器测试

各部分运行的位置：**远端服务器只运行 vLLM（模型推理服务）；智能体、投题接口和
Vivado 判定都在本机运行。** 两边通过 SSH 隧道连接。

```
本机                                                                  远端服务器
日常跑分   remote_selftest.sh ─► run_selftest.sh ─► run.sh ──────────┐
                                                └─► run_baseline.sh ─┤
模拟投题   submit_client.py ─HTTP─► serve_local.sh:7860 ─► 同上 ──────┤
                                                                     ▼
                                   127.0.0.1:18000 ══ SSH 隧道 ══► vLLM 127.0.0.1:8000
判定       judge.py / score.py（使用本机 Vivado）
```

远端的 vLLM 只监听本机地址 `127.0.0.1`，也不设置 API key。原因是 `baseline.py`
发请求时不带身份验证用的 `Authorization` 请求头。用 SSH 隧道，既能让基线脚本连上，
又不会把推理服务暴露到公网。

### 首次配置

```bash
cd 43240-agent/dev/remote
cp remote.env.example remote.env && vi remote.env    # 填写服务器地址、模型路径、上下文长度
```

`run_selftest.sh` 运行时会读取 `selftest/env.sh`，里面的 `LLM_*` 变量会把远端配置
覆盖掉（`remote_selftest.sh` 发现这种情况会停止运行并提示）。请把这几行改成
「没有设置时才使用默认值」的写法：

```bash
export LLM_BACKEND="${LLM_BACKEND:-openai}"
export LLM_BASE_URL="${LLM_BASE_URL:-https://api.deepseek.com}"
export LLM_API_KEY="${LLM_API_KEY:-sk-...}"
export LLM_MODEL="${LLM_MODEL:-deepseek-chat}"
```

这样直接运行 `run_selftest.sh` 时仍然使用商用 API，通过 `remote_selftest.sh` 运行
时则使用远端模型，两者互不影响。

### 启动远端推理服务

```bash
./remote_vllm.sh start      # 把 serve/vllm.sh 复制到远端，并在后台启动
./tunnel.sh up              # 建立 SSH 隧道
./remote_vllm.sh wait       # 等待模型加载完成
./tunnel.sh status          # 查看隧道是否正常、当前模型名
```

远端运行的就是提交方案里的那份 `serve/vllm.sh`，所以测试时的服务配置和
`MODEL.md` 中声明的一致。

### 日常跑分

```bash
./remote_selftest.sh --tag smoke --tasks ../../../tasks --samples 1
./remote_selftest.sh --tag veval-s5 --samples 5
```

除 `--tag` 外，其余参数原样传给 `selftest/run_selftest.sh`，默认题目目录是仓库根目录
的 `tasks/`。方案（agent）和基线（baseline）在同一次运行中使用同一个推理服务，算出
的增益才可信。

### 模拟评测当天投题

```bash
./serve_local.sh                                   # 终端 1：在本机启动投题接口
./submit_client.py --tag contract --limit 3        # 终端 2：模拟赛事方投题
./submit_client.py --tag soak --samples 5          # 长时间连续投题，检查服务是否稳定
```

两种测试的目的不同：日常跑分检查「方案做得好不好」，模拟投题检查「服务能不能按
`docs/API_CONTRACT.md` 的约定正常工作」，包括令牌验证、`track` 字段、原样返回
`task_id`、在 `deadline_s`（单题时间上限）内返回、连续请求不出错。这里在客户端测得
的耗时，和赛事方计分用的墙钟时间（从发出请求到收到响应的实际时间）是同一个算法。

提交前至少完整跑一次模拟投题。评测当天也可以用 `--url` 指向 rc-tunnel（Radeon Cloud
平台把本地端口暴露到公网的工具）分配的公网地址，做最后一次检查。

### 测试结束后

```bash
./tunnel.sh down
./remote_vllm.sh stop       # 停止远端 vLLM，释放 GPU
```

---

## 跑分之后要做的事

1. `experiments/<运行编号>.md` 已经自动生成，补写「改动与假设」「结论」两节
2. 值得分析的失败题目，把原因写进 `failures/`，并附上 `runs/` 中对应 trace 的路径
3. 阶段性结论整理进 `../REPORT.md` 第 6、7 节
