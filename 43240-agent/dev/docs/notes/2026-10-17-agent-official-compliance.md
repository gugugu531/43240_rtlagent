# 自有实现官方要求核查

- 类型：审查、修复与验收记录
- 日期：2026-10-17
- 状态：代码修复与本地验证完成；更新 PR #41，暂不合并；正式封存待办未完成
- 来源：用户要求使用命令严格核查最新官方要求；官方 HEAD `f7a8bd465c2a820e006c7a00ecc7df468974635b`

## 核查范围与依据

在已有同步分支上继续核查自有实现，官方文件和两个 baseline 不加自定义修改。
通过 `git ls-remote` 核实官方实时 HEAD，并从官方 Git 对象逐文件读取内容，使用 `cmp`、
SHA-256 摘要和 Git 文件模式检查字节、执行权限与题库映射。
要求以 SCORING.md 的基线与共享思考段、docs/API_CONTRACT.md 的时间与启动约定、
docs/SUBMISSION.md 的封存内容为准。

本轮沿用已获认可的同步与修复范围，不更换架构或默认求解策略。
ModelService 和健康检查复用 `load_shared_generation(template_options=None)`；
JobManager 在持锁的查询、nonce 重投及出队阶段处理排队截止；
`check_submission_layout`、`stage_submission` 新增可选 `release=False` 声明检查。
验收覆盖原官方请求一致性、调用前拒绝不共享参数、真实进程回收、繁忙 Worker 的到期查询和独立包校验。

## 发现与修复

1. **空共享声明仍可绕过思考一致性。** 原实验 enable_thinking 以及显式请求可在 generation
   为空时仅改变普通生成/修复，baseline 保持服务默认。现无论声明是否为空，都拒绝未声明字段；
   一致的部分配置只用于核对，实际请求与本地计数始终继承完整官方加载结果。
   健康检查复用这一校验，冲突配置不报告就绪。
2. **计数器不接受官方允许的其他标量模板参数。** 原实现只支持布尔 enable_thinking，
   其他合法字符串、数字会导致严格上下文模式停止。现支持官方允许的布尔、数字和字符串，
   保持本地受限模板与离线编码；嵌套对象仍报告未知，不伪造精确值。
3. **排队任务可能迟迟不返回 done。** 原实现只在 Worker 出队时检查截止；前一任务仍运行时，
   到期任务的查询一直 queued。现查询或 nonce 重投即可结束已到期排队任务，返回空答案及
   queue_deadline 记录；Worker 后续跳过它，两种模式一致。HTTP 时限范围统一为 1 至 900 秒。
4. **独立包漏查官方基线与执行权限。** 原工具只在相邻 example 存在时比较 baseline，
   独立包中修改 baseline 也可通过。现固定核对该官方版本的两个 SHA-256，独立包同样执行；
   四个 Shell 入口缺少执行权限时也拒绝。官方升级后须重新核对并更新开发工具中的固定摘要。
5. **结构检查不能反映封存声明未完成。** 新增可选 `--release`，核对固定模型 revision、
   MODEL.md 来源和版本一致性、显存声明、服务版本和 Dockerfile 镜像占位项；失败不暂存。
   默认模式仍可验证开发包。Docker 默认临时目录改为官方建议的本地盘 /var/tmp，
   本机脚本默认不改。所有当前指南同步更新，历史记录正文保留。

前四类问题先由四项回归实际重现失败，再修复；新增健康检查使用真实 YAML 配置校验路径，
排队测试在前一任务仍阻塞时查询两种模式，且验证 Worker 不再执行过期任务。
本次收紧替代上一份[审查记录](2026-10-17-upstream-sync-review.md)中保留空声明实验选项的决定。

## 验证与复现

在 43240-agent/ 下使用临时环境 /tmp/rtl-upstream-sync-venv，需本机 HTTP 的测试在沙箱网络限制外执行；
没有调用外部模型，也没有启动付费云资源。

```bash
git ls-remote https://gitee.com/Vickyiii/rtlagent2026.git HEAD
python -m unittest discover -s dev/tests -p 'test_*.py' -v
python dev/tools/submission.py --stage /tmp/43240-agent-compliance-20261017 \
  --task ../tasks/example/example_ex03_lfsr8 --output /tmp/43240-agent-compliance-smoke-20261017
python dev/tools/submission.py --release
bash -n run.sh run_baseline.sh serve/start.sh serve/vllm.sh
git diff --check
```

- 全量 355 项：346 项通过，9 项真实 Vivado 测试按默认设置跳过，无失败或错误。
- 全量包含独立包中 baseline/Agent 真实本机 HTTP 请求和思考段提取一致，输出 16384、
  请求上限 840；共享声明为空及非空均有覆盖。
- 基线超时测试验证进程后代回收、保留已有答案、下一任务继续；Supervisor 回归覆盖阻塞模型调用。
- 独立包 84 个文件，不含 dev、tasks 或题库文件；mock smoke 退出码 0、答案 177 字节、监督 completed。
- 官方 60 文件和两个运行 baseline 内容与执行权限一致；3 个 task.json 保留既有题号映射。
- `--release` 按预期退出 2，指出固定 revision、实测显存、服务版本、官方镜像四项未完成。

原始日志与临时结果：/tmp/rtl-agent-compliance-tests-20261017.log、
/tmp/rtl-agent-compliance-layout-20261017.json、/tmp/rtl-agent-compliance-release-20261017.json。
独立包与清单位于上列暂存目录及其相邻的 manifest 文件；不纳入 Git。

## 仍需完成的部署验收

正式模型 revision、官方镜像和目标 GPU 测量需要实际选型与部署，不能为了通过检查填写假值。
声明检查不证明公开 URL 可访问、显存测量真实、辅助模型与总开销合规或镜像确为官方版本。
本轮没有进行目标 GPU/Vivado 全链路验收，因此不声称已经符合全部封存条件。
用户已授权提交、推送当前 GitHub 仓库并更新 PR #41，暂不合并 main。
