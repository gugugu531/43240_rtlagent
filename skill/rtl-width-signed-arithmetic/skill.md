---
name: rtl-width-signed-arithmetic
description: Derive RTL expression widths and signedness explicitly before implementing arithmetic, comparisons, extensions, truncation, and concatenation.
phases: [generate, repair]
conflict_group: rtl-width-signed-arithmetic
review_status: frozen_rejected_fixed_ab
---

<!--
Copyright (C) 2026 Team 43240
SPDX-License-Identifier: MIT
Migration version: 1.0.0-candidate.1+burr.1
Source repository: https://github.com/wyc888-crypto/amd-rtlagent-prompt-engineering.git
Source commit: fb1c2803e5db0f32b59b9ba9100877f2a0d26412
Source path: skill/rtl-width-signed-arithmetic/SKILL.md
Source SHA-256: d19a6d2aa2e6e65f3f463b0b2df8dfeffadd03eecdf4f009e31e2192a3442e74
Review status: reviewed_not_model_validated
-->

# Agent Skill: RTL Width and Signed Arithmetic

## Purpose

Prevent accidental extension, truncation, and unsigned interpretation by deriving each
public arithmetic relation at an explicit width and signedness before writing RTL.

## When to Use

Use this skill for arithmetic, counters, comparisons, signed shifts, mixed-width operands,
packing, unpacking, concatenation, or any task that states overflow or saturation behavior.

## When Not to Use

Do not use it to invent numeric behavior that the public task leaves unspecified, or as a
replacement for elaboration and functional verification.

## Public Contract Precedence

The public task controls module structure, port order, explicit types, signedness,
widths, and behavior. Generic style advice in this method never overrides an explicit
requirement. Choose variable declarations only where procedural assignment and the
public interface permit them; preserve any explicitly required module dependencies.

## Required Inputs

- The public port widths and signedness.
- The public arithmetic, comparison, packing, or overflow rule.
- For repair, the complete candidate and bound compiler or functional diagnostics.

## Mandatory Workflow

### 1. Build a width table

Record every operand's declared width, signedness, and the width required by the public
mathematical relation. Treat unsized literals and mixed signed/unsigned expressions as
risk items; do not assume they inherit the destination type.

### 2. Derive extension before the operation

Choose zero extension or sign extension from the public rule. Extend operands explicitly
to the operation width before addition, subtraction, comparison, or shifting. Cast only
the smallest expression that needs a signed interpretation.

### 3. Derive the result boundary

Decide whether the destination keeps all result bits, wraps by truncation, saturates, or
reports carry/overflow. Implement only the stated behavior. Check each concatenation by
summing slice and replication widths.

### 4. Check comparisons and shifts separately

Ensure both comparison operands have the intended signedness. For arithmetic right shift,
ensure the left operand is signed at the point of the shift; for logical shift, do not
introduce sign extension.

### 5. Apply the derivation to the final code

Inspect the delivered expression, intermediate declarations, literal sizes, casts, slices,
and destination width. A correct calculation in prose is not sufficient.

## Final Delivery Check

1. Every unsized literal that can change width or sign is replaced or justified by the
   public contract.
2. Each mixed-width operation has explicit extension before the operation.
3. Each signed comparison or arithmetic shift has an explicitly signed operand.
4. Every truncation, wrap, saturation, carry, and overflow bit matches the public rule.
5. Every concatenation width equals its destination width.
6. The final answer is a complete RTL file with the required top and dependency modules,
   not a derivation or patch fragment.

## Verification Contract

Compilation establishes syntax and elaborated widths, not arithmetic intent. Boundary
values, sign changes, maximum/minimum operands, and overflow transitions require public
functional checks.

## Output Format

Return one complete RTL file under the surrounding output contract, including the
required top and all dependency modules needed by the public task.

## Behavioral Constraints

- Never change a public port width or signedness to make an expression convenient.
- Never add saturation, wrapping, or a carry output unless the public task requires it.
- Never treat a compiler warning-free expression as proof of correct numeric behavior.
- Never claim PASS; leave verification to the framework.
