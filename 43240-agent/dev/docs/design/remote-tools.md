# 远端管理工具

脚本位于 dev/tools/remote/，配置位于该目录的 remote.env。第五阶段仅迁移路径并将联合实验接入
统一 run.py，没有启动云端或改变推理服务默认参数。平台与环境说明来自下面注明的历史实测，
不代表本轮重新确认。最新 GPU 诊断见[验证记录](../notes/2026-10-05-gpu-diagnosis-and-model-validation.md)。

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
> `dev/docs/notes/0001-inference-backend.md`。

远端的 vLLM 只监听本机地址 `127.0.0.1`，也不设置 API key。原因是 `baseline.py`
发请求时不带身份验证用的 `Authorization` 请求头。用 SSH 隧道，既能让基线脚本连上，
又不会把推理服务暴露到公网。

## 首次配置

```bash
cd 43240-agent/dev/tools/remote     # 以下命令都在本目录下运行
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

`tunnel.sh up` 现在用两个 systemd 用户服务管理连接：底层 SSH/socat 转发监听
`LOCAL_VLLM_PORT + 1`，本地 HTTP gateway 监听 `LOCAL_VLLM_PORT`。服务退出后 3 秒自动
重启；relay 的每个连接仍新建 SSH 会话，网络恢复后新请求可以继续。需要本机有可用的
`systemctl --user`，relay 模式另需 socat。`tunnel.sh down` 停止两个服务及其子进程。

gateway 对连接断开、连接被拒绝等传输异常，最多在 270 秒内用原始请求字节重试；GET
健康检查最多等待 8 秒。上游 HTTP 错误直接返回。两组实验都通过同一个 gateway，采样
参数和回复正文不变。中断的 POST 重试可能让远端重复推理，因此每次传输重试记录在
gateway 的 journal 中，分析耗时时需一起查看；本题硬超时仍由 Supervisor 控制。

```bash
journalctl --user -u fpgachina-transport-18000.service -u fpgachina-model-gateway-18000.service
```

实验汇总现在排除已记录的模型失败样本，并保留原始 judge 文件；只有完整、双方有效且
覆盖相同的配对实验才给出 gain。接口连通不等于长时间稳定，正式运行仍需查看调用错误数。

### 本次 AutoDL 暂停后补跑（2026-10-13）

`autodl_resume_quick34.sh` 专用于恢复
`20261012-225403-autodl-qwen3-8b-a-fixed-quick34-460c1d2a` 取消的 5 题；
运行前核对源码 SHA256 和 10 个待补样本，使用
`dev/configs/quick34-remaining-20261013.yaml`，不会重跑已有 58 项。
历史补跑曾安装 90 分钟远端保护；2026-10-13 用户已取消今后整轮固定截止，当前启动脚本
默认不安装该保护，退出时仍停止 vLLM、连接与会话定时器。屏幕关闭可继续，但本机网络断开
或休眠仍会影响求解链路。该旧专用补跑脚本已完成使命，不应再次执行以重跑旧样本。
`autodl_watchdog.sh disarm` 现在先应用 `REMOTE_ACTIVATE`，解决非交互 SSH 中 Python
不在 PATH 的问题；本轮已实际验证保护器启动与撤销。

补跑完成后，在 `43240-agent/` 下运行：

```bash
python3 dev/tools/combine_runs.py <原运行目录> <补跑目录>
```

工具要求原运行 `cancelled`、补跑 `completed`，并核对有效配置、正式源码哈希、题目输入、
完整覆盖及重复样本；取消、工具失败或模型失败样本不参与合并。派生摘要写入补跑目录的
`combined/summary.json`，逐样本来源保存在 `combined/provenance.json`。
它不修改原始运行，也不是一次新的连续执行。完成后仍需用户在 AutoDL 网页关机；
脚本停止 vLLM 不会关闭平台实例。

### 当前整轮时限政策与诊断恢复

`autodl_generation_diagnostic.sh`、`autodl_quick34.sh` 和旧专用恢复入口共用
`autodl_session_limit.sh`：`AUTODL_SESSION_LIMIT_S` 默认 0，取消遗留本地提醒/截止 timer 和远端
watchdog，不再按 5 小时或 90 分钟自动暂停。只有用户另外明确要求，才设置正数启用限时。
每次模型请求、单题和判定的超时预算不变；完成、报错或手动停止仍关闭推理服务。
不启用独立远端时限后，若本机崩溃或断网导致清理无法到达远端，vLLM 可能留在云端，
恢复连接后应检查；AutoDL 实例持续计费，仍需在网页关机。

11 题诊断在第二组被旧 timer 中断时：

```bash
python3 dev/tools/generation_resume.py prepare <新会话目录> --previous <旧会话目录>
python3 dev/tools/generation_resume.py verify <新会话目录>
DIAGNOSTIC_VIVADO_SETTINGS=<实际settings64.sh路径> \
  bash dev/tools/remote/autodl_generation_diagnostic.sh <新会话目录> --resume
