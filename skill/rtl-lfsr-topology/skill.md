---
name: rtl-lfsr-topology
description: 'Galois/Fibonacci LFSR topology: tap indexing, feedback recurrences, seed loading, shift direction.'
phases: [generate, repair]
review_status: frozen_default_fixed
---

# RTL LFSR Topology

## Scope

Use for a linear feedback shift register (LFSR) whose public diagram or text
specifies its feedback connections. The method also helps with a fully specified
CRC recurrence, but a polynomial or an algorithm name alone may not determine
its serial bit order, reflection convention or update timing. An ordinary shift
or rotation without feedback is outside this skill's focus.

This is an original general method; improvement in real-model results has not
been established. No familiar tap table, task identity or reference implementation
may supply a missing connection or constant.

## Required Inputs

- State width, bit labels, shift direction and feedback operation.
- Explicit tap connections or a convention that unambiguously determines them.
- Clock, reset or seed load, enable and their public priority.
- For input-driven feedback, input bit order and the update rule per accepted bit.

## Method

1. **Resolve the diagram's indexing.** Write down which physical register bit
   each label denotes. A tap number may name a polynomial exponent, a one-based
   stage position or a zero-based bit index. Determine that convention from
   the public contract before translating labels into Verilog indices. The
   left side of a drawing does not necessarily mean the most significant bit.

2. **Identify the feedback topology.** In a Fibonacci arrangement, selected
   old-state bits usually combine into a feedback value inserted at a boundary.
   In a Galois arrangement, a shifted-out old-state bit usually affects several
   destinations along the shift path. These descriptions identify connections,
   not a license to replace one arrangement with another. Follow the stated
   XOR, XNOR or input-combining operation exactly.

3. **Write destination equations before concatenations.** For every next-state
   bit, identify its ordinary shift source, any feedback source and any external
   input contribution. Give the low boundary, high boundary and every distinct
   tap case explicit attention. All sources belong to the same old state.
   Do not update one tapped bit and then reuse that new value for another bit.

4. **Check the recurrence as a whole.** Separate the plain shift relation from
   feedback injection, then combine them without losing or duplicating a
   destination. Check that each state bit has one intended next value. If using
   a mask, derive each mask bit from the destination equations; never select
   a remembered constant because the width or polynomial looks familiar.
   Count concatenation widths and avoid slices outside the declared vector.

5. **Preserve initialization and acceptance.** Record whether reset or load is
   synchronous, its polarity and exact seed, and whether an enabled update can
   occur on the same edge. Keep disabled state only when the public rule says
   to hold. Do not replace a zero seed to avoid lockup or add a recovery circuit
   unless requested. For CRC-style input, distinguish one accepted bit from
   one clock cycle and from a whole-word update.

6. **Inspect the actual repair.** Compare the delivered slices, tap indices,
   feedback source and branch priority against the destination equations. Keep
   the public interface and any mandated structure. A topologically different
   LFSR can have an attractive period and still violate the required sequence.

## Verification and Limits

For a linear XOR recurrence, one-hot old states expose individual connection
errors: activate a source bit and check all affected destinations after one
update. For affine or input-driven recurrences, also check the all-zero state
and independent input contributions; do not assume linearity when an inversion
is present. Include an asymmetric seed and several successive accepted updates
to distinguish reversed direction, a missing tap and accidental in-place updates.

Expected states must be derived from public connections independently of the
candidate. These checks do not prove a maximal period, CRC compatibility or
physical timing. Do not assert such properties without separate evidence.
Follow the surrounding output contract and deliver complete RTL when requested;
do not include a reference sequence, testbench or passing verdict as the answer.
