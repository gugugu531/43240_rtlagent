---
name: rtl-pipeline-transaction-alignment
description: 'Pipeline transaction alignment: pipelined operands, partial results, valid bits, sideband control, latency, bubbles, stalls, flushes, ready/valid backpressure.'
phases: [generate, repair]
---

# Pipeline Transaction Alignment

Use when a public task requires multiple registered stages, pipelined arithmetic,
or data and control that must travel together. A clock input alone does not imply a
pipeline. This method does not select an arithmetic algorithm or introduce a ready/valid
protocol absent from the public interface. Read the statement, interface, latency and
acceptance rules; for repair also inspect the parent candidate and its actual diagnostics.
This original method has not established a model-quality improvement.

## Define the observation convention

Identify the edge that accepts an input and the edge after which the corresponding
output is visible. Draw a cycle table with input acceptance, each stage's contents,
output data and output validity. Clarify whether the specification counts the accepting
edge as the first cycle. Do not turn an L-stage description into a latency formula
until that convention is known.

Give two adjacent input transactions symbolic labels A and B. Attach a label to every
registered operand, partial sum/product, carry, sign, opcode, destination and validity
bit. At each stage, all operands of one result must belong to the same label. A later
stage cannot use a current external operand to finish an earlier transaction unless
the public contract guarantees that operand is held for the entire operation.

## Derive one transfer rule per stage

- In a fixed-throughput pipeline, advance data and metadata at each required edge.
  An invalid input normally creates a bubble if the protocol specifies valid gating;
  it does not automatically freeze earlier valid work.
- A global clock enable freezes all state covered by that enable, including carries
  and valid bits. Do not freeze only data while advancing its validity.
- In a ready/valid pipeline, acceptance requires the specified handshake. An occupied
  stage blocked downstream retains its data and validity. Upstream replacement is
  permitted only when that stage can accept it. Derive simultaneous transfer and
  replacement from capacity, rather than writing independent conflicting assignments.
- Flush and reset remove or preserve transactions exactly as specified. Clearing valid
  bits does not require zeroing every datapath register unless that is observable and
  required. Do not let pre-flush metadata announce a post-flush result.

Use nonblocking assignments for stage registers. Their stage-register sources refer to
the pre-edge state; textual order does not forward a newly scheduled value. A combinational
intermediate is not a pipeline stage. If the interface has only start/busy/done,
derive its acceptance and completion separately rather than assuming streaming behavior.

## Check transaction conservation

Trace back-to-back unequal inputs, a bubble between inputs, a stall with a valid final
stage, resumption, and a reset/flush in flight when those controls exist. Every accepted
transaction must emerge once, in the specified order, with the correct metadata, unless
the contract explicitly cancels it. Verify the result at its declared latency, not merely
at some later cycle when it happens to match. A pipelined arithmetic repair must align
carry and partial-result paths as well as top-level operands.

Keep the declared ports and stage requirements. Return complete RTL under the surrounding
output contract. Static cycle tracing does not establish timing closure, throughput under
all traffic, or functional PASS; those require the corresponding actual checks.
