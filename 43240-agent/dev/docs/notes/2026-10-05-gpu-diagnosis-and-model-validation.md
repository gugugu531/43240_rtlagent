# GPU 诊断与真实模型验证

日期：2026-10-05。代码版本：`342be4e`。用户授权启动云服务器诊断，正常后继续测试。
本轮没有修改 Agent、服务脚本、remote.env、baseline 或官方文件。只增加实验产物和文档。

## 结论（最新）

本轮 GPU 基础运算、Qwen3-8B 加载和推理均正常。相同 PyTorch、HIP 和驱动版本下未复现
上一轮的 `fill_` 阻塞，不能把问题归因于这些版本必然不支持 gfx1100。
上次故障的具体根因仍未确认；缺少上次物理设备标识、宿主机日志与底层调用栈，无法用
本次恢复证明当时是设备状态异常、宿主机问题或运行库问题。

默认 Workflow 与 baseline 已完成三题对照；指定单题的 repair_loop、真实 HTTP 请求和
真实推理期间的取消也已验证。测试范围很小，不能据此证明全题集收益或决赛硬件适配。
实例、隧道、本地 HTTP 服务和休眠阻止进程已关闭，平台最终状态为 `not_found`。

## GPU 诊断

原始证据：[诊断目录](../../runs/20261005-gpu-root-diagnosis/)、
[诊断日志](../../runs/20261005-gpu-root-diagnosis/diagnosis.log)、
[环境登记](../../runs/20261005-gpu-root-diagnosis/environment.json)。

| 项 | 本次实测 |
| --- | --- |
| 模板 | 4477 |
| GPU 架构、显存 | gfx1100，51,522,830,336 字节 |
| GPU 标识 | Unique ID `0x8c850b1d78ee91fe`，PCI 地址 `0000:83:00.0` |
| 容器设备 | `/dev/kfd`、`/dev/dri/card5`、`/dev/dri/renderD132` |
| Linux 内核 | `6.8.0-79-generic` |
| amdgpu 模块版本 | `6.16.13`，不等同于 Linux 内核版本 |
| PyTorch / HIP | `2.10.0+rocm7.2.4.git3d3aa833` / `7.2.53211` |
| vLLM | `0.27.0+rocm724` |
| 实际加载的 HIP / HSA 库 | `/opt/rocm-7.2.4/lib/libamdhip64.so.7.2.70204`、`libhsa-runtime64.so.1.18.70204` |
| 平台主进程 GPU 环境 | `LD_LIBRARY_PATH=/opt/rocm/lib`，`HIP_VISIBLE_DEVICES` 为空 |
| SSH GPU 环境 | 未设置上述 GPU 环境变量 |

SSH 默认环境下 `torch.empty(1)`、`fill_(1)`、同步和读取结果全部成功。
追加 100 次 GPU 创建数组、乘加、同步及结果校验，耗时约 0.175 秒并全部通过。
默认环境已经成功，因此没有继续执行环境继承及 SDMA 的失败对照。
这证明本次不继承平台的两个 GPU 环境变量也能工作，不证明上次实例环境相同。

上一轮两次实例与本轮均使用同一连接地址，但上一轮没有 GPU Unique ID，无法判断是否
同一物理设备。销毁容器也不等于重启宿主机或重置 GPU。