```

仅补取消的 SampleSpec，不重抽已完成的低分答案；复用统一 runner。新会话保存原始证据哈希、
剩余样本清单、网关审计和 `combined-sampled/` 派生汇总。原会话及结果不改写。

远端运行的就是提交方案里的那份 `serve/vllm.sh`，所以测试时的服务配置和
`MODEL.md` 中声明的一致。

## 使用 AMD Radeon Cloud 实例

GPU 服务器也可以用 AMD Radeon Cloud（比赛的云平台）按需启动的实例。实例**从启动到销毁
一直计费**，不管有没有在用，所以用 `cloud.py` 通过平台接口（Platform API）自动启动和
销毁，避免空跑。接口说明见
<https://amd-aim.github.io/radeon-cloud-docs/api/instances/>。

**一次性准备**（在控制台网页上完成）：

1. 在 Profile 页面设置 SSH 公钥
2. 新建一个模板：镜像选 `AMD-Stable-GH-Proxy`（自带 vLLM，并且能通过平台代理访问 HF 镜像
   和 ModelScope）；打开 SSH Access；不要挂载 Model Directory（挂载 Devzone 时启动会报
   `unsupported launch option`）。持久存储目前不可用，每次启动都要重新下载权重
3. 在 `remote.env` 中设置 `REMOTE_HOST=cloud`、`RC_API_BASE`、登录凭据、`RC_TEMPLATE_ID`，
   `REMOTE_MODEL` 写权重在实例中的路径

```bash
./cloud.py me           # 检查凭据是否有效、余额、是否设置了 SSH 公钥
./cloud.py templates    # 查看模板 id
```

**中国站点与文档不一致的地方**（2026-09-23 实测，文档只描述了 Global 站点）：

| 项 | 文档 | 中国站点实际情况 |
| --- | --- | --- |
| 平台接口地址 | `https://radeon-global.anruicloud.com` | `https://developer.amd.com.cn/radeon` |
| 登录凭据 | API key（`Authorization: Bearer rc-...`） | **不接受 API key**，只认浏览器登录状态，要把 Cookie 复制到 `RC_COOKIE`。API key 只能用于模型接口 |
| 启动实例 | 直接调用接口 | 可能要求先做邮箱验证（验证码加人机验证），脚本无法完成 |

平台要求验证时，`up` 会停下并提示。这时在控制台网页上启动实例，就绪后用 `--own`
让脚本接管：

```bash
./cloud.py up --own                                  # 接管：启动看门狗
./cloud.py session --own -- <命令>                   # 接管，命令结束后销毁
```

**实测可用的流程**（2026-09-24 多次使用）：

