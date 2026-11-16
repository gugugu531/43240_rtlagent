// 在方案仓库根目录编译：typst compile report/main.typ report/report.pdf
// PDF 为生成文件，请修改 Typst 源稿后重新编译。
#set document(title: "设计报告")
#set page(paper: "a4", margin: (x: 25mm, y: 25mm), numbering: "1", number-align: center)
#set text(font: "Noto Serif CJK SC", size: 12pt, lang: "zh")
#set par(justify: true, first-line-indent: (amount: 2em, all: true), leading: 0.5em, spacing: 0.65em)
#set heading(numbering: "1.1")
#show figure.caption: set block(sticky: true)
#show heading: set text(font: "Noto Sans CJK SC", weight: "bold")
#show heading.where(level: 1): set text(size: 16pt)
#show heading.where(level: 2): set text(size: 14pt)
#align(center, text(size: 20pt, font: "Noto Sans CJK SC", weight: "bold")[设计报告])
#v(5mm)
= 方案概述
#include "sections/01-01-objectives.typ"
#include "sections/02-architecture.typ"
#include "sections/02-01-design-rationale.typ"
#include "sections/03-01-selected-model.typ"
#include "sections/03-02-model-comparison.typ"
#include "sections/03-03-finetuning.typ"
#include "sections/03-04-inference-stack.typ"
#include "sections/04-01-control-flow.typ"
#include "sections/04-02-planning-and-generation.typ"
#include "sections/04-03-structure-and-behavior.typ"
#include "sections/04-04-diagnosis-and-repair.typ"
#include "sections/04-05-budget-and-delivery.typ"
#include "sections/05-01-skill-inventory.typ"
#include "sections/05-02-skill-development.typ"
#include "sections/05-03-skill-validation.typ"
#include "sections/06-01-test-environment.typ"
#include "sections/06-02-graded-results.typ"
#include "sections/06-03-single-attempt-success.typ"
#include "sections/06-04-time-and-cost.typ"
#include "sections/06-05-results-analysis.typ"
#include "sections/07-01-build-preparation.typ"
#include "sections/07-02-inference-service.typ"
#include "sections/07-03-task-and-baseline.typ"
#include "sections/07-04-selftest-reproduction.typ"
#include "sections/07-05-environment-dependencies.typ"
#include "sections/08-01-failure-types.typ"
#include "sections/08-02-unsuccessful-improvements.typ"
#include "sections/08-03-scope-and-limits.typ"
#include "sections/09-innovations.typ"
#include "sections/10-01-achievement.typ"
#include "sections/10-02-future-work.typ"
#include "sections/11-references.typ"
#include "sections/12-01-collaboration-tools.typ"
#include "sections/12-02-design-origins.typ"
#include "sections/12-03-useful-suggestions.typ"
#include "sections/12-04-incorrect-suggestions.typ"
#include "sections/12-05-verification.typ"
#include "sections/13-01-implementation-index.typ"
#include "sections/13-02-experiment-records.typ"
#include "sections/13-03-key-records.typ"
