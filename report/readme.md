# 设计报告

[阅读 PDF](report.pdf)，[查看 Typst 主文件](main.typ)。正文按章节保存在 `sections/`，图示及 Graphviz 源文件保存在 `figures/`。

本目录迁自匿名方案中的报告材料，保留原报告正文和 PDF。根目录 `REPORT.md` 是此前按赛事模板维护的 Markdown 报告，两份材料分别保留，不视为自动同步。

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