```bash
./cloud.py me                                   # 1. 确认 Cookie 有效
systemd-inhibit --what=sleep:idle --mode=block sleep 9000 &   # 2. 阻止本机休眠
./cloud.py up --max-minutes 130                 # 3. 启动实例，看门狗时限按计划时长设置

# 4. 实例上的准备：卸载坏掉的 flash_attn，下载权重（放到后台，看日志里的完成标记）
(. ./_common.sh && rssh ". /root/.platform_env; pip uninstall -y flash_attn; \
    setsid nohup hf download Qwen/Qwen3-8B --local-dir /workspace/models/Qwen3-8B \
    > /workspace/dl.log 2>&1 < /dev/null &")    # 放在子 shell 里：_common.sh 出错时会 exit

# 5. 启动 vLLM 和中转；换模型时在命令前设置 REMOTE_MODEL 和 REMOTE_EXTRA_ENV
REMOTE_MODEL=/workspace/models/Qwen3-8B \
REMOTE_EXTRA_ENV="VLLM_EXTRA_ARGS='--reasoning-parser qwen3'" ./remote_vllm.sh start
./tunnel.sh up
./tunnel.sh status                              # 显示「vLLM 响应正常」后再跑分

# 若云端镜像的 vLLM 不再接受提交脚本里的某个参数，服务会直接起不来。
# 2026-09-25 实测：vLLM 0.27.0 移除了 --disable-log-requests，报 unrecognized arguments。
# 在 remote.env 里写 REMOTE_STRIP_ARGS=--disable-log-requests，remote_vllm.sh 只会在
# **远端副本**上剥掉它，仓库里的 serve/vllm.sh 保持不变（改提交文件是另一个决定）。

# 5. 起显存采样，再跑分（指标采集见 dev/docs/design/historical-analysis.md「资源与速度指标」）
./vram_watch.sh start 2
LLM_BACKEND=openai LLM_BASE_URL=http://127.0.0.1:18000/v1 LLM_API_KEY=dummy \
LLM_MODEL=Qwen3-8B MODEL_NAME=Qwen3-8B python3 ../run.py \
    --config ../../configs/remote-smoke.yaml --tag cloud-check --modes baseline
./vram_watch.sh stop && ./vram_watch.sh report   # 停采样并汇总峰值显存

./tunnel.sh down && ./cloud.py down             # 7. 结束后立刻销毁
```

`cloud.py session -- <命令>` 会自动完成「启动 → 启动 vLLM → 建立连接 → 运行命令 → 销毁」，
但**目前不会做第 4 步**（卸载 `flash_attn`、下载权重），新实例上直接用会因为没有权重而
失败。在把第 4 步加进脚本之前，请按上面的流程手动操作。

其他命令：

```bash
./cloud.py status                   # 实例状态、看门狗剩余时间
./cloud.py down                     # 销毁
```

防止实例被遗忘的三道保护：

| 保护 | 说明 |
| --- | --- |
| `session` 结束时销毁 | 正常结束、出错、Ctrl-C、SIGTERM 都会销毁 |
| 看门狗 | `up` 会在本机后台启动一个独立进程，`RC_MAX_MINUTES`（默认 180 分钟）后无论实例是否在用都会销毁它。本脚本或终端被关掉也不影响；**本机关机、休眠、断网，或 Cookie 失效时不起作用** |
| 平台自带的空闲超时和最长运行时间 | 最后的保险，具体时长文档没有给出 |

**实例环境的实测情况**（2026-09-24，模板镜像 `AMD-Stable-GH-Proxy`）：

| 项 | 情况 | 脚本的处理 |
| --- | --- | --- |
| GPU | gfx1100（W7900），48 GB 显存。决赛是 32 GB 的 R9700，测试时把 `REMOTE_GPU_UTIL` 设为 0.62 左右，模拟 32 GB 上限 | — |
| 启动耗时 | 平台就绪约 1 分钟；之后 SSH 服务还要一段时间才能登录 | `up` 会跟踪启动任务，等平台报告的 SSH 阶段完成，并实际登录一次确认 |
| GPU 资源 | 可能不足，启动任务直接失败（`resource_capacity_insufficient`） | 报错退出，稍后重试 |
| 外网 | 只能通过平台的出口代理访问，HF 镜像和 ModelScope 下载速度波动大，实测 12 到 300 MB/s（16 GB 的模型 1 到 20 分钟），偶尔读取超时后自动续传，huggingface.co、github.com 不通。代理设置只在 JupyterLab 主进程的环境变量里，SSH 登录后没有 | `up` 把代理、HF 镜像、PyPI 镜像和 `/opt/venv` 写进实例的 `/root/.platform_env`，`remote_vllm.sh` 启动前自动加载 |
| Python | torch、vLLM 在 `/opt/venv`（vLLM 0.16.1）；镜像自带的 `flash_attn` 是坏的，vLLM 加载 Qwen3 时会报 `No module named 'flash_attn_2_cuda'`，需要先 `pip uninstall -y flash_attn` | 暂未自动处理 |
| SSH 端口转发 | 被禁用（`AllowTcpForwarding no`），`ssh -L` 隧道不通 | `tunnel.sh` 改用中转模式：本机 socat 监听端口，每个连接开一次普通 SSH 会话转发，每个请求多约 0.7 秒。**本机需要安装 socat** |
| 存储 | `/workspace` 约 98 GB，实例销毁后清空（持久存储暂不可用） | 每次启动重新下载权重 |

