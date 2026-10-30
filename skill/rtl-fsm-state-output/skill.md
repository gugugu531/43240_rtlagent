---
name: rtl-fsm-state-output
description: Derive finite-state transitions and output timing from the public state, event, reset, and Moore or Mealy contract before implementing RTL.
phases: [generate, repair]
conflict_group: rtl-fsm-state-output
review_status: frozen_rejected_fixed_ab
---

<!--
Copyright (C) 2026 Team 43240
SPDX-License-Identifier: MIT
Migration version: 1.0.0-candidate.1+burr.1
Source repository: https://github.com/wyc888-crypto/amd-rtlagent-prompt-engineering.git
Source commit: fb1c2803e5db0f32b59b9ba9100877f2a0d26412
Source path: skill/rtl-fsm-state-output/SKILL.md
Source SHA-256: cf8d2e0ff95ebaba250f16fcfab320b4c7c962462facd0395f50a662d591c1fc
Review status: reviewed_not_model_validated
-->

# Agent Skill: RTL FSM State and Output Timing

## Purpose

Keep state transition, registered state, and output timing aligned so an otherwise correct
FSM does not assert an output in the wrong cycle.

## When to Use

Use this skill for named-state machines, sequence detectors, controllers, protocol phases,
or tasks where outputs depend on state and possibly current inputs.

## When Not to Use

Do not use it for a standalone shift/register datapath merely because it has internal state,
or when the public task does not define enough transition or output behavior to derive an FSM.

## Public Contract Precedence

The public task controls module structure, port order, explicit types, signedness,
widths, and behavior. Generic style advice in this method never overrides an explicit
requirement. Choose variable declarations only where procedural assignment and the
public interface permit them; preserve any explicitly required module dependencies.

## Required Inputs

- Public states or an equivalent history definition.
- Clock/reset timing, transition conditions, priorities, and output timing.
- For repair, the complete candidate and bound counterexample or tool diagnostics.

## Mandatory Workflow

### 1. Normalize the state contract

List each state, reset state, transition condition, and priority. Mark unspecified transitions
as unknown rather than silently choosing hold or reset.

### 2. Classify each output

For every output, determine from public text whether it is Moore (current-state), Mealy
(current-state and current-input), or explicitly registered. Record the cycle in which the
observer must see it.

### 3. Separate current and next state

Use a clocked block for state storage and a complete combinational relation for next state.
Use old-state semantics on the active edge. Do not read `next_state` as though it were
already registered unless the public timing requires look-ahead behavior.

### 4. Trace discriminating transitions

Walk through reset, one self-loop, one transition, and one output-producing event. Write the
state and visible output before and after each active edge. Include overlapping input events
when the public task gives them priority.

### 5. Reconcile the final implementation

Compare every transition and output expression with the trace. Check reset polarity/timing,
default transitions, illegal-state handling, and whether registered outputs add a cycle.

## Final Delivery Check

1. Reset enters the exact public state at the stated event.
2. Every public transition and priority is represented once, with no invented transition.
3. Next-state logic is complete or intentionally preserves state according to the task.
4. Moore, Mealy, and registered outputs appear in the required cycle.
5. Procedural outputs use variables and ANSI ports are not redeclared.
6. The response is a complete RTL file with the required top, dependency modules,
   and exact public interface.

## Verification Contract

Compilation does not establish transition coverage or output latency. Directed traces must
cover reset, self-loops, competing transitions, accepting states, and exit behavior; finite
tests still do not prove an unbounded temporal property.

## Output Format

Return one complete RTL file under the surrounding output contract, including the
required top and all dependency modules needed by the public task.

## Behavioral Constraints

- Never infer Moore versus Mealy behavior from a preferred coding style.
- Never add a recovery transition unless the public task defines it. Unspecified
  behavior remains unspecified; synthesis convenience does not create a requirement.
- Never move an output across a clock boundary to make a trace pass.
- Never claim PASS; leave verification to the framework.
