---
name: rtl-sequential-state-update
description: Derive and implement edge-triggered register, shift, rotate, and counter updates from the public clock, reset, priority, and next-state contract.
---

<!--
Copyright (C) 2026 Team 43240
SPDX-License-Identifier: MIT
Migration version: 2+burr.1
Source repository: https://github.com/wyc888-crypto/amd-rtlagent-prompt-engineering.git
Source commit: fb1c2803e5db0f32b59b9ba9100877f2a0d26412
Source path: skill/rtl-sequential-state-update/SKILL.md
Source SHA-256: 3afd66e628e00af50d3df1d30000038672892c9336c7aec9d9e24505e3c1bd40
Review status: reviewed_not_model_validated
-->

# Agent Skill: RTL Sequential State Update

## Purpose

Produce a complete RTL file, including the top and any required dependency modules,
whose state updates follow the public specification.
Treat the task statement and declared interface as authoritative. This skill supplies
a method; it does not supply task-specific values, hidden expectations, or a passing verdict.

## When to Use

Use this skill when the public task requires a register, logical or arithmetic shift,
rotation, or counter whose value changes on a stated clock event.

## When Not to Use

Do not use it for a purely combinational task, when the public text does not define a
clocked state update, or when the primary problem is a named-state transition table
that needs the dedicated FSM method.

## Public Contract Precedence

The public task controls module structure, port order, explicit types, signedness,
widths, and behavior. Generic style advice in this method never overrides an explicit
requirement. Choose variable declarations only where procedural assignment and the
public interface permit them; preserve any explicitly required module dependencies.

## Required Inputs

- The complete public task statement and declared interface.
- For repair, the complete current candidate and all bound diagnostics or unresolved public counterexamples.
- Any mechanically derived next-state relation already supplied by the framework.

If clock, reset, priority, direction, fill, or overflow behavior is not public, do
not invent it. Implement only what is stated and preserve the framework's unknown state.

## Mandatory Workflow

### 1. Write the state contract before choosing syntax

Identify the state vector and record:

- clock event;
- reset timing, polarity, and value;
- load, enable, direction, selector, and hold controls;
- the stated priority between simultaneous controls;
- operation width and any stated wrap, fill, or saturation behavior.

Do not infer semantics from a port name alone. A signal called `reset_n`, `enable`,
or `load` has only the behavior stated by the public task.

### 2. Form one ordered next-state decision

Order the branches exactly as the public priority requires. Include an explicit hold
case whenever the specification requires state retention. For an asynchronous reset,
put the declared reset edge in the sensitivity list; for a synchronous reset, test it
inside the clocked block only. Do not convert one reset mode into the other.

Use nonblocking assignments for clocked state. Every right-hand state reference is
the value before the active edge; source-code order must not be used to simulate a
multi-step shift within one edge.

### 3. Check the source of every destination bit

For shifts and rotations, map each destination bit to its old-state source before
writing a concatenation or loop. Check the boundary separately:

- logical shift: insert the stated constant;
- arithmetic right shift: repeat the old sign bit;
- rotation: wrap the displaced old-state bit to the opposite boundary;
- hold: every destination bit keeps the corresponding old-state bit.

For a counter, determine the arithmetic width and the stated overflow behavior.
Do not add saturation, signed interpretation, or a wider hidden state unless required.

### 4. Reconcile the method with the actual code

When repairing, compare the public relation with the current sensitivity list,
condition order, selectors, slices, concatenations, and assignments. Apply every
identified correction to the delivered code. A correct explanation is not a repair
until the expression and all affected branches implement it.

Preserve the module name, port names, directions, widths, and unrelated public behavior.
Do not remove an unresolved counterexample merely because another branch compiles.

### 5. Use one discriminating public trace as a consistency check

Choose a legal initial value whose adjacent bits are not all equal. Walk through the
public reset, load, hold, and one active update using old-state semantics. For a
directional operation, use a value that distinguishes left from right and hold.

Compare the trace with the final expression, including the boundary bit and control
priority. This is a local consistency check, not permission to declare PASS; the
framework must rerun its independent checks.

### 6. Deliver the complete RTL file

Return a complete, extractable RTL file under the surrounding output contract.
Include the required top, dependency modules, declarations, and matching `endmodule` statements. Do not replace the code
with a plan, checklist, testbench, waveform discussion, or partial patch.

## Final Delivery Check

Before returning the RTL file, inspect the final code rather than the reasoning draft:

1. Every output written by an `always`, `always_ff`, `always_comb`, or `always_latch`
   block is declared as a variable (`reg`, `logic`, or an equivalent explicit variable
   type). An output driven only by `assign` remains a net.
2. An ANSI port declared inside the module header is not declared again in the module
   body. Correct the header declaration instead of adding a second declaration.
3. Every concatenation is syntactically complete. Count the width of every slice,
   replicated item, fill bit, and wrapped bit; their sum must equal the destination width.
4. For each shift or rotation, state the old-state source for the low boundary, high
   boundary, and at least one interior destination bit, then compare those sources with
   the final expression.
5. The sensitivity list, reset timing and polarity, branch priority, hold behavior, and
   assignment type all match the public contract.
6. The response contains the complete required top and dependency modules, exact public
   ports, all declarations, and matching `endmodule` statements; no repair remains only in prose.

This checklist is a generation discipline. It does not replace the framework's
interface checks, `xvlog`, `xelab`, synthesis, or independent functional checks.

## Verification Contract

The implementation remains unverified until the framework checks the interface,
compiles and elaborates the module, and reruns any applicable public behavior tests.
A clean compile proves neither shift direction nor reset, priority, hold, or overflow
semantics. Finite public tests do not constitute formal proof.

## Output Format

Follow the surrounding response contract and return one complete RTL file containing
the required top and all dependency modules needed by the public task.
Do not add a testbench, a second alternative, a patch fragment, or a PASS claim.

## Behavioral Constraints

- Never use a task identifier, hidden test, reference implementation, or score to choose an expression.
- Never change the public interface to make an implementation easier.
- Never guess an unspecified reset, priority, direction, fill, or overflow rule.
- Never generate or weaken a testbench and then treat its result as authoritative.
- Never claim that the candidate passed; report only the complete RTL requested by the surrounding prompt.
- If the public requirements conflict, preserve the conflict for the framework instead of silently choosing one clause.
