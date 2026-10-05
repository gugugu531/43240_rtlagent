# 第三阶段：远程测试尝试与真实工具验证

日期：2026-10-05。测试代码版本为 `342be4e`。
用户填入 remote.env 后授权尝试测试。本次不修改 Agent、服务脚本、remote.env 或官方文件。

## 结论

真实 Vivado 与 HTTP 协议层验证通过。本次首次远程尝试被基础 GPU 运算超时阻塞。
用户随后授权重新启动诊断，GPU 基础运算和真实模型测试已通过；上次阻塞具体根因仍未确认。
最新结果见[GPU 诊断与真实模型验证](2026-10-05-gpu-diagnosis-and-model-validation.md)。
下文保留首次尝试的实测范围与证据，不把 mock 结果视为真实模型结果。

两次实例都已销毁，最终 cloud.py status 返回 not_found。中转、临时 HTTP 服务与本机休眠保护已停止。
凭据未写入记录或提交。

## 改动与假设

验证第三阶段重构在真实工具与模型环境中是否能运行，重点检查单题执行、模型证据、受管理进程、
中断答案恢复与 HTTP deadline（墙钟时间上限）。计划使用三道示例题，不开展全量模型跑分。
先在开发判定链路验证参考实现；参考答案未传入 Agent。遇到云端基础环境异常后，转为分别验证
GPU 健康、真实 Vivado 集成和真实 HTTP 请求，不能把 mock 结果算作真实模型结果。

## 结果与证据

| 项目 | 结果 | 证据 |
| --- | --- | --- |
| 本机参考判定 | 三道示例题全部 L3，无环境失败 | [自动实验记录](../experiments/20261005-175329-stage3-reference-smoke.md)、[判定数据](../../runs/20261005-175329-stage3-reference-smoke/score.json) |
| Agent 与真实 Vivado 集成 | mock 生成一次，接口、lint、综合均 passed；选择恢复验证通过，无未回收进程 | [trace](../../runs/20261005-stage3-real-vivado-smoke/trace.jsonl) |
| 真实 Vivado 综合中发送 SIGTERM | shell 退出码 0，信号后 0.064 秒退出；保留 c001，受管理进程组终止，无未回收进程 | [观察数据](../../runs/20261005-stage3-real-vivado-cancel/cancel_observation.json) |
| 真实 HTTP 鉴权与单题请求 | 未授权 health 返回 401；授权 health 返回 rtl；solve 固定四个字段，task_id 原样返回 | [观察数据](../../runs/20261005-stage3-http-smoke/observations.json) |
| HTTP 单题，mock | 1 次调用、177 字节答案，实测请求墙钟约 0.148 秒 | 同上 |
| HTTP 1 秒 deadline | 约 0.092 秒返回空答案与 deadline 记录；默认 20 秒预留已超过预算，不启动模型，不扩大为 5 秒 | 同上 |
| 云端 GPU 与模型 | 两次实例基础运算超时；两种 vLLM 配置均未就绪 | [诊断登记](../../runs/20261005-stage3-cloud-diagnostics/observations.json) |
| 官方 baseline 原样 | 两个文件与 example 逐字节相同 | 本次执行 cmp |

HTTP 部分明确使用 mock，未访问真实模型。真实 Vivado 集成也使用 mock 模型，只证明工具、
日志和监督链路能工作。mock 的综合通过不证明符合示例题功能。
完整工具日志位于对应输出目录的 records/<run_id>/tool_logs/，进程输出位于 process_logs/。

## 云端阻塞定位

凭据有效；启动前平台没有运行实例。使用用户配置中的模板与 Qwen3-8B 路径。
首次实例设置 35 分钟看门狗，异常实例销毁后，新实例设 15 分钟看门狗并先做最小 GPU 检查。
第二次检查失败后立即销毁，没有在新实例重复下载权重或长时间加载模型。

实际环境：gfx1100、约 48 GiB 显存，vLLM 0.27.0+rocm724，PyTorch
2.10.0+rocm7.2.4.git3d3aa833，torch.version.hip 为 7.2.53211，驱动版本 6.16.13。
PyTorch 公布的构建架构包含 gfx1100，因此不能只按“不支持此架构”解释异常。

首次权重下载完成。初始配置是上下文 32768、GPU utilization 0.85、默认 V2 Model Runner。
服务等待 240 秒仍未就绪。随后仅通过远端临时环境改为 VLLM_USE_V2_MODEL_RUNNER=0、
--enforce-eager、--max-num-seqs 1、--reasoning-parser qwen3，再次等待 240 秒仍未就绪。
工程中的 serve/vllm.sh 和 remote.env 均保持原样；仅远端脚本副本按现有配置剥离
--disable-log-requests。不将此次临时服务参数当作正式提交声明。

最小检查直接调用 PyTorch，绕过 Agent 和 vLLM：

```python
x = torch.empty(1, device="cuda")
x.fill_(1)
torch.cuda.synchronize()
```

显存分配成功，fill_ 未在时限内返回：首次检查 35 秒超时，停止推理服务并禁用 SDMA 后仍在
30 秒超时；新实例也在 20 秒超时。faulthandler（Python 栈打印工具）的定时输出停在 fill_ 所在行。
这将阻塞范围缩小到基础 GPU 运行环境；具体是驱动、运行库还是资源状态问题尚未确认，不能据此
认定某一版本或物理 GPU 已损坏。

HSA_ENABLE_SDMA=0 是 AMD 文档提供的 DMA 开关，仅用于一次受控排查，没有改善当前结果。
出处：[AMD ROCm 环境变量](https://rocm.docs.amd.com/en/docs-7.2.2/reference/env-variables.html)。

## 后续条件

应先让最小 PyTorch GPU 运算正常完成，再加载模型开展真实单题与 Agent/baseline 对照。
当前无需修改 Agent 架构来处理此环境故障，也没有足够证据要求更换模型。
本次保留 97 项本地回归通过的结论；追加的真实工具和协议验证见上表，后续真实模型小规模验证已完成，见上文链接。
