# remote/ — 用远端服务器测试

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

> **注意：** 比赛并没有规定必须使用 vLLM，推理后端由队伍自己选择。现有的
> `remote_vllm.sh` 暂时默认使用 vLLM，换用其他后端时需要修改。依据和修改计划见
> `../decisions/0001-inference-backend.md`。

远端的 vLLM 只监听本机地址 `127.0.0.1`，也不设置 API key。原因是 `baseline.py`
发请求时不带身份验证用的 `Authorization` 请求头。用 SSH 隧道，既能让基线脚本连上，
又不会把推理服务暴露到公网。

## 首次配置

```bash
cd 43240-agent/dev/remote     # 以下命令都在本目录下运行
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

## 启动远端推理服务

```bash
./remote_vllm.sh start      # 把 serve/vllm.sh 复制到远端，并在后台启动
./tunnel.sh up              # 建立 SSH 隧道
./remote_vllm.sh wait       # 等待模型加载完成
./tunnel.sh status          # 查看隧道是否正常、当前模型名
```

远端运行的就是提交方案里的那份 `serve/vllm.sh`，所以测试时的服务配置和
`MODEL.md` 中声明的一致。

## 日常跑分

```bash
./remote_selftest.sh --tag smoke --tasks ../../../tasks --samples 1
./remote_selftest.sh --tag veval-s5 --samples 5
```

除 `--tag` 外，其余参数原样传给 `selftest/run_selftest.sh`，默认题目目录是仓库根目录
的 `tasks/`。需要并行跑分、逐个样本的失败原因时，改用
`../eval/remote_eval.sh`（见 [`../eval/README.md`](../eval/README.md)）。方案（agent）和基线（baseline）在同一次运行中使用同一个推理服务，算出
的增益才可信。

## 模拟评测当天投题

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

## 测试结束后

```bash
./tunnel.sh down
./remote_vllm.sh stop       # 停止远端 vLLM，释放 GPU
```

---

## 脚本一览

| 脚本 | 作用 |
| --- | --- |
| `remote.env.example` | 配置模板，复制为 `remote.env` 后填写（`remote.env` 不提交到 git） |
| `remote_vllm.sh` | 在远端启动、查看、停止 vLLM：`start` / `wait` / `status` / `logs` / `stop` |
| `tunnel.sh` | 建立、查看、关闭 SSH 隧道：`up` / `status` / `down` |
| `remote_selftest.sh` | 日常跑分：调用 `selftest/run_selftest.sh`，结果写入 `../runs/`，并生成 `../experiments/` 中的记录 |
| `serve_local.sh` | 模拟投题的服务端：在本机启动 `serve/serve_api.py`，推理请求经隧道发往远端 |
| `submit_client.py` | 模拟投题的客户端：按接口约定逐题投题、计时、判定、打分 |
| `record.py` | 被上面两个跑分脚本调用，记录运行信息、生成实验记录 |
| `_common.sh` | 各 Shell 脚本共用的配置读取和函数，不直接运行 |
