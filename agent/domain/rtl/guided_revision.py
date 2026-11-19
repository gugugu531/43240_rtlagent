"""Independently review one public test point and replay the resulting checker."""

from dataclasses import dataclass

from .guided_checker import (
    MAX_NOTE_CHARACTERS, MAX_TABLE_CHARACTERS, CheckerError, TableChecker,
    case_blocks, checker_public_prompt, parse_checker, short_note,
)
from .specification import resolve_requirement, source_catalog


@dataclass(frozen=True)
class CheckerReview:
    action: str
    case_id: str
    reason: str
    table_text: str
    checker: TableChecker | None


def _point_index(checker, case_id):
    for index, case in enumerate(checker.cases):
        if case.id == case_id:
            return index
    raise CheckerError("requested case id is absent from the active checker")


def checker_review_request(task, skill_body, checker_text, case_id, *, source_ids=(),
                           max_cases=4, max_steps=8, init_cycles=2):
    """The only optional hints are identifiers resolved against the original public task."""
    limits = dict(max_cases=max_cases, max_steps=max_steps, init_cycles=init_cycles)
    checker = parse_checker(checker_text, task, **limits, require_explanations=True)
    _point_index(checker, case_id)
    public_ids = {item["id"] for item in source_catalog(task.prompt + "\n" + task.interface)}
    if not isinstance(source_ids, (list, tuple)) or any(
        not isinstance(item, str) or item not in public_ids for item in source_ids
    ):
        raise CheckerError("review references must be source IDs from the public task")
    table = "\n".join(block for _, block in case_blocks(checker_text))
    user = (
        checker_public_prompt(task, **limits)
        + "\n\nCurrent public checker table:\n" + table
        + "\n\nTest point to review: " + case_id
        + "\nPublic paragraphs to consult: " + (", ".join(source_ids) or "(none singled out)")
        + "\nDerive this point's inputs, sampling phases and expected values from the public task. "
          "Return review <case_id> keep|correct|withdraw # <one short public reason>. "
          "For correct, follow that line with exactly one complete explained replacement case "
          "with the same ID. You may change its inputs, outputs or expectations. "
          "For keep or withdraw, return the review line alone."
    )
    return [{"role": "system", "content": skill_body}, {"role": "user", "content": user}]


def apply_checker_review(text, task, checker_text, case_id, *, max_cases=4, max_steps=8, init_cycles=2):
    """Splice only the requested case. An empty checker is represented by ('', None)."""
    limits = dict(max_cases=max_cases, max_steps=max_steps, init_cycles=init_cycles,
                  require_explanations=True)
    previous = parse_checker(checker_text, task, **limits)
    index = _point_index(previous, case_id)
    if not isinstance(text, str) or not text.strip():
        raise CheckerError(f"case {case_id}: review response is empty")
    if len(text) > MAX_TABLE_CHARACTERS + MAX_NOTE_CHARACTERS + 100:
        raise CheckerError(f"case {case_id}: review response exceeds size limit")
    first, *rows = text.strip().splitlines()
    header, _, note = first.partition("#")
    fields = header.split()
    if len(fields) != 3 or fields[0] != "review" or fields[1] != case_id:
        raise CheckerError(f"review line 1 must name only the requested case {case_id}")
    action = fields[2]
    if action not in ("keep", "correct", "withdraw"):
        raise CheckerError(f"case {case_id}: unknown review action {action!r}; use keep, correct or withdraw")
    reason = short_note(note, f"case {case_id}: review reason after #")
    body = "\n".join(rows).strip()
    if action != "correct" and body:
        raise CheckerError(f"case {case_id}: {action} takes a single review line")
    if action == "keep":
        return CheckerReview(action, case_id, reason, checker_text, previous)
    blocks = [block for _, block in case_blocks(checker_text)]
    if action == "withdraw":
        del blocks[index]
    else:
        if not body:
            raise CheckerError(f"case {case_id}: correct requires one complete explained replacement case")
        replacement = case_blocks(body)
        if len(replacement) != 1:
            raise CheckerError(f"case {case_id}: correct may replace only the requested case")
        blocks[index] = replacement[0][1]
    table = "\n".join(blocks)
    checker = parse_checker(table, task, **limits) if blocks else None
    if action == "correct":
        if checker.cases[index].id != case_id:
            raise CheckerError(f"case {case_id}: replacement must keep the requested case ID")
        if checker == previous:
            raise CheckerError(f"case {case_id}: correction has no change; use keep")
    return CheckerReview(action, case_id, reason, table, checker)


