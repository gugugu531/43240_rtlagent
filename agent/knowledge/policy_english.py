"""English translations of reviewed missing-fact descriptions, keyed by stable card ID.

Descriptions are documentation, not executable predicates. Missing evidence still rejects.
"""

MISSING_FACTS = {
    'repair-local-syntax': 'Feedback does not explain an unclosed preceding statement, delimiter, or begin/end relationship.',
    'repair-undeclared-identifier': 'Feedback does not distinguish misspelling, a missing declaration, scope, or conditional compilation.',
    'repair-multiple-drivers': 'Feedback does not explain all driver sources and the single ownership that should be retained.',
    'semantic-rotate-versus-shift': 'Feedback gives only a boundary mismatch without explaining whether shifted-out bits should be discarded, filled, or wrapped.',
    'semantic-reset-contract': 'At least one of reset synchrony, polarity, target value, or priority remains unspecified.',
    'semantic-combinational-completeness': 'Feedback identifies a reachable branch retaining an old value but does not explain the distinction between a combinational default and sequential hold.',
    'repair-sequential-event-control': 'Feedback does not provide a valid single-clock method with reset synchrony, polarity, and priority.',
    'semantic-selection-shape': 'Object dimensions, legal indices, or the target bit order remain unclear.',
    'repair-index-and-part-select': 'Feedback identifies a direction or range error but does not provide a method that preserves bit order and target width.',
    'repair-module-and-top-resolution': 'The candidate does not contain a uniquely identifiable correct module declaration or compilation input.',
    'semantic-declaration-lifecycle': 'Feedback has not distinguished a missing declaration, use before declaration, redeclaration, or valid shadowing.',
    'repair-duplicate-and-implicit-declaration': 'Feedback does not explain which declaration to retain or where the first use occurs.',
    'semantic-elaboration-constant': 'Feedback does not distinguish elaboration constants, runtime objects, and dynamic bit selection.',
    'repair-generate-loop-index': 'Feedback does not distinguish a generate elaboration loop from a procedural runtime loop.',
    'semantic-enum-encoding': 'Feedback does not provide the complete expanded enum values, base-type width, and external encoding contract.',
    'semantic-module-compilation-scope': 'Feedback does not explain module/endmodule boundaries and the intended parent module of objects outside modules.',
    'repair-explicit-declaration-type': 'Feedback does not explain driver ownership, range, signedness, or the required net/variable type.',
}
