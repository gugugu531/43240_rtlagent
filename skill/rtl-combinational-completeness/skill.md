---
name: rtl-combinational-completeness
description: Implement complete combinational RTL with explicit defaults, full assignment coverage, and public priority semantics without unintended storage.
---

<!--
Copyright (C) 2026 Team 43240
SPDX-License-Identifier: MIT
Migration version: 1.0.0-candidate.1+burr.1
Source repository: https://github.com/wyc888-crypto/amd-rtlagent-prompt-engineering.git
Source commit: fb1c2803e5db0f32b59b9ba9100877f2a0d26412
Source path: skill/rtl-combinational-completeness/SKILL.md
Source SHA-256: 55d29431f7b49e11e9e9ca1e69ccbd5c7d147c537f83471c143e2e29bcd58907
Review status: reviewed_not_model_validated
-->

# Agent Skill: RTL Combinational Completeness

## Purpose

Implement public combinational behavior without unintended latches, stale values, hidden
priority changes, or incomplete assignment coverage.

## When to Use

Use this skill for truth tables, multiplexers, encoders, decoders, combinational next-state
logic, and output logic whose value must depend only on current inputs and state.

## When Not to Use

Do not use it to convert a clocked public requirement into combinational logic, or to add
defaults where the task explicitly requires storage or an unknown/don't-care result.

## Public Contract Precedence

The public task controls module structure, port order, explicit types, signedness,
widths, and behavior. Generic style advice in this method never overrides an explicit
requirement. Choose variable declarations only where procedural assignment and the
public interface permit them; preserve any explicitly required module dependencies.

## Required Inputs

- The complete public truth relation, conditions, priorities, and output widths.
- For repair, the complete candidate and bound lint or functional evidence.

## Mandatory Workflow

### 1. Enumerate assignment targets

List every signal written by the combinational block and the conditions that determine it.
Separate independent outputs from shared priority decisions.

### 2. Establish public priority

Translate stated priority into one ordered `if`/`else if` chain or an equivalent case form.
Do not create priority merely from convenient source order.

### 3. Guarantee coverage

Give every target an intentional value on every reachable path. Prefer a public default at
the start of the block followed by overrides, or a complete case with a justified default.
Use blocking assignments in ordinary combinational procedural logic.

### 4. Check case semantics

Account for all public selector values. Use wildcard case forms only when their treatment
of X/Z is compatible with the public requirement; otherwise use exact comparisons.

### 5. Reconcile final code

Inspect nested branches, early defaults, each output, and each temporary. Ensure no branch
accidentally preserves an old value and no later assignment reverses the intended priority.

## Final Delivery Check

1. Every combinational target is assigned on every intended path.
2. Defaults and `default` branches implement public behavior rather than masking omissions.
3. Branch order matches the public priority.
4. Procedural outputs use `reg`/`logic` and ANSI ports are not redeclared.
5. No clock, edge, delay, or state-holding construct was introduced.
6. The response is a complete RTL file with the required top, dependency modules,
   and exact public interface.

## Verification Contract

Lint can detect some incomplete assignments but cannot prove truth-table intent or priority.
Use exhaustive checks for a small finite input domain and directed boundary cases otherwise.

## Output Format

Return one complete RTL file under the surrounding output contract, including the
required top and all dependency modules needed by the public task.

## Behavioral Constraints

- Never silence a latch warning by inventing a default not supported by the task.
- Never add a clocked register to repair combinational completeness.
- Never weaken exact X/Z requirements by selecting a convenient wildcard case.
- Never claim PASS; leave verification to the framework.
