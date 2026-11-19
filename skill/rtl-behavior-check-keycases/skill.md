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
- The public output ports. Choose outputs whose expected values follow from the
  specification. The host records which ones the table actually checks.

## Mandatory Workflow

### 1. Identify the observation boundary

List every public input and output. Identify the top module's single clock input
and active edge, if any. Use post samples for values specified after the active
edge and nonblocking updates. Select a pre sample explicitly when the public
specification determines the output after input settling and before that edge.
For a combinational block, sample after inputs have been stable for the host-defined
settle interval. Do not reference internal signals or hierarchical paths.

### 2. Select a few discriminating cases within the host limits

Prefer, in this order:

1. reset, initial, or warm-up to a known public state;
2. hold, disable, or no-op behavior;
3. one priority conflict or control overlap stated by the task;
4. one boundary, transition, or arithmetic edge that distinguishes common mistakes.

For a small combinational truth table, cover every publicly defined input combination
when it fits within the host limits; split lines across cases if needed. Otherwise
select discriminating cases without claiming exhaustive coverage. Do not add random
stimulus or a case that cannot state a public expected value.

Respect the finite event budget. A few observed shifts do not establish a full state
cycle, and visiting an output does not establish priority or transition coverage.
Prefer cases that actually activate the property being checked. A waveform with
simultaneous input and clock changes does not override the host drive/edge/sample
order; omit ambiguous expectations instead of guessing a scheduling convention.

### 3. Establish a known initial state for each sequential case

For a sequential case, the first line MUST be an `init` line. Drive the public reset
or initialization inputs exactly as the task specifies, including polarity and
synchronous versus asynchronous behavior. The host applies this initialization phase
for its configured number of clock edges. Each `init` compares any explicit pre
expectation after its first input drive and before its first edge. It compares
unqualified outputs after its final edge and settling. The same timing applies to
a later `init` line.

Never assume that an uninitialized register is zero. If the public task does not
establish a known state, omit the sequential case and leave that behavior unchecked.

### 4. Compute expected values from the public specification

For every selected output and phase, compute the value from the public rules.
Consider the previous state, the current inputs, and whether the active edge has
occurred. State the exact bit pattern in hexadecimal.
The host expands it to the declared width. A value that is unknown, X, or dependent
on an unspecified behavior must not be written as an expected value.

For truth tables and Karnaugh maps, first resolve the public variable/bit order,
row and column axis labels, and the stated Gray-code ordering. Map each selected cell
to named input bits before converting the stimulus to hexadecimal; do not interchange
row and column variables or infer a formula from planning hints. A don't-care cell
permits multiple implementation results: do not force it to zero or one. Omit that
expected output (and, if no known output remains, that line), keeping each case's
checked output set consistent. Do not turn unknown output bits into known values.

If the workflow permits checking only key outputs, use the same output set on every
line of one case. The host records every public output not in that set as unchecked;
unchecked outputs are never counted as passing.

### 5. Emit an explained vector table

Do not write Verilog, SystemVerilog, tasks, delays, loops, classes, assertions,
hierarchical references, or a clock generator. The host owns the testbench, clock,
reset application interval, sampling, and comparison.

The following example describes a one-bit register which captures `d` at the
rising edge and clears asynchronously while `reset` is high. The last line
reasserts reset after loading one.

```text
case reassert_reset # Reasserting asynchronous reset clears the loaded one before the next edge.
init reset=1 d=0 q=0
step reset=0 d=1 pre.q=0 q=1
init reset=1 d=1 pre.q=0 q=0
```

For a synchronous clear, the last line would contain `pre.q=1 q=0`. Only the
first pre sample of that repeated init can distinguish the two behaviors. When
the public task leaves a pre value unspecified, omit that expectation.

- `case <id> # <one short explanation>` starts one independent test point.
  Give each point a unique ID of up to 63 letters, digits, hyphens or underscores.
  In one sentence, say which stimulus exercises which observable behavior.
  The explanation is required on every header and limited to 240 printable characters.
- Each stimulus line begins with `init` or `step`.
- Every non-clock public input MUST appear exactly once on every stimulus line of that case.
- Use `q=value` for a post expectation and `pre.q=value` for a clocked pre
  expectation. Select either or both for a given output. Each output and phase
  may appear once per line. A table with only unqualified outputs compares
  only post samples.
- The output names on the first line define the checked outputs for that case.
  Every later line must check the same names in at least one phase.
- The host records `checked_outputs` and `unchecked_outputs` for every case.
  If otherwise passing comparisons leave a public output unchecked, the verdict
  is `partial_passed`.
- Values are hexadecimal without a width prefix. The host validates width and rejects
  unknown or out-of-range values.
- Obey the effective case, table-line and expanded-event limits in the host execution
  contract. Defaults are four cases and eight lines per case. Repeated init events count
  toward the expanded-event limits even though they occupy one table line.
- A sequential case without an `init` first line is invalid.
- The `step` line's pre and post expectations refer to the same expanded event.
- A combinational case may use `step` first and treats `init` as a settle step.
  Only unqualified output names are valid for combinational cases.
- Write explanations only on case headers. Each remaining line contains stimulus and expectations.

### 6. Self-check the table before returning it

1. Every stimulus line drives every non-clock input.
2. Every stimulus line of a case checks the same output set.
3. The first sequential line is `init`, and its reset or initialization action is
   explicitly required by the public task.
4. Every expected value is a known hexadecimal pattern within the port width.
5. Each case has its own brief explanation and exercises the behavior it describes.
6. No expected value was copied from the candidate RTL or a simulation result.

### 7. Review a requested test point

When the host names a point for review, independently derive its stimulus and
expectations from the public specification and the supplied execution rules.
The host retains the stimuli, expectations and explanations of the other cases.

Start the reply with `review <id> <action> # <reason>`. Give one public reason of
up to 240 printable characters. Choose one action:

- `keep` when the current stimulus, expectations and explanation are justified.
  Return only the review line.
- `correct` when the point can be repaired. Follow the review line with one complete
  replacement case with the same ID and its own brief explanation. Its inputs,
  expectations, selected outputs and sample phases can change.
- `withdraw` when the public task cannot support this point. Return only the review
  line. The host can remove the last point too.

For example, when the public specification says that reset is synchronous:

```text
review reassert_reset correct # Synchronous reset clears the register on the rising edge.
case reassert_reset # A loaded one remains visible until the reset edge clears it.
init reset=1 d=0 q=0
step reset=0 d=1 pre.q=0 q=1
init reset=1 d=1 pre.q=1 q=0
```

## Output Contract

For initial construction, return the explained table. For a review, return the
decision line and the replacement case only when correcting the point.

## Verification Boundary

A matching table means only that the checked outputs matched the checked cases under
the host sampling plan. If any public output is unchecked, the result is a partial
behavior check and `functional_passed` MUST remain false or unknown. It does not
prove that all public behavior is correct. The RTL author evaluates a mismatch
against the public specification and can request independent review of the point.
Report unchecked outputs and unknown
values separately. For mixed known and unknown bits, a mismatch on any known bit
is a failure. A comparison with unknown bits and all known bits matching remains
unresolved.
