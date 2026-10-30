---
name: rtl-kmap-coordinate-mapping
description: 'Karnaugh-map coordinates: row/column labels, minterm numbering, care cells, Boolean equivalence, SOP/POS covers, cofactor decomposition.'
phases: [generate, repair]
---

# Karnaugh Map Coordinates and Care Sets

Use for a public Karnaugh map, numbered minterm/maxterm set, or explicitly requested
sum-of-products (SOP), product-of-sums (POS) or mux decomposition. This is a method for
coordinate interpretation and Boolean equivalence, not a replacement for a rejected
generic combinational skill. Read the actual public labels, input significance and
care conditions; for repair inspect the candidate expression and its bound diagnostic.
This original method is not a measured improvement in model solving quality.

## Recover the specified Boolean domain

Record the input variable order and which variables label rows and columns. Map each
displayed cell to its input assignment using the printed labels. Adjacent Karnaugh-map
labels commonly use Gray order, but do not assume a conventional order if another is
shown. A minterm number depends on the declared bit significance, not its screen position.
If an essential diagram or label is absent, report that missing evidence to the workflow;
do not reconstruct a familiar problem from its title.

Separate the ON set, OFF set and explicitly permitted don't-care set for each output.
An unspecified table row is not automatically a don't-care, and a synthesis don't-care
is not the same as an observed simulation X. Do not use `casex` to conceal an uncertain
input or output. Where the specification explicitly permits either binary output, choose
a deterministic value if compatible with the requested implementation form.

## Derive the requested form

For SOP, group required ones, optionally including don't-cares but never required zeros.
For POS, group required zeros, optionally including don't-cares but never required ones.
Rectangular groups have power-of-two size and may wrap across opposite edges of a
standard map; they do not connect diagonally. Keep only invariant variables in the
corresponding product or sum term. Derive literal polarity by evaluating that term on
the group rather than memorizing an ambiguous sign rule.

For a mux implementation, fix the specified select variables and derive a cofactor
for each select assignment from the table. Each data input may still be a function of
the remaining variables. Preserve the public select-bit significance; an otherwise
equivalent function with swapped select wiring does not implement the required structure.

## Check equivalence before minimizing further

Evaluate the derived expression for every cared-for input assignment when the domain
is small. Check ON and OFF cells, including corners and wrapped groups; checking only
the ones can miss an overlarge implicant. Verify each output independently and confirm
the final implementation retains the required SOP, POS or mux structure. Equivalence
alone does not establish minimality when a minimum form is requested; compare admissible
covers under the specified cost criterion, retaining multiple equal minima when relevant.

For repair, locate the first cared-for assignment that differs, map it back to the
original row/column labels, and correct the actual expression or mux input. Do not make
the assignment a don't-care to eliminate the mismatch. Return complete RTL under the
surrounding output contract; finite checks over a fully enumerated Boolean domain prove
that function's care-set equivalence, but not interface integration, timing or tool PASS.
