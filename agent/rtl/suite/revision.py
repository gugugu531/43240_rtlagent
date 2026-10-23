"""Revision contracts preserve old stimuli and effective comparison domains."""

from .schema import validate_suite
from .semantics import SuiteError
from agent.rtl.identity import suite_hash
from .evaluate import expected_traces


def validate_revision(previous, revised, revision):
    """Retain every old stimulus and permit only named behavior-expression edits."""
    old, new = validate_suite(previous), validate_suite(revised)
    if (
        revision.get("kind") != "specification_revision"
        or revision.get("origin") != "code_aware_diagnosis"
        or set(revision) != {"kind", "origin", "quote", "target", "names"}
    ):
        raise SuiteError(
            "checker revision must use the fixed specification-only request"
        )
    target, names = revision.get("target"), revision.get("names")
    if (
        target not in ("outputs", "state_next", "async_reset_values")
        or not isinstance(names, list)
        or not names
    ):
        raise SuiteError("checker revision target or names are invalid")
    if any(not isinstance(name, str) for name in names) or len(set(names)) != len(
        names
    ):
        raise SuiteError("checker revision names must be unique strings")
    allowed = old["outputs"] if target == "outputs" else old["state"]
    if not set(names).issubset(allowed):
        raise SuiteError("checker revision must name existing model signals")
    ports = lambda suite: {
        n: (p["direction"], p["width"], p.get("signed", False))
        for n, p in suite["ports"].items()
    }
    if (
        ports(old) != ports(new)
        or old.get("clock") != new.get("clock")
        or old.get("clocks") != new.get("clocks")
        or old["mode"] != new["mode"]
    ):
        raise SuiteError("checker revision cannot change ports, clock or mode")
    steps = lambda case: [
        {
            "inputs": s["inputs"],
            "edge": s.get("edge", True),
            "sample": s.get("sample", True),
            "edges": s.get("edges"),
        }
        for s in case["steps"]
    ]
    new_cases = {case["id"]: case for case in new["cases"]}
    for case in old["cases"]:
        if case["id"] not in new_cases or steps(case) != steps(new_cases[case["id"]]):
            raise SuiteError(
                "checker revision must preserve every old case, input, edge and sample"
            )
    old_requirements = {r["id"]: r["quote"] for r in old["requirements"]}
    new_requirements = {r["id"]: r["quote"] for r in new["requirements"]}
    if any(
        new_requirements.get(name) != quote for name, quote in old_requirements.items()
    ):
        raise SuiteError(
            "checker revision cannot remove or alter existing requirement quotations"
        )
    if set(old["state"]) != set(new["state"]):
        raise SuiteError("checker revision cannot add or remove model state")
    if any(
        old.get(key, {}) != new.get(key, {}) for key in ("output_valid", "output_masks")
    ):
        raise SuiteError("checker revision cannot change output validity or masks")
    if set(old["outputs"]) != set(new["outputs"]):
        raise SuiteError("checker revision cannot change the checked output set")
    changes = []
    for name in old["outputs"]:
        if old["outputs"][name] != new["outputs"][name]:
            if target != "outputs" or name not in names:
                raise SuiteError(
                    "checker revision changed an unapproved output expression"
                )
            changes.append(
                {
                    "path": f"outputs.{name}",
                    "old": old["outputs"][name],
                    "new": new["outputs"][name],
                }
            )
    for name, register in old["state"].items():
        replacement = new["state"][name]
        if {k: v for k, v in register.items() if k != "next"} != {
            k: v for k, v in replacement.items() if k != "next"
        }:
            raise SuiteError(
                "checker revision cannot change state metadata or clock binding"
            )
        if (register["width"], register.get("signed", False)) != (
            replacement["width"],
            replacement.get("signed", False),
        ):
            raise SuiteError(
                "checker revision cannot change state widths or signedness"
            )
        if register["next"] != replacement["next"]:
            if target != "state_next" or name not in names:
                raise SuiteError(
                    "checker revision changed an unapproved state transition"
                )
            changes.append(
                {
                    "path": f"state.{name}.next",
                    "old": register["next"],
                    "new": replacement["next"],
                }
            )
    old_reset, new_reset = old.get("async_reset"), new.get("async_reset")
    if bool(old_reset) != bool(new_reset):
        raise SuiteError("checker revision cannot change the reset sampling contract")
    if old_reset:
        if (old_reset["port"], old_reset["active"]) != (
            new_reset["port"],
            new_reset["active"],
        ):
            raise SuiteError("checker revision cannot change reset binding or polarity")
        for name in old_reset["values"]:
            if old_reset["values"][name] != new_reset["values"][name]:
                if target != "async_reset_values" or name not in names:
                    raise SuiteError(
                        "checker revision changed an unapproved reset value"
                    )
                changes.append(
                    {
                        "path": f"async_reset.values.{name}",
                        "old": old_reset["values"][name],
                        "new": new_reset["values"][name],
                    }
                )
    old_resets, new_resets = old.get("async_resets", []), new.get("async_resets", [])
    if len(old_resets) != len(new_resets):
        raise SuiteError("checker revision cannot change explicit reset contracts")
    for index, (before, after) in enumerate(zip(old_resets, new_resets)):
        if (before["port"], before["active"], set(before["values"])) != (
            after["port"],
            after["active"],
            set(after["values"]),
        ):
            raise SuiteError(
                "checker revision cannot change reset binding, polarity or state subset"
            )
        for name in before["values"]:
            if before["values"][name] != after["values"][name]:
                if target != "async_reset_values" or name not in names:
                    raise SuiteError(
                        "checker revision changed an unapproved reset value"
                    )
                changes.append(
                    {
                        "path": f"async_resets.{index}.values.{name}",
                        "old": before["values"][name],
                        "new": after["values"][name],
                    }
                )
    if not changes:
        raise SuiteError("checker revision made no approved behavior change")
    # A permitted state expression must not indirectly disable a previously
    # required comparison through an unchanged guard or mask expression.
    new_rows = {(row["case_id"], row["step"]): row for row in expected_traces(new)}
    for before in expected_traces(old):
        if not before["sample"]:
            continue
        after = new_rows[before["case_id"], before["step"]]
        for name in before["expected"]:
            full = (1 << old["ports"][name]["width"]) - 1
            if (
                before["valid"][name] is True
                and before["mask_known"][name] == full
                and before["masks"][name]
                and (
                    after["valid"][name] is not True
                    or after["mask_known"][name] != full
                    or before["masks"][name] & ~after["masks"][name]
                )
            ):
                raise SuiteError(
                    "checker revision cannot weaken prior effective output validity or masks"
                )
    for change in changes:
        change["old_suite_hash"] = suite_hash(old)
        change["new_suite_hash"] = suite_hash(new)
    return changes
