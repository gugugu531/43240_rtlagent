---
name: rtl-sequential-state-update-v3
description: Implement and repair clocked registers, shifts, rotations, and counters with explicit ANSI output-variable and concatenation delivery checks.
phases: [generate, repair]
conflict_group: sequential-state-update
review_status: frozen_candidate_not_default
---

<!--
Copyright (C) 2026 Team 43240
SPDX-License-Identifier: MIT
Migration version: 3.0.0-candidate.1+burr.1
Source repository: https://github.com/wyc888-crypto/amd-rtlagent-prompt-engineering.git
Source commit: fb1c2803e5db0f32b59b9ba9100877f2a0d26412
Source path: skill/rtl-sequential-state-update-v3/SKILL.md
Source SHA-256: cc36e274504975c19439889313f5bde38670e4655b7ba2183f4e26e95174ed1b
Review status: reviewed_not_model_validated
-->

# Agent Skill: RTL Sequential State Update v3

## Purpose

Produce a complete RTL file, including the top and any required dependency modules,
whose clocked state updates follow the public specification. The task and declared interface are authoritative; this skill supplies
a method and does not supply task-specific values or a passing verdict.

## When to Use

Use for a register, logical or arithmetic shift, rotation, or counter whose value
changes on a stated clock event, including repair of such a candidate.

## When Not to Use

Do not use for a purely combinational task or a named-state transition table that
needs the dedicated FSM method. Do not invent missing clock, reset, priority, fill,
direction, overflow, or initialization behavior.

## Public Contract Precedence

The public task controls module structure, port order, explicit types, signedness,
widths, and behavior. Generic style advice in this method never overrides an explicit
requirement. Choose variable declarations only where procedural assignment and the
public interface permit them; preserve any explicitly required module dependencies.

## Required Inputs

- Complete public task statement and interface.
- For repair, the complete parent candidate and its bound diagnostic.
- Any mechanically derived next-state relation supplied by the framework.

## Mandatory Workflow

### 1. Enforce the delivery contract before deriving logic

An output written by a procedural block must be a variable in its ANSI port
declaration. Under this delivery contract, write:

```verilog
output reg [W-1:0] q
```

or the SystemVerilog `logic` equivalent. Do not write an ANSI output and then declare
the same identifier again in the module body:

```verilog
output [W-1:0] q;
reg [W-1:0] q;
```

Adding `reg` or `logic` changes the object type. It preserves names, directions,
and widths only when those declarations are otherwise unchanged. Make this correction
only when the public task does not forbid the resulting type; an explicit type
requirement takes precedence over this generic coding method.
An output driven only by `assign` remains a net.

### 2. Write one ordered state contract

Record the clock event, reset timing/polarity/value, controls, priority, hold behavior,
operation width, and stated wrap/fill/saturation behavior. Put an asynchronous reset
edge in the sensitivity list; test a synchronous reset only inside the clocked block.
Use nonblocking assignments. Every right-hand state reference denotes the value before
the active edge.

### 3. Map boundary and interior bits

For every shift or rotation, identify the old-state source of the low boundary, high
boundary, and one interior bit. Logical shifts insert the stated constant; arithmetic
right shifts repeat the old sign bit; rotations wrap the displaced bit. For counters,
keep the stated arithmetic width and overflow behavior.

When a replicated item is combined with another item, the replication needs its own
braces inside an outer concatenation:

```verilog
{N{expr}}                 // one replication expression
{{N{expr}}, slice}        // replication plus another concatenation item
```

For an arithmetic right shift of a `W`-bit vector by a constant `N` with
`1 <= N < W`, the generic form is:

```verilog
{{N{q[W-1]}}, q[W-1:N]}
```

Do not use `{N{expr}, slice}`. Count the replication and slice widths separately and
require their sum to equal the destination width. Handle `N == 0`, `N >= W`,
and a variable shift amount separately according to the public task; the slice above
is not a valid template for those cases.

### 4. Repair the delivered code, not only the explanation

Compare the contract with the parent sensitivity list, declarations, branch order,
selectors, slices, concatenations, and assignments. Apply every identified correction
to the final module. Preserve the public module and port signature and unrelated correct
behavior.

### 5. Check one discriminating public trace

Use a legal value with unequal adjacent bits. Walk through reset/load/hold and one
active update with old-state semantics. Check direction, boundary bit, and priority
against the final expression. This is a consistency check, not a PASS claim.

## Final Delivery Check

Inspect the final code itself:

1. Every procedurally driven output is `output reg` or `output logic` in the ANSI header.
2. No ANSI port identifier is declared again in the module body.
3. Every replication used with a slice has both replication braces and outer braces.
4. Every concatenation has the destination width and correct boundary sources.
5. Clock/reset timing, priority, hold behavior, and assignment type match the public contract.
6. Return the complete required top and dependency modules with exact public ports,
   all declarations, and matching `endmodule` statements.

## Verification Contract

The implementation remains unverified until the framework checks the interface,
runs `xvlog`, `xelab` and synthesis, and performs applicable independent functional checks. A clean
compile does not prove direction, priority, reset, hold, or overflow semantics.

## Output Format

Follow the surrounding response contract and return one complete RTL file containing
the required top and all dependency modules needed by the public task.
Do not return a testbench, alternative implementation, patch fragment, or PASS claim.

## Behavioral Constraints

- Never use task identifiers, hidden tests, reference implementations, or scores.
- Never change the public interface to simplify the implementation.
- Never leave an intended repair only in reasoning text.
- If public requirements conflict, preserve the conflict for the framework rather than guessing.
