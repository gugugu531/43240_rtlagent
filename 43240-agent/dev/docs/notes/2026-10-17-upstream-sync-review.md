# 同步改动提交前审查

- 类型：审查与验收记录
- 日期：2026-10-17
- 状态：审查与修复验证完成；用户授权提交、推送 GitHub、创建 PR，暂不合并
- 来源：[同步记录](2026-10-17-upstream-source-sync.md)，主办方 `f7a8bd465c2a820e006c7a00ecc7df468974635b`

## 范围

复查整个同步分支相对 origin/main 的差异：官方源文件、权限、题库映射、baseline 复制、
共享思考声明、900 秒默认时限、检查点重放、当前文档、打包边界与新增测试。
再次 fetch 当前 GitHub main 后没有新增提交；本分支尚无 PR。
本轮是在已授权的同步范围内修复审查问题，不对官方原始文件加自定义补丁。

## 发现与修复

1. **一致的部分思考配置误报冲突。** manifest 同时声明 enable_thinking 和其他标量模板参数时，
   YAML 只能提供 enable_thinking；即使值一致，原实现仍要求整个字典相等，导致初始化失败。
   现允许一致的子集，最终请求与计数都继承完整 manifest 声明，仍拒绝不一致或额外参数。
2. **未声明的另一种思考字段可绕过共享策略。** manifest 仅声明 reasoning_effort 时，
   原实现仍允许普通请求增加 chat_template_kwargs；反向情况也一样，导致方案与 baseline 不一致。
   现只要存在有效共享声明，就检查两类字段，不允许额外加入未声明思考设置。
   声明为空时保留既有实验选项的行为，正式部署仍应通过共享声明设置思考参数。
3. **执行权限未完整同步。** selftest/judge/l3_synth.tcl 内容与上游相同，但上游已改为可执行，
   上轮只比较内容而漏掉权限。本轮按上游权限同步，并核对全部文件的可执行位。
4. **当前文档有残留旧说明。** 修正 README 的 AGENT_DEADLINE_S=360 和无条件声称 baseline
   不传思考设置的文字，补充部分配置继承与额外参数拒绝规则。

前两类问题先用新增回归重现，再修复验证。检查点测试从直接检查哈希字段，改为在独立包中
实际创建检查点、验证正常重放、改变 manifest 后确认在模型调用前拒绝旧检查点。
另将开发汇总中的动态导入写法改为普通导入，未改变计分或实验策略。

## 验证

使用临时环境 /tmp/rtl-upstream-sync-venv；需要本机 HTTP 套接字的测试在沙箱网络限制外运行，
不调用外部模型，不启动付费云实例。

```bash
python -m unittest discover -s dev/tests -p 'test_*.py' -v
python dev/tools/submission.py --stage /tmp/43240_rtlagent-pr-review-20261017 \
  --task ../tasks/example/example_ex03_lfsr8 --output /tmp/rtl-upstream-pr-review-smoke
```

- 全量 350 项：341 项通过，9 项真实 Vivado 测试按默认设置跳过，无失败或错误。
- 共享配置专项覆盖一致子集、完整继承、冲突与额外参数拒绝、模板计数、实际检查点拒绝，
  以及独立包中 baseline/Agent 的 HTTP 请求和思考文本提取一致。
- 官方 60 文件内容与可执行位核对通过；18 个题库文件仅保留既有路径与题号映射，
  两个运行 baseline 与上游 example 原文件逐字节一致。
- 独立打包 mock smoke 通过：答案 177 字节，退出码 0，监督 completed，不含 dev 或题库。
- 相关 Shell 入口语法检查通过；本地凭据文件、运行产物、权重未加入提交清单。

复现日志 /tmp/rtl-upstream-review-reproduction.log；最终日志 /tmp/rtl-upstream-pr-review-tests.log；
打包结果 /tmp/rtl-upstream-pr-review-layout.json。上述临时产物不纳入 Git。

官方源文件只原样同步；既有实验 8192/300 等显式预算不改写，历史记录仍按当时版本阅读。
正式模型、镜像占位项和目标 GPU 实测仍待完成，本次审查不能代替赛事封存验收。
用户本轮授权推送到当前 GitHub 开发仓库并创建 PR，不授权合并 main。