文档核查另有一条反证：[ROCm/TheRock #6696](https://github.com/ROCm/TheRock/issues/6696)
记录了相同 PyTorch 构建及 HIP 版本在 gfx1100 GPU 上成功完成最小运算。该 issue 的
故障针对另一份 nightly 构建的第二张 GPU，不能当作本次故障的已确认原因。
[AMD 容器说明](https://rocm.docs.amd.com/projects/install-on-linux/en/latest/how-to/docker.html)
说明 GPU 访问取决于宿主机驱动及设备映射；本轮映射可用，不代表上轮映射和状态已经核实。

## 服务配置与对照口径

模型为 Qwen/Qwen3-8B，配置文件下载记录的上游 commit 为
`b968826d9c46dd6066d109eabc6255188de91218`；本轮没有逐分片计算权重哈希。
上下文 32768，GPU utilization 0.85，BF16，无量化，默认 V2 Model Runner、编译及 CUDA Graph。
仅远端副本按现有配置剥离 `--disable-log-requests`，并使用 `--reasoning-parser qwen3`。
Agent 与 baseline 在每组对照中连接同一模型服务。

第一组保持默认思考。第二组只在远端临时启动参数加入
`--default-chat-template-kwargs '{"enable_thinking":false}'`，随后 repair_loop 和 HTTP
也使用关闭思考的服务。没有更改仓库配置或把临时参数登记为最终提交方案。

## 真实模型与 Vivado 结果

| 测试 | 题目与结果 | 原始记录 |
| --- | --- | --- |
| single_generate，开启思考 | ex01、ex03 双方 L3；ex02 双方 L0 | [第一组](../../runs/20261005-183124-stage3-real-default-smoke/) |
| single_generate，关闭思考 | ex01、ex03 双方 L3；ex02 双方 L1 | [第二组](../../runs/20261005-184027-stage3-real-nothink-smoke/) |
| repair_loop，只跑指定单题 | ex03_lfsr8 为 L3 | [单题记录](../../runs/20261005-184136-stage3-real-repair-single/) |

L3 表示仿真正确且可综合；L1 表示仿真结果不一致。上述判定均未报告工具环境错误。
题目分别为 ex01_popcount8、ex02_detect_1101、ex03_lfsr8。开发判定器可以读取参考答案，
Agent 输入与运行组件没有读取参考答案。

开启思考时，ex02 的 Agent 请求在 180 秒上限处超时，记录 `model_timeout`；baseline
约 187.4 秒后返回 `finish=length`，输出 token 为 8192，代码正文为空。
这是模型输出和预算问题，与本轮 GPU 健康不同。Agent 的服务上限默认 180 秒，官方
baseline 固定 300 秒；默认策略只是近似 baseline，两者不是完全相同的超时配置。
关闭思考后，这一题有了完整代码，但双方仍为 L1，不能把关闭思考描述为已解决功能错误。

单题使用临时 taskset 文件，只列 ex03_lfsr8，开发入口选出一题；repair_loop 一次模型调用后，
真实接口、lint、synth 检查均通过。内部检查不验证功能，L3 来自外部官方判定器。
两个完整逻辑工具日志为 1,304 与 13,176 字节，工作目录删除后仍保留。
此单题没有触发第二轮修复或检查复用，因此不能称为真实模型的修复成功率或消融实验。

详细记录核验保存为各组运行目录的 `record-verification.json`。成功响应保存原始 HTTP
文本、完整 JSON、代码正文和提取结果；第一组 ex01/ex03 的思考正文分别为 14,020 与
14,323 字符。超时调用没有收到完整响应，没有伪造原始回复或 token 用量。
各次监督记录均无未回收进程，成功答案的选择检查点校验通过。

## HTTP 与取消

[HTTP 记录](../../runs/20261005-stage3-real-http/observations.json)：

- 真实模型正常请求返回 HTTP 200，task_id 原样返回，字段符合协议，耗时约 2.273 秒；
  单次模型调用、205 字符答案。详细证据保存到独立记录目录，请求临时目录删除后仍在。
- 22 秒预算的请求有一次模型开始记录，约 1.841 秒返回 HTTP 200 和空答案。
  20 秒清理预留使求解窗口较短，Supervisor 记录 `deadline`、Worker 为 -15，无未回收进程。
  这不表示请求拥有完整 22 秒的推理时间，也不保证每种负载下完全相同的返回耗时。

[真实推理期间取消](../../runs/20261005-stage3-confirmed-model-cancel/observations.json)：
启动前服务端活跃请求为零；模型调用开始后，确认服务端活跃请求为一，再向 run.sh 发送 TERM。
约 0.064 秒退出，shell 返回 0，Worker 为 -15，停止原因 `sigterm`，无未回收进程。
只确认本地退出和资源回收，`backend_inference_cancelled=unknown`，没有把共享服务端取消
推理算作已验证能力。

## 后续边界

本轮完成了第三阶段的真实模型小规模验证，不改变下一阶段实施前交用户审阅计划的要求。
YAML 配置、统一实验入口与指标、历史重放尚未实现。进一步扩大题集前，应明确思考模式和
请求预算口径；目前不以三题结果评价默认 Workflow 的全题集能力或收益。

若 GPU 阻塞再次出现，应在销毁前保存相同的设备标识、库路径、HIP 调试日志与底层调用栈，
并对照宿主机错误日志或不同物理 GPU。当前没有足够证据要求修改 Agent 架构或更换模型。
