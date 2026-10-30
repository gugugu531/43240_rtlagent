---
name: rtl-counter-terminal-events
description: 'Bounded counters: terminal count pulses, modulo reloads, timer expiration, cascaded digit enables.'
phases: [generate, repair]
review_status: frozen_default_fixed
---

# RTL Counter Terminal Events

## Scope

Use this method when the difficult part is deciding which accepted count event
reaches a terminal value, reloads a bounded counter, advances an upper digit, or
changes a divider output. A free-running register or an ordinary shift does not
need this method. This is an original general method; improvement in real-model
results has not been established.

The public statement and interface determine all ranges, initial values, control
priorities and observation cycles. Do not infer a decimal range from a name, or
invent an illegal-state recovery policy. Missing timing remains unspecified.

## Required Inputs

- The legal count values, direction, reset or initialization rule and reload rule.
- The event that accepts a count, including enable, pause, load and clear behavior.
- The meaning and timing of every carry, enable, terminal flag and output pulse.
- For repair, the current candidate and evidence bound to that candidate.

## Method

1. **Separate a value from an event.** Record the legal inclusive range and the
   predicate for accepting one count. Distinguish “the stored count equals the
   limit” from “a count is accepted while at the limit” and from “this update
   reaches the limit.” A level flag can remain high during a pause; an event
   pulse may require an accepted update. Use the definition actually stated.

2. **Write the boundary timeline.** Label the old state immediately before each
   edge and the new state after nonblocking assignments settle. Walk through
   the predecessor of the terminal value, the terminal value and the reload
   value. Place each visible output on that timeline. Do not automatically
   register a combinational carry enable or remove a required output register.

3. **Derive each digit from the same old state.** In a cascade, an upper digit
   advances only when the specified lower-digit carry events occur. If several
   digits wrap on one edge, derive all their enables before any digit updates.
   Do not inspect an already updated lower digit, or let source-code assignment
   order simulate propagation over several clock edges.

4. **Handle controls before arithmetic.** Order reset, load, clear, enable,
   direction and terminal handling by the public priority. Check a load at the
   terminal boundary, a pause there, and direction changes at each endpoint.
   Explicitly distinguish wrap, saturation, reload and hold. Non-power-of-two
   ranges require their stated boundary behavior; register truncation alone
   does not implement an arbitrary modulus.

5. **Count edges, then interpret time.** For a timer, state whether its start
   edge counts toward the duration. For a divider, separately count the interval
   between pulses, the interval between output toggles and the complete output
   period. Use only the clock edges and duty-cycle requirements provided. Do
   not substitute a generated clock or a second-edge design for a missing rule.

6. **Compare the delivered code with the timeline.** Check terminal comparisons,
   branch order, carry predicates and output registers against the same trace.
   A corrected explanation is insufficient if the final expression still uses
   the wrong old/new value. Preserve unrelated behavior and the exact interface.

## Verification and Limits

Use a small, independently specified bounded counter to check its last two
values, wrap or reload, pause at the endpoint and overlapping controls. For a
cascade, include an edge where one lower digit wraps and another where several
wrap together. A useful negative example advances an upper digit from the new
lower value, or produces a pulse repeatedly while counting is disabled.

Expected values must come from the public rules, never from candidate outputs.
Uninitialized or unspecified states are not zero by default. Compilation does
not establish pulse timing or period. Follow the surrounding delivery contract;
when RTL is requested, return the complete required implementation without a
testbench or a claim that verification passed.
