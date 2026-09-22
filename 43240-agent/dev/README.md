# dev/ — 团队开发区（不提交）

`43240-agent/` 是提交包，本目录是它里面唯一**不随提交走**的部分：`.dockerignore`
已排除 `dev/`，打包提交目录时也要去掉它。

> **为什么必须隔离：** 这里会记录失败样本、VerilogEval 参考实现的片段。它们一旦进入
> 提交包，就可能被认定为「在技能包或智能体中预置答案」（SCORING 2.9/2.10），
> 整个 track 成绩作废。**凡是含参考答案的内容，只能放在 `dev/`。**

---

## 目录

| 路径 | 放什么 | 进版本库 |
| --- | --- | --- |
| `notes/` | 开发日志，`YYYY-MM-DD-<topic>.md` | 是 |
| `experiments/` | 每次跑分一条记录，脚本自动生成骨架，结论手填 | 是 |
| `failures/` | 失败样本归因，一类问题一个文件；`REPORT.md` 失败分析的素材 | 是 |
| `remote/` | 远端测试入口，见下 | 是（`remote.env` 除外） |
| `runs/` | 跑分产物：solution、trace、Vivado 日志、score.json | 否 |

文件名用英文（与提交包规则一致），正文中文。

## 官方文档导航

仓库根目录与 `../../example/` 是主办方原样文件，**只读，不改**。

| 需要查 | 看这里 |
| --- | --- |
| 赛题、提交结构、检查清单 | `../../README.md` |
| 评分公式、提交条件、作弊判定 | `../../SCORING.md` |
| `/v1/health`、`/v1/solve`、trace 格式、环境细节 | `../../docs/API_CONTRACT.md` |
| 常见问题 | `../../docs/FAQ.md` |
| 本地判定用法、VerilogEval 转换 | `../../selftest/README.md` |
| 报告模板 | `../../REPORT_TEMPLATE.md` |
| 示例方案原版（对照用） | `../../example/`，`diff -r ../../example ..` |

**不得改动的两个文件：** `baseline.py`、`run_baseline.sh`。用
`diff ../../example/baseline.py ../baseline.py` 核对。

---

## 远端测试

拓扑：**远端只跑 vLLM；智能体、投题接口、Vivado 判定都在本机。**

```
本机                                                              远端
B1  remote_selftest.sh ─► run_selftest.sh ─► run.sh ───────┐
                                         └─► run_baseline.sh ┤
B2  submit_client.py ─HTTP─► serve_local.sh:7860 ─► 同上 ────┤
                                                             ▼
                                   127.0.0.1:18000 ══SSH 隧道══► vLLM 127.0.0.1:8000
判定  judge.py / score.py（本机 Vivado）
```

远端 vLLM 只绑 `127.0.0.1`、不开 API key：`baseline.py` 不带鉴权头，隧道是唯一
既能让基线连上、又不把推理服务暴露到公网的办法。

### 一次性配置

```bash
cd 43240-agent/dev/remote
cp remote.env.example remote.env && vi remote.env    # 主机、模型路径、上下文
```

`run_selftest.sh` 会在内部 source `selftest/env.sh`，其中的 `LLM_*` 会覆盖掉远端配置
（`remote_selftest.sh` 会检测并拒绝运行）。把这几行改成「已设置则不覆盖」：

```bash
export LLM_BACKEND="${LLM_BACKEND:-openai}"
export LLM_BASE_URL="${LLM_BASE_URL:-https://api.deepseek.com}"
export LLM_API_KEY="${LLM_API_KEY:-sk-...}"
export LLM_MODEL="${LLM_MODEL:-deepseek-chat}"
```

单独跑 `run_selftest.sh` 仍走商用 API，经 `remote_selftest.sh` 则走远端，两者互不干扰。

### 起远端推理

```bash
./remote_vllm.sh start      # 同步 serve/vllm.sh 到远端并后台启动
./tunnel.sh up              # 建隧道
./remote_vllm.sh wait       # 等权重加载完
./tunnel.sh status          # 隧道 + 模型名
```

用的是提交包里的同一份 `serve/vllm.sh`，测到的服务配置就是 `MODEL.md` 声明的那份。

### B1：日常开发跑分

```bash
./remote_selftest.sh --tag smoke --tasks ../../../tasks --samples 1
./remote_selftest.sh --tag veval-s5 --samples 5
```

其余参数原样转给 `selftest/run_selftest.sh`，默认题集为仓库根的 `tasks/`。
方案与基线同一次运行、连同一个服务，增益可信。

### B2：模拟评测当天投题

```bash
./serve_local.sh                                   # 终端 1：本机投题接口
./submit_client.py --tag contract --limit 3        # 终端 2：模拟投题机
./submit_client.py --tag soak --samples 5          # 连续数百次请求的耐久测试
```

B1 验证的是「方案好不好」，B2 验证的是「接口按契约活着」：鉴权、`track`、task_id
回传、`deadline_s` 内返回、连续请求不崩。客户端测的墙钟就是计分用的那个口径。
提交前至少跑一次 B2。评测当天可用 `--url` 直接指向 rc-tunnel 的公网地址做最后检查。

### 收尾

```bash
./tunnel.sh down
./remote_vllm.sh stop       # 释放远端 GPU
```

---

## 跑分之后

1. `experiments/<run_id>.md` 已自动生成，补上「改动与假设」「结论」两节
2. 值得分析的失败样本，归因写进 `failures/`（附 `runs/` 里 trace 的路径）
3. 阶段性结论汇总进 `../REPORT.md` 第 6、7 节
