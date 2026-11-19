# 2026-11-03 排版报告（历史版本）

当前三角色的设计、模型与验收结果见方案根目录的设计报告。角色输入、复核条件和提交规则见工作流指南。[当前设计报告](../REPORT.md) · [三角色工作流指南](../docs/guided-verify.md)

本目录保留迁自匿名方案的历史材料，包括 2026-11-03 生成的 18 页 PDF 及其 Typst 源稿。正文按章节保存在 `sections/`，图示及 Graphviz 源文件保存在 `figures/`。[历史 PDF](report.pdf) · [Typst 主文件](main.typ)

在方案仓库根目录编译，需要 Typst（原 PDF 由 0.15.1 生成）以及 Noto Serif CJK SC、Noto Sans CJK SC 字体：

```bash
typst compile report/main.typ report/report.pdf
```

修改图示时先安装 Graphviz 并重新生成 SVG：

```bash
dot -Tsvg report/figures/architecture.dot -o report/figures/architecture.svg
dot -Tsvg report/figures/control-flow.dot -o report/figures/control-flow.svg
```

PDF 和 SVG 为生成文件，请勿直接修改。附录提及的 `dev/report-evidence/` 是本机审阅资料，不随 Git 提交或方案打包；阅读、编译本报告不依赖该目录。报告中的历史实验不代表迁移时重新完成了模型或 Vivado 验证。
