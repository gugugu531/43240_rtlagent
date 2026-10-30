---
name: rtl-memory-accepted-transactions
description: 'Single-clock storage: synchronous FIFO occupancy, accepted push/pop transactions, RAM collision semantics, readout latency.'
phases: [generate, repair]
---

# Memory and Accepted Transactions

Use for a synchronous FIFO (first-in, first-out queue), RAM, or register file whose
boundary behavior depends on simultaneous requests. Do not apply a single-clock
occupancy equation to asynchronous FIFOs or infer clock-domain crossing circuitry.
Read the public interface and behavior; for repair also read the actual parent
candidate and its bound diagnostic. This is an original general method, not evidence
of model improvement or a substitute for independent checking.

## Separate requests from operations that occur

Write a small event table before coding. For a queue, cover empty, interior and full
occupancy with neither request, push only, pop only and both. Define accepted push
and accepted pop in each row from the specification. In particular:

- At full, a simultaneous pop may or may not permit a push.
- At empty, a simultaneous push may or may not supply a pop directly.
- A request rejected at a boundary must not advance its pointer or update occupancy.

These are interface choices, not consequences of the word FIFO. Do not assume
fall-through, bypass, overwrite, or full replacement when the public contract is
silent. Keep an unresolved boundary requirement visible to the surrounding workflow.

For depth D, derive occupancy after the edge as old occupancy plus accepted push
minus accepted pop. Implement the four accepted-event combinations directly, or use
explicitly sized arithmetic that represents every value from 0 through D. Distinguish
address width from occupancy width. Natural pointer overflow implements modulo D
only for power-of-two depth; otherwise wrap explicitly at D-1. Handle legal depth-one
parameters without zero-width declarations or invalid slices.

## Bind data visibility to the same events

State whether a read is combinational, registered, or first-word fall-through, and
which edge makes data valid. Keep the output hold/reset policy separate from the
memory contents. Resetting pointers does not imply clearing the entire memory.
Derive empty/full from the specified old or updated state; do not add a register and
accidentally move a flag by one cycle.

For RAM and register-file ports, list accepted reads and writes and resolve a same-address
collision: old data, new data, unchanged output, or explicitly unspecified data.
For a clocked array read and nonblocking write, the read ordinarily observes the old
array value. A specified new-data behavior needs an explicit forwarding path or an
equivalent supported implementation. Do not rely on source-code ordering to choose it.
Multiple write ports also require the specified same-address priority.

## Discriminating checks

Use distinct data words and trace wraparound, the final free slot, removal of the final
word, and simultaneous requests at all three occupancy classes. Confirm ordering,
accepted-event counts, flags and read latency together. For memory collisions, use
different old/new words so the policies are distinguishable. Test reset while requests
are active according to its declared priority. Check the final candidate, including
data and pointer branches; a correct count alone does not establish correct storage.

Return the complete RTL required by the surrounding contract. Do not add an interface
signal, hidden initialization or a testbench to repair unspecified semantics. Compilation
and these finite traces do not prove memory inference, asynchronous safety or a passing result.