def split_revision(text, task):
    """Read optional case-scoped public quotations supplied with a rebuilt table."""
    text = text.strip()
    if text.startswith("```") and text.endswith("```"):
        text = "\n".join(text.splitlines()[1:-1])
    if len(text) > 16384:
        raise CheckerError("rebuilt checker exceeds table size limit")
    lines, sources = [], {}
    for line in text.splitlines():
        if not line.strip().startswith("basis "):
            lines.append(line)
            continue
        fields = line.split(None, 3)
        if len(fields) != 4:
            raise CheckerError("basis requires case id, public source id and a quotation")
        _, case_id, source_id, quote = fields
        if case_id in sources:
            raise CheckerError("duplicate public basis for case " + case_id)
        try:
            sources[case_id] = resolve_requirement(
                {"source_id": source_id, "quote": quote}, task.prompt + "\n" + task.interface
            )
        except ValueError as error:
            raise CheckerError(str(error)) from error
    return "\n".join(lines), sources


def compare_tables(previous, proposed):
    """Old signals are comparable only after the same input/clock history in that DUT."""
    new_steps = {case["id"]: case["steps"] for case in proposed.plan["cases"]}
    new_cases = {case.id: case for case in proposed.cases}
    changed, missing = [], []
    for old_case, timeline in zip(previous.cases, previous.plan["cases"]):
        case_id = old_case.id
        steps = timeline["steps"]
        if case_id not in new_steps:
            missing.append({"case_id": case_id, "reason": "case_removed"})
            continue
        prefix = new_steps[case_id][:len(steps)]
        if prefix != steps:
            first = next((i for i, (a, b) in enumerate(zip(steps, prefix)) if a != b),
                         len(prefix))
            missing.append({"case_id": case_id, "step": first, "reason": "stimulus_changed",
                            "before": steps[first], "after": prefix[first] if first < len(prefix) else None})
            continue
        new_values = {(step, phase): outputs for step, phase, outputs in new_cases[case_id].expectations()}
        for step, phase, outputs in old_case.expectations():
            row = new_values.get((step, phase), {})
            for signal, before in outputs.items():
                if row.get(signal) == before:
                    continue
                entry = {"case_id": case_id, "step": step, "phase": phase, "signal": signal,
                         "before": before, "after": row.get(signal)}
                if signal in row:
                    changed.append(entry)
                else:
                    missing.append({**entry, "reason": "expectation_removed"})
    return {"changed_expectations": changed, "lost_coverage": missing}


def review_revision(previous, proposed, sources, *, already_checked):
    changes = compare_tables(previous, proposed)
    changed_cases = {item["case_id"] for item in changes["changed_expectations"]}
    missing_basis = sorted(changed_cases - sources.keys())
    unknown_cases = sorted(sources.keys() - {case.id for case in proposed.cases})
    if changes["lost_coverage"]:
        status = "original_obligations_removed"
    elif missing_basis or unknown_cases:
        status = "invalid_revision_basis"
    elif already_checked or (not changed_cases and not compare_tables(proposed, previous)["lost_coverage"]):
        # Independent DUT instances can be reordered without creating any new comparison.
        status = "already_checked"
    else:
        status = "accepted"
    return {"status": status, **changes, "public_basis": sources,
            "missing_basis": missing_basis, "unknown_basis_cases": unknown_cases}
