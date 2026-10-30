---
name: rtl-stream-word-boundaries
description: 'Serial parallel conversion: word packing, accepted transfers, residual bits, group boundaries, output-valid timing.'
phases: [generate, repair]
review_status: frozen_default_fixed
---

# RTL Stream Word Boundaries

## Scope

Use for serial-to-parallel, parallel-to-serial or streaming width conversion
where ordering, partial groups and output timing matter. A plain register shift
without framing does not need this method. This is an original general method;
improvement in real-model results has not been established.

The public protocol controls acceptance, interruption, buffering and output
timing. A signal named valid may mark every useful beat, only the start of a
word, or completion of a group. Never infer ready/valid handshaking from names
or add an unrequested ready port.

## Required Inputs

- Input and output widths, serial or chunk ordering and complete-group definition.
- Acceptance rules, enable behavior and any explicit backpressure or busy rule.
- Output latency and whether input can be accepted on an output-producing edge.
- Reset, partial-group interruption, padding and end-of-stream behavior if defined.

## Method

1. **Define the accepted events.** Translate the public protocol into separate
   input acceptance and output consumption events. Valid-only interfaces have
   no implicit acknowledgement. For a serializer, determine when parallel data
   is sampled and whether a new word can replace one still being transmitted.
   Specify whether a valid interruption holds, clears or discards a partial
   group; do not assume that a pause always preserves accumulated data.

2. **Write an ordering ledger.** Label accepted input bits or chunks by arrival
   order, then map them to their destination positions. Distinguish MSB-first
   transfer within a chunk from the order of complete chunks. For serialization,
   identify the first visible bit and the edge that advances to the next one.
   Use labels rather than convenient numeric examples that could hide reversal.

3. **Count accepted content, not elapsed clocks.** Track how many meaningful bits
   or elements remain buffered. For integer grouping, the last accepted element
   completes a group. For unequal widths with a non-integer ratio, preserve the
   unused suffix or prefix according to the ordering ledger; a word boundary
   can split an input chunk. Do not discard residual bits at every output.

4. **Derive simultaneous append and removal.** Describe the ordered buffer before
   the edge, the content accepted on that edge, the output selected and the
   residual content afterward. Under a lossless bit-stream contract, buffered
   content changes by accepted input bits minus consumed output bits. Apply
   this identity only when no specified clear, drop or padding event occurs.
   Determine whether newly accepted bits may contribute to that edge's output;
   neither bypass nor an extra pipeline stage is implied by the identity.

5. **Check capacity and timing together.** Determine the maximum residual content
   under the allowed input/output rates. A narrower single output cannot absorb
   an indefinitely faster input without a specified throttle, drop rule or
   sufficient bounded buffering. Do not conceal an inconsistent rate contract
   by silently losing data. Mark the last-input edge, result-visible edge and
   next-group first-input edge explicitly. Some protocols prohibit accepting
   input during the output cycle even when valid remains high.

6. **Keep data and control aligned.** The output word and its valid indication
   must describe the same group. Distinguish a one-cycle start pulse from a
   per-beat valid level. Reset or interruption must affect data, residual count
   and pending-output control consistently with the public rule. Reconcile
   every final slice and branch with the ordering ledger and edge timeline.

## Verification and Limits

Use independent labels for consecutive input chunks. Check a partial group,
an interruption, the completing input, the output edge and the next group.
For a non-integer ratio, continue until boundaries have crossed several input
chunks, verifying that each accepted bit appears exactly once under a lossless
contract. Negative examples include counting invalid cycles, dropping residual
bits, mixing adjacent groups and accepting input on a forbidden output edge.

Only public rules can determine expected data; unspecified padding, reset timing
or backpressure remains unknown. Finite traces do not establish arbitrary-rate
correctness. Follow the surrounding delivery contract and return complete RTL
when requested, without a testbench or an unsupported passing claim.
