# L0 的报错编号分布（语法 / 详细描述失败）

| 项 | 内容 |
| --- | --- |
| 状态 | **已解决**（分析完成，结论可用于技能包选题）；**待办**：把结论落成技能包检查项 |
| 影响 | L0 是「可修」的那一类失败——修好它是低基线路线兑现增益的前提 |
| 最后更新 | 2026-09-28 |
| 统计范围 | 13 次全题集 baseline 运行（截至 2026-09-27）的判定日志与 `samples.csv` |
| 相关文档 | [`sim-mismatch.md`](sim-mismatch.md)（另一端的 L1 失配） |

## 问题

L0（`xvlog` / `xelab` 就失败的题）到底错在哪？它占各候选失败的 9%–34%，
而且是「有确定依据可修」的一类。回答「哪一类题的哪一种错最多」，才能决定技能包该覆盖什么。

## 已解决

### 方法：先分辨根因与级联

判定日志里 Vivado 的报错是一串编号，**必须先分辨根因与级联**：`VRFC 10-8530` 的原话是
「module 'TopModule' is ignored due to previous errors」，它只是前面错误的后果；
`XSIM 43-3322`（静态展开失败）同理。**统计里必须排除这两个**，否则它们会因为
「每个 L0 都有」而挤占榜首，把真正的根因盖住。

### 根因编号排行

| 编号 | Vivado 原话（摘自判定日志） | 出现在多少道题 | 最集中的题型 |
| --- | --- | ---: | --- |
| `VRFC 10-1280` | procedural assignment to a non-register out_always_comb is not permitted, left-hand side | 201 | 状态机、组合逻辑、时序其它 |
| `VRFC 10-4982` | syntax error near '…'（**通用语法错误，出错的记号每例不同**） | 104 | 组合逻辑、状态机、移位/LFSR |
| `VRFC 10-8549` | SystemVerilog 2017 keyword 'always_comb' used in incorrect context | 47 | 组合逻辑、状态机、时序其它 |
| `VRFC 10-2989` | 'current_state_next' is not declared | 31 | 状态机、移位/LFSR、波形推断 |
| `VRFC 10-1491` | unexpected EOF（**输出被截断的迹象**） | 22 | 波形推断、状态机、卡诺图/真值表 |
| `VRFC 10-9336` | redeclaration of ANSI port 'reset' is not allowed | 21 | 状态机、波形推断、组合逻辑 |
| `VRFC 10-3805` | use of undefined macro 'systemverilog' | 17 | 状态机、组合逻辑、时序其它 |
| `VRFC 10-3818` | variable 'global_history_reg' is driven by invalid combination of procedural drivers | 14 | 状态机、时序其它、波形推断 |
| `VRFC 10-2063` | Module \<full_adder\> not found while processing module instance \<FA0\> | 13 | 波形推断、组合逻辑、时序其它 |
| `VRFC 10-5010` | illegal character '2' in binary number 3'b012 | 13 | 组合逻辑、波形推断、状态机 |
| `VRFC 10-8928` | enum member 'READING_BYTE3' has a value that is outside the representable range of the enum | 10 | 状态机 |

### 按性质归类（能动手的部分）

| 性质 | 典型编号 | 说明 |
| --- | --- | --- |
| **声明不规范** | `VRFC 10-1280`、`10-2989`、`10-9336`、`10-3248` | 在 `always` 里给 `output`（默认是 wire）赋值却没写 `reg`/`logic`；标识符未声明；端口重复声明 |
| **语法与模式** | `VRFC 10-4982`、`10-8549`、`10-3805`、`10-1491` | 通用语法错误（位置每例不同，**不是一个根因**）；`always_comb` 用法；未定义宏；意外的文件结尾 |
| **结构错误** | `VRFC 10-2063`、`10-3186`、`10-9543`、`10-3823`、`10-3818` | 例化了没定义的子模块；对非数组类型取下标；位宽不匹配；同一变量多个驱动 |
| **用了不存在的系统函数** | `XSIM 43-4286`、`VRFC 10-10098` | 例如 `$popcount`——仿真器没有这个函数 |
| 级联（不计入根因） | `VRFC 10-8530`、`XSIM 43-3322` | 前面错误的后果，统计时已排除 |

### 一个值得记住的例子

`Qwen3.6-35B-A3B`（AWQ-4bit）在 `Prob026_alwaysblock1` 上生成的代码：

```verilog
module TopModule (input a, input b, output out_assign, output out_alwaysblock);
    assign out_assign = a & b;
    always @(*) begin
        out_alwaysblock = a & b;   // ← 这里
    end
endmodule
```

**逻辑完全正确**，但 `output out_alwaysblock` 默认是 wire，在 `always` 里赋值需要写成
`output reg out_alwaysblock`，于是 `VRFC 10-1280` → `VRFC 10-8530` → 判 L0。

**这说明相当一部分 L0 不是能力问题，而是声明规范的机械失误**：写对了逻辑，却因为一行声明
丢掉整道题。这类错误可枚举、可检查、可以在生成后一次性拦掉。

## 未解决

### 待办：把结论落成技能包检查项

按上面的频次排序，技能包优先覆盖：

1. `always` 里赋值的输出必须声明 `reg`/`logic`（最高频，201 道题）；
2. 所有中间信号先声明，不要依赖隐式 wire；
3. 不要用不存在的系统函数（`$popcount` 等）；
4. 不要依赖只在某些工具里支持的写法（`always_comb` 的上下文限制、未定义宏）；
5. 输出长度要留余量——`VRFC 10-1491`（意外文件结尾）是**截断**的直接证据，与 `max_tokens`
   预算和思考开关节有关。

### 限制因素

- 这些编号是**报错分类**，不是「怎么改」；落地成检查项还需要把每类错误对应到一条可执行的
  规则（例如「检查 `always` 块里被赋值的信号是否都声明了 `reg`/`logic`」）。
- `VRFC 10-4982` 是通用语法错误，无法靠单个规则拦住，只能靠「生成后先自检编译」。

## 证据

- 统计口径与脚本：`dev/tools/analysis/` 下的分析工具读取各运行的 `samples.csv` 的 `error_ids` 列
- 判定日志原话：`../runs/<运行编号>/baseline/<题目>/s1/judge.log`
- 上文例子的原始文件：`../runs/20260925-194130-screen-A1-qwen3.6-35b-a3b-awq/baseline/Prob026_alwaysblock1/s0/solution.v`
