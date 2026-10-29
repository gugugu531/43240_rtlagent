# 第45批：修复mixed-sign并继续扩展候选方法

完成更新：本批已结束，16次真实生成与独立审计通过；本页保留运行前安排，最终处置及错误说明以[完成报告](2026-10-29-rag-batch45-results.md)为准。

2026-10-29。上一批的记录器、已有事实、跨卡NBA及关键词问题已修复并有复测；mixed-sign仍有真实交付退步，本批不宣称它已经修好。

新增四张修订卡：比较结果符号、同进程NBA优先级、分块进位链、批次末样本。前三者中NBA优先级只做有失败代码的机械及修复筛选，不凭题面主题授权。另三类新增题面候选谓词仍shadow，实际谓词总数为15。

mixed-sign新版本使用SystemVerilog `$bits` 从权威端口获得宽度，依次完成原宽signed解释、目标宽扩展、unsigned offset扩展、signed解释和加法；示例不再列出复制拼接或手数符号位的替代方案。机制仍需模型落实，机械通过不代表模型交付已解决。两组配对分别为上批原题／原seed回归及七位源的不同上下文。

packer在上一批真实配对和拒绝检查基础上进入**显式首次生成试验**。其injection_stages只允许pre_generation，检索和最终装配都核对阶段。默认配置仍shadow；反馈修复不能借此权限注入。追加两个独立位宽上下文，通过真实generate节点、dense检索、实际准入和预算装配。

| 主机 | 任务 | 真实调用上限 |
| --- | --- | ---: |
| 33376 | 比较、分块进位、mixed原题、mixed不同位宽 | 8 |
| 33589 | NBA优先级、批次末样本、packer四位、packer五位 | 8 |

总16次，同题同seed、thinking开启、temperature=0、top_p=1、max_tokens=16384、timeout800秒，无自动重试。单卡错误隔离，两臂同一检查器。原题回归单列，不能把重复seed或同家族不同位宽称为独立泛化。

本地8夹具24变体通过真实Vivado；21条新谓词检查和10条packer装配检查通过，134项回归通过。检查还修复了non-overlapping被误匹配为overlapping、out_valid标识符不被识别、first-low/second-high同句被误当first-high三类词法边界问题。初始失败记录保留。

云端根目录为 `/root/rtl-rag-cohort45-20261029-r1`，冻结包和实际源文件保存在 `dev/optimization-v45/`。33589仅启动本批自有CPU embedding端口18045，队列结束后关闭；既有8010服务复用。

启动修正：r1在健康检查处缺少JSON导入，两机均为零生成基础设施失败，原件已回传。以独立r2包修正导入，并在云端实际执行health检查后启动；当前活动根为 `/root/rtl-rag-cohort45-20261029-r2`。修正包、收据、状态和回传工具位于 `dev/optimization-v46/`，本批上限仍为16次。修正前失败摘要见 `dev/optimization-v45/preparation-issues.json`；不将基础设施失败记为correct_empty。

完成后审计16个尝试、真实消息、thinking开关、用量、新稿、评分输入和哈希。packer必须证明card臂实际发送目标卡；没有发送属于路径验证失败，不能把它记为有卡成功。mixed若再退步保持hold；只有经过实际观察的修订才更新状态。
