# 上游投题接口与启动要求对齐

- 类型：实现与验收记录
- 状态：已获用户认可，已实施并完成本地验证
- 日期：2026-10-16
- 来源：[主办方仓库](https://gitee.com/Vickyiii/rtlagent2026)，提交 `9df176717fec16751d02f4fb5c67dbd40a22fc15`（2026-10-15 18:24，Asia/Shanghai）

## 范围与认可的方案

用户要求对照上游修改当前工作区并提交。经对比后，向用户提交了以下方案并得到认可：
保留现有求解流程与 baseline，在 HTTP 层增加串行队列、nonce 去重、状态查询和包含排队的时限；
补充 `serve/start.sh`、打包检查和说明；验证鉴权、超时清理与连续投题；只在独立分支本地提交。

HTTP 层使用 `JobManager.submit()`、`get()` 管理任务，后台 `_solve()` 仍调用文件式入口。
FastAPI lifespan 负责 Worker 的启动、退出和 Linux 孤儿进程接管；每题沿用 `ProcessExecutor`
的进程组监督。启动脚本复用上游常驻服务入口，并增加串行启动锁、失败清理和请求超时。

## 已实现

- `POST /v1/solve` 返回 202 与任务编号；`GET /v1/jobs/{job_id}` 查询 `queued/running/done`。
- 非空 nonce 重复投递返回原任务；空 nonce 每次新建。串行处理，排队时间计入单题时限。
- 任务错误结束为 `done`，保留可读答案和 trace；服务错误只记录类别，不输出异常中的敏感信息。
- Agent 与 baseline 均监督进程组，Linux 下接管并回收任务孤儿；服务退出停止当前任务与队列。
- 健康检查核对 Worker、模型列表和所配置的模型名称；mock 不查询模型服务。
- `serve/start.sh` 在服务已运行时复用，否则通过 `setsid` 启动并等待就绪；补充上游 EDA 临时目录清理。
- 默认按 30 GB 与实际卡容量计算显存比例，向下取整；显式 `GPU_UTIL` 保留覆盖能力。
  日志开关按安装版本的帮助信息选择，保留 `VLLM_EXTRA_ARGS`。
- Docker、manifest、MODEL.md、方案 README、服务说明与当前手册同步更新，打包要求包含启动脚本。

## 保留的边界

这次对齐是已认可的服务兼容修改，不是把整个上游仓库覆盖到本地。
根目录主办方文件、`docs/`、`selftest/`、`example/` 与两个 baseline 文件均保持不变。
上游 `baseline.py` 已新增 `strip_think()`；本地按受保护文件规则仍保留原提取逻辑，
默认 `single_generate` 继续与本地 baseline 对齐。使用 Qwen3 等推理模型仍需正确配置 reasoning parser。
本地只读 API 文档为旧快照，当前用法指向上游契约和 `serve/README.md`。

任务、结果与 nonce 映射保存在单个 HTTP 进程中，重启后清空；只能运行一个 uvicorn Worker，
不支持多 Worker 或热重载。未确定模型选型，未填写虚构的显存实测值，未修改 REPORT.md 的实测结论。

## 验收

使用已有依赖环境 `/tmp/rtl-async-service-venv/bin/python`。测试中的本机套接字需要在沙箱限制外运行；
不调用外部模型，不启动云端实例。

```bash
python -m unittest discover -s dev/tests -p 'test_*.py' -v
python dev/tools/submission.py --stage /tmp/rtl-upstream-submission-20261016 \
  --task ../tasks/example/example_ex03_lfsr8 --output /tmp/rtl-upstream-smoke-20261016
bash -n serve/start.sh serve/vllm.sh
```

- 全量：336 项，327 项通过，9 项真实 Vivado 测试按默认设置跳过；无失败或错误。
- 新增 HTTP 验证：立即响应、并发 nonce 去重、串行顺序、排队过期、异常后继续服务、鉴权和字段校验、
  模型列表匹配、3 次真实 mock 入口、baseline 超时后的答案保留与后代回收、服务关闭清理。
- 连续性：300 次投题和重复投递/查询，使用测试替身，不代表真实 GPU 长时间压测。
- 启动：测试替身验证重复执行、独立会话、服务启动失败、新旧 vLLM 参数、48 GB 卡对应 30 GB 比例 `0.6250`、
  显式比例覆盖、预算超出 32 GB 时拒绝启动。
- 独立打包与单题 smoke：`ok=true`，退出码 0，答案 177 字节，监督状态 completed；不含 dev 和题库。
- `git diff --check` 与受保护文件差异检查通过。

本地原始日志位于 `/tmp/rtl-upstream-tests-20261016.log`，打包检查输出位于
`/tmp/rtl-upstream-submission-check-20261016.json`；临时目录不保证长期保存，不纳入提交。
未构建官方 GPU 镜像，未在目标 GPU 测量真实显存与长时间推理，未运行本次无关的真实 Vivado 专项。