实例的 1 号进程是 JupyterLab，它不回收子进程，崩溃的 vLLM 会变成僵尸进程；`remote_vllm.sh`
判断进程是否存活时会排除僵尸进程。

注意事项：

- **每个账号同时只能有一个实例。** 已经有实例（例如在网页上手动启动的）时，`up` 和
  `session` 会直接使用它，但**不会自动销毁**它，也不会为它启动看门狗，除非加 `--own`；
  否则用完要手动 `./cloud.py down`
- **启动次数有限制**：大约每分钟 1 次、每 10 分钟 3 次、每小时 5 次。连续跑多组实验时，
  用一次 `up`，跑完再 `down`，不要每组实验都用 `session`
- 实例每次启动的 SSH 地址、端口和主机密钥都会变，`_common.sh` 从 `cloud.state` 读取
  地址，主机密钥单独存放在 `cloud_known_hosts` 中（两个文件都不提交）
- 看门狗时限要留够：到时会直接销毁，正在跑的实验会中断。时间不够时先
  `./cloud.py down` 再重新 `up`，或调大 `RC_MAX_MINUTES`
- API key 和 Cookie 只放在 `remote.env` 中，`cloud.py` 不会把它们打印出来
- **Cookie 大约 4 小时就会失效**（2026-09-24 实测：10:24 填入，14:33 失效）。失效后看门狗
  也无法销毁实例，所以每批实验应控制在 Cookie 有效期内，开始前先运行 `./cloud.py me` 确认。
- **要起实例的脚本不能先 `source _common.sh`**：没有实例时它检查 `cloud.state` 会直接退出，
  脚本会在 `cloud.py up` 之前就死掉（2026-09-27 踩过两次）。正确顺序是先 `./cloud.py up`，
  实例就绪后再 `. ./_common.sh`。同理，参数校验也放在 `source` 之前。
- **以命令前缀传的 `REMOTE_*` 变量会被 `remote.env` 覆盖**：`remote_vllm.sh` 会先
  `source _common.sh`，而它从 `remote.env` 读取这些值，所以
  `REMOTE_GPU_UTIL=0.80 ./remote_vllm.sh start` **不生效**，vLLM 拿到的仍是文件里的值。
  2026-09-27 因为这个连挂四次：文件里留着给 8B 模型的 `REMOTE_GPU_UTIL=0.62`，
  装不下 22.41 GiB 的 35B MoE，日志里 `Available KV cache memory: -0.47 GiB`。
  要临时改就直接传 `serve/vllm.sh` 读的那个变量，例如
  `REMOTE_EXTRA_ENV="GPU_UTIL=0.9"`。**排查这类问题先看日志里打印的实际值**
  （`--gpu-memory-utilization=…`），不要假设前缀生效。
  **失效后连 `./cloud.py status` 都查不了**（HTTP 401），也就无法确认实例是否还在计费，
  所以每批实验收工前必须先把实例销毁，不要留到下次处理（2026-09-25 两次会话都踩到这条）
- **本机休眠会中断评测**，看门狗也会随本机一起暂停，实例继续计费。长时间运行前用
  `systemd-inhibit --what=sleep:idle --mode=block sleep <秒数> &` 阻止休眠

## 日常跑分

```bash
./remote_selftest.sh --tag smoke --tasks ../../../../tasks --samples 1
./remote_selftest.sh --tag veval-s5 --samples 5
```

