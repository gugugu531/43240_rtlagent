## Task

{{ task.prompt }}

## Required top module and public interface evidence

Required top module name: `{{ task.top }}`. Emit this exact name.
Parsed public interface (including source, confidence, completeness and warnings):
{{ task.expected_interface.public_dict() | tojson }}
Unknown widths or incomplete declarations remain unresolved; consult the original public task.
Do not treat embedded buggy RTL as an authoritative interface or invent missing declarations.
{% if task.interface %}
Explicit interface text:
{{ task.interface }}
{% endif %}
If this section is empty, use explicit public interface requirements in the task.
Do not promote declarations in a buggy example or previous candidate to authoritative constraints.
{% if plan and plan.classification is defined %}
## Task classification (host routing only; not a verified design)
{{ plan.classification | tojson }}
Classification is routing metadata, not a chosen implementation; the original task takes precedence.
{% if plan.ambiguities is defined and plan.ambiguities %}
## Unresolved ambiguities (do not invent semantics)
{{ plan.ambiguities | tojson }}
{% endif %}
{% elif plan %}
Design plan (may be incorrect; the original task takes precedence):
{{ plan | tojson }}
{% endif %}
{% if feedback %}
## Previous implementation

```verilog
{{ parent.code if parent else "" }}
```

## Tool feedback

```
{{ feedback }}
```

## Required actions for this round

Apply a stop-and-deliver discipline for this repair:

- First identify the smallest code location and modification that explain the supplied
  feedback while preserving the public behavior.
- Once that local modification is supported by the supplied evidence, stop considering
  alternative architectures unless a new public counterexample shows it is insufficient.
- Implement the change as legal Verilog/SystemVerilog and deliver the complete file. Prefer
  a simple intermediate signal or explicit per-bit condition over syntax whose legality is
  uncertain.
- Do not let unresolved optional matters block delivery. Continue investigating only when an
  uncertainty affects an explicit public requirement, the authoritative interface, or the
  observed failure.

For multiple-driver errors, inspect each reported signal and all of its assignment sites,
including reset branches. A block that writes only once during reset still counts as a driver.
Each state register must have a single clocked writer. If combinational next-state calculation
is needed, use a separate next value with defaults. Keep one combinational writer for a purely
combinational signal. Preserve the specified active edges, reset type, priorities, and cycle
behavior. Do not merely rename variables or delete reset or functional branches to remove errors.
Feedback line numbers, assignment sites, and nearby block headers are lexical navigation aids,
not proof of scope or driver ownership.

1. Distinguish root causes from downstream symptoms: `XSIM 43-3322` is usually only an
   elaboration-failure summary. Check every independent root cause; do not assume an error
   on a second signal is a consequence of the first.
2. Classify the failure:
   - **Interface mismatch**: `interface mismatch` or `cannot find port`.
     Rewrite the module header to match the public interface without changing any port name.
     These failures score zero and must be handled first.
   - **Missing module**: for `Module <X> not found`, compare X with the public top module
     and the reported instance. Rename the top only if its name violates the public task;
     a missing instantiated helper requires its implementation or an instance correction,
     not renaming the correct top module to X.
   - **Syntax error**: `VRFC 10-4982 syntax error`, often caused by a missing module-header
     semicolon, unmatched `begin`/`end`, or an invalid width expression.
   - **Unsynthesizable construct**: locate the cause using the diagnostic text and source,
     not the error number alone. Change only constructs that actually violate synthesis
     requirements, while preserving the behavior specified by the task.
   - **Unintended latch or multiple drivers**: incomplete combinational branches or assignments
     to one signal in two always blocks. Inspect every variable reported by `VRFC 10-3818`,
     including blocks that write only during reset.
   - **Undriven top-level output**: `Synth 8-3848` is a synthesis warning, not a compilation failure.
     Implement missing outputs according to the public task. Do not blindly connect similarly
     named internal signals or arbitrary constants just to suppress a warning.
     Successful compilation or synthesis, or fewer warnings, does not prove functional correctness.
3. **Change only what is necessary.** Do not rewrite previously correct parts and introduce
   new errors. Preserve module and port names, directions, widths, order, and any explicit type
   constraints. A declaration explicitly identified by the public task as faulty may be
   repaired to satisfy that task; do not preserve a known faulty width merely because
   it appears in the previous implementation. If the task does not restrict net versus variable types, your own compiler
   diagnostics may justify correcting a port's variable type (such as reg/logic). This does not
   permit adding, removing, or renaming ports, or changing connections or functionality.
4. If the same error remains unresolved for two consecutive rounds, try a different approach
   instead of continuing small edits at the same location.

Output the complete corrected file in exactly one fenced ```verilog code block, with no text outside it.

{% endif %}
