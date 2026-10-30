---
name: rtl-packed-index-neighborhood
description: 'Packed indexing: vector lanes, variable part selects, flattened grids, cellular-automaton neighbors, row boundaries, wrap rules, simultaneous updates.'
phases: [generate, repair]
---

# Packed Indices and Neighborhood Updates

Use when correctness depends on a packed lane selection, vector permutation, flattened
grid, or local-neighbor recurrence. Do not use this as a generic combinational-completeness
or arithmetic-width checklist. Required inputs are the public packing order, dimensions,
legal index range, boundary policy and update event; for repair include the actual parent
candidate and bound diagnostic. This original method supplies no task-specific answer or
claim of model improvement.

## Write the index map first

Define the position of one logical element in the packed vector. For example, when
the public contract says row-major packing with the first column in the least significant
lane, the bit base of element (r,c) is (r*C+c)*W. This formula is conditional: reverse
order, column-major layouts and ascending declarations require their own map.

Write the inverse map and check the first element, final element, a row boundary and
one interior element. Track logical index, packed position and bit significance separately.
For a mux, distinguish the selected lane number from the bit offset; for a permutation,
identify exactly one source for each destination. Use named intermediate indices when
they make the relation easier to inspect.

An indexed part select may have a variable base but requires a constant width. Verify
the language mode and the declared vector direction before choosing `+:` or `-:`.
Never clamp an invalid selector, wrap it, or replace its unknown result with zero unless
the public specification explicitly requires that behavior.

## Resolve boundaries in logical coordinates

For each neighbor offset, derive the row and column separately before flattening.
Adding one to a flattened index crosses a row boundary and is not generally the right
neighbor. Keep fixed boundary values, wrapping, reflection and omitted neighbors distinct.

For toroidal wrapping, use bounded conditional indices or normalize each coordinate
within its own dimension. A negative Verilog remainder is not a normalized modulo
index; do not use a negative intermediate directly as an array index. Check tiny legal
dimensions: different neighbor offsets can identify the same cell. Whether to count
offsets or unique cells follows the specification, not an automatic deduplication rule.

## Separate one generation from the next

For a cellular automaton or stencil recurrence, compute every next cell only from the
old grid. In-place procedural updates can turn a parallel step into a traversal-order
dependent computation. Use a distinct next-state relation or clocked nonblocking updates
with old-state sources. Keep load/hold/reset priority independent of the neighborhood rule.
Size any neighbor-count accumulation to represent the maximum count before applying
the local rule.

## Check the map and the recurrence independently

Use distinguishable lane values for muxes and permutations, or a single active cell at
an interior, edge and corner for grids. Inspect all boundary sources, then run at least
two generations so a wrong update order cannot hide behind a symmetric initial state.
Check the smallest permitted dimensions and non-power-of-two sizes if parameterized.
Compare the final slices and indices with the map, preserving unspecified behavior.

Return the complete requested RTL. These checks establish neither full equivalence nor
a tool PASS, and do not authorize changing the public packing or adding padding ports.