除 `--tag` 外，其余参数原样传给 `selftest/run_selftest.sh`，默认题目目录是仓库根目录
的 `tasks/`。需要并行跑分、逐个样本的失败原因时，改用
`./remote_eval.sh --config ../../configs/remote-smoke.yaml`（见 [`dev/docs/design/historical-analysis.md`](historical-analysis.md)）。方案（agent）和基线（baseline）在同一次运行中使用同一个推理服务，算出
的增益才可信。

方案 A 先用单题、单并发验证。这个配置会同时运行 `evidence_repair` 和 baseline；模型仍在远端，
Agent 的接口检查、lint、综合和 judge 仍在本机，因此本机必须先初始化 Vivado 环境和许可证：

```bash
./remote_eval.sh --config ../../configs/evidence-repair-remote.yaml
```

确认 trace 中出现 `evidence_repair`、Vivado 检查不是 `unavailable`，且两种模式都完成后，再增加
题目、样本数和并发。不要同时修改温度、上下文长度、候选数或提示策略，否则无法把分数变化归因
到结构化反馈和一次修复本身。

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

### 开发侧 thinking / 采样诊断

网关默认仍然原样转发请求。只有显式设置 `MODEL_GATEWAY_PROFILE` 和
`MODEL_GATEWAY_AUDIT_DIR` 后重新建立隧道，才会启用开发参数覆盖；原始请求与实际请求均留档，
两组的原始响应也保存，重试使用同一份实际请求。审计文件不记录 Authorization 请求头。
可用设置为 `think-on-greedy`、`think-off-greedy`、`think-on-sampled`；
不改题面、messages 或 8192 输出上限。参数覆盖后的采样组不是官方 baseline 固定参数成绩。

本轮固定五题、三组顺序、验收和资源保护见
[生成诊断计划](../notes/2026-10-13-generation-diagnostic-plan.md)。
后续 11 题两组运行见[执行记录](../notes/2026-10-13-diagnostic-eleven-execution.md)；
`generation_sweep.py prepare --config ... --profiles ...` 可冻结已声明的题集与有序设置，
生成报告在每组开始和完成时更新，明确区分已汇总与在途样本。
普通 `tunnel.sh up` 不会自动使用这些设置，也不会改变正式提交服务。

### 释放资源

```bash
./tunnel.sh down
./remote_vllm.sh stop       # 停止远端 vLLM，释放 GPU
```

用的是 AMD Radeon Cloud 实例时，最后再运行 `./cloud.py down` 销毁实例、停止计费
（用 `session` 时会自动完成）。

---

## 脚本一览

| 脚本 | 作用 |
| --- | --- |
| `cloud.py` | 通过平台接口启动、查看、销毁 AMD Radeon Cloud 实例：`me` / `templates` / `up` / `status` / `down` / `session` |
| `remote.env.example` | 配置模板，复制为 `remote.env` 后填写（`remote.env` 不提交到 git） |
| `remote_vllm.sh` | 在远端启动、查看、停止 vLLM：`start` / `wait` / `status` / `logs` / `stop` |
| `tunnel.sh` | 建立、查看、关闭 SSH 隧道：`up` / `status` / `down` |
| `vram_watch.sh` | 在实例上按秒采样显存：`start` / `stop` / `fetch` / `report`；模型筛选时配合跑分使用 |
| `weights.sh` | 采集权重的 sha256 与上游 commit，确认「两次跑分用的是不是同一份权重」；`joint_run.sh` 会自动调用它 |
| `joint_run.sh` | 一个模型的联合跑分一条命令跑完：换模型重启 vLLM → 等就绪 → 单路速度探测 → 起显存采样 → `run.py --config joint-quick.yaml` → 汇总显存 |
| `remote_selftest.sh` | 日常跑分：调用 `selftest/run_selftest.sh`，结果写入 `dev/runs/`，并生成 `dev/docs/experiments/` 中的记录 |
| `serve_local.sh` | 模拟投题的服务端：在本机启动 `serve/serve_api.py`，推理请求经隧道发往远端 |
| `submit_client.py` | 模拟投题的客户端：按接口约定逐题投题、计时、判定、打分 |
| `record.py` | 被上面两个跑分脚本调用，记录运行信息、生成实验记录 |
| `_common.sh` | 各 Shell 脚本共用的配置读取和函数，不直接运行 |
