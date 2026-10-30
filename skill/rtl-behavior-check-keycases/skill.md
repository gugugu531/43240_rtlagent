---
name: rtl-behavior-check-keycases
description: Select a few high-value public test cases and express them as a flat input and expected-output table for a host-generated self-checking testbench.
phases: [generate, repair]
conflict_group: behavior-check-keycases
review_status: frozen_candidate_not_default
---

<!--
Copyright (C) 2026 Team 43240
SPDX-License-Identifier: MIT
Review status: candidate_not_model_validated
-->

# Agent Skill: RTL Behavior Check by Key Cases

## Purpose

Provide a small, deterministic set of public-interface test cases that a host can
turn into a self-checking testbench. The method focuses on a few cases that
discriminate the stated behavior. It does not attempt exhaustive verification and
it does not replace an independent functional or formal proof.

## When to Use

Use this skill when the public task defines observable behavior for a combinational
block or a single-clock sequential block, and a short table of input vectors and
expected outputs can distinguish a correct implementation from a likely wrong one.

## When Not to Use

Do not use this skill when:

- the interface is incomplete, has `inout` ports, or uses more than one clock;
- the required behavior depends on unspecified timing, protocols, or internal state
  that cannot be observed at public outputs;
- the task cannot be initialized from public reset, initial, or warm-up semantics;
- the only available evidence is the candidate implementation or a simulation log.
  The checker must be derived from the public task, not from observed behavior.

## Public Contract Precedence

The public task controls port names, directions, widths, signedness, reset timing,
clock edges, priority, latency, and valid conditions. This skill supplies a case
selection method only. Never invent behavior, and never use the candidate's output
as the expected value.

## Required Inputs

- The complete public task statement and the resolved public interface.
- The public reset, initial, or warm-up rule for each sequential case.
- The host execution contract, including effective case/line/event limits, initialization
  repetition, sampling times and expanded event indexing. Use these mechanics to compute
  table values; they do not override the public functional specification.
- The list of outputs the user or workflow permits checking. If the list is omitted,
  all public outputs are checked.

## Mandatory Workflow

### 1. Identify the observation boundary

List every public input and output. Identify the single clock input, if any, and the
sampling phase: after the active clock edge and after nonblocking assignments settle.
For a combinational block, sample after inputs have been stable for the host-defined
settle interval. Do not reference internal signals or hierarchical paths.

### 2. Select a few discriminating cases within the host limits

Prefer, in this order:

1. reset, initial, or warm-up to a known public state;
2. hold, disable, or no-op behavior;
3. one priority conflict or control overlap stated by the task;
4. one boundary, transition, or arithmetic edge that distinguishes common mistakes.

Do not enumerate the full input space. Do not add random stimulus. Do not add a case
that cannot state a public expected value.

### 3. Establish a known initial state for each sequential case

For a sequential case, the first line MUST be an `init` line. Drive the public reset
or initialization inputs exactly as the task specifies, including polarity and
synchronous versus asynchronous behavior. The host applies this initialization phase
for its configured number of clock edges. After the final init edge and settling, it
samples and compares the `init` line's checked outputs; only then does it execute the
`step` lines.

Never assume that an uninitialized register is zero. If the public task does not
establish a known state, omit the sequential case and leave that behavior unchecked.

### 4. Compute expected values from the public specification

For every checked output on every line, compute the value from the public rules using
old-state semantics at the clock edge. State the exact bit pattern in hexadecimal.
The host expands it to the declared width. A value that is unknown, X, or dependent
on an unspecified behavior must not be written as an expected value.

If the workflow permits checking only key outputs, use the same output set on every
line of one case. The host records every public output not in that set as unchecked;
unchecked outputs are never counted as passing.

### 5. Emit only the flat vector table

Do not write Verilog, SystemVerilog, tasks, delays, loops, classes, assertions,
hierarchical references, or a clock generator. The host owns the testbench, clock,
reset application interval, sampling, and comparison.

Use this exact line format:

```text
case reset
init reset=1 load=0 data=00 q=01
step reset=0 load=1 data=a5 q=a5
step reset=0 load=0 data=00 q=4a
case shift_boundary
init reset=0 load=1 data=80 q=80
step reset=0 load=0 data=00 q=01
```

Rules:

- `case <id>` starts one case; ids are unique and at most 63 characters.
- Each following line begins with `init` or `step`.
- Every non-clock public input MUST appear exactly once on every line of that case.
- Every key=value token that names a public output is an expected value.
- The output names on the first line define the checked outputs for that case; every
  later line of the case MUST use the same output names.
- The host records `checked_outputs` and `unchecked_outputs` for every case and
  line. If any public output is unchecked, the verdict is `partial_outputs`; it
  MUST NOT be reported as a full functional pass.
- Values are hexadecimal without a width prefix. The host validates width and rejects
  unknown or out-of-range values.
- Obey the effective case, table-line and expanded-event limits in the host execution
  contract. Defaults are four cases and eight lines per case. Repeated init events count
  toward the expanded-event limits even though they occupy one table line.
- A sequential case without an `init` first line is invalid.
- The `init` line's expected outputs are compared after the final init edge; they are
  not ignored.
- A combinational case may use `step` first; `init` is then treated as a settle step.
- No prose, Markdown, comments, or trailing explanation is allowed in the table.

### 6. Self-check the table before returning it

1. Every line drives every non-clock input.
2. Every line of a case checks the same output set.
3. The first sequential line is `init`, and its reset or initialization action is
   explicitly required by the public task.
4. Every expected value is a known hexadecimal pattern within the port width.
5. The cases are few, distinct, and target stated behavior rather than guessed cases.
6. No expected value was copied from the candidate RTL or a simulation result.

## Output Contract

Return only the table lines. The host parses them strictly and generates the
testbench. A malformed table must be rejected, not repaired by guessing.

## Verification Boundary

A matching table means only that the checked outputs matched the checked cases under
the host sampling plan. If any public output is unchecked, the result is a partial
behavior check and `functional_passed` MUST remain false or unknown. It does not
prove that all public behavior is correct. A
mismatch is evidence for adjudication, not proof that the RTL is wrong; the checker
may itself have an incorrect expected value. Report unchecked outputs and unknown
values separately.
