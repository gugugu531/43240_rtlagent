"""Pure evidence-based repair eligibility and candidate promotion decisions."""

from __future__ import annotations

import hashlib
import json

from agent.rtl.adaptive_assessment import (
    AssessmentError, validate_assessment, bound_details, structural_failures,
)
from agent.rtl.identity import suite_hash
from agent.rtl.observation import sampling_hash, sampling_plan_from_suite
from agent.rtl.properties import property_hash
from agent.rtl.suite.evaluate import expected_traces


def _integer(value, high, name):
    if type(value) is not int or not 0 <= value <= high:
        raise AssessmentError(name + " is outside its explicit bit width or range")
    return value


def _frozen(checker):
    if checker is None or checker.status != "approved" or not checker.repair_authorized:
        raise AssessmentError("functional evidence requires an approved frozen checker")
    payload = checker.payload
    material = {"task_hash": checker.task_hash, "route": checker.route, "checker": payload}
    digest = hashlib.sha256(json.dumps(material, ensure_ascii=False, sort_keys=True,
                                       separators=(",", ":")).encode()).hexdigest()
    if digest != checker.checker_hash or checker.route not in ("model", "properties"):
        raise AssessmentError("approved checker content or route differs from its hash")
    return payload


def check_plan_hash(checker):
    """Hash the fixed neutral sampling plan, independently of candidate execution."""
    payload = _frozen(checker)
    plan = sampling_plan_from_suite(payload) if checker.route == "model" else payload["sampling"]
    return sampling_hash(plan)


def _structure_ok(assessment):
    failures = structural_failures(assessment, require_complete=True)
    structure = assessment["structure"]
    if "observation" in failures:
        raise AssessmentError("child observation compilation has a known RTL code failure")
    for kind in ("lint", "synth"):
        if (structure[kind].get("status") != "passed" or type(structure[kind].get("rc")) is not int
                or structure[kind]["rc"] != 0 or structure[kind].get("failure_kind") in ("environment", "timeout", "checker")):
            raise AssessmentError("child " + kind + " did not pass")
    interface = structure["interface"]
    if interface.get("status") == "passed" and interface.get("rc") != 0:
        raise AssessmentError("passed interface has a nonzero result code")
    if interface.get("status") not in ("passed", "failed", "skipped"):
        raise AssessmentError("child interface check has an execution error")
    if interface.get("status") != "passed" and interface.get("blocking") is True:
        raise AssessmentError("child interface still has a blocking mismatch")
    if interface.get("failure_kind") in ("environment", "timeout", "checker"):
        raise AssessmentError("child interface is unavailable due to a tool/checker error")
    return interface.get("status") != "passed"


MISMATCH_LIMIT = 32


def _model_mismatches(failed, context, limit=MISMATCH_LIMIT):
    """Bound actual failing-bit rows for the repair prompt; never infer them from summaries."""
    rows = []
    for case_id, step, signal, bit in sorted(failed)[:limit]:
        row = context[(case_id, step, signal)]
        mask = 1 << bit
        rows.append({
            "case_id": case_id, "step": step, "signal": signal, "bit": bit,
            "expected_value": 1 if row["expected_bits"][signal] & mask else 0,
            "actual_value": 1 if row["actual_bits"][signal] & mask else 0,
        })
    return rows


def _property_mismatches(failed, context, limit=MISMATCH_LIMIT):
    """Bound failed obligations with the boolean hold values recorded by the checker."""
    rows = []
    for key in sorted(failed)[:limit]:
        observations = context[key].get("observations") or []
        observed = observations[-1].get("value") if observations else None
        rows.append({"property_id": key[0], "case_id": key[1], "trigger_step": key[2],
                     "expected_holds": True,
                     "observed_holds": observed if type(observed) is bool else None})
    return rows


def _model(details, payload):
    if details.get("suite_hash") != suite_hash(payload):
        raise AssessmentError("model result suite_hash differs from frozen checker")
    traces = details.get("traces")
    expected = expected_traces(payload)
    if not isinstance(traces, list) or len(traces) != len(expected):
        raise AssessmentError("model trace is incomplete or has extra events")
    outputs = {name: port["width"] for name, port in payload["ports"].items() if port["direction"] == "output"}
    passed, failed, unknown, excluded, context = set(), set(), set(), set(), {}
    for actual, anticipated in zip(traces, expected):
        if not isinstance(actual, dict):
            raise AssessmentError("model trace row must be an object")
        # Recompute the public checker; persisted expected/mask/valid cannot weaken it.
        for field, value in anticipated.items():
            if json.dumps(actual.get(field), sort_keys=True) != json.dumps(value, sort_keys=True):
                raise AssessmentError("model trace differs from fixed expectation at " + field)
        bits, known = actual.get("actual_bits"), actual.get("actual_known")
        if not isinstance(bits, dict) or not isinstance(known, dict) or set(bits) != set(outputs) or set(known) != set(outputs):
            raise AssessmentError("model trace output bits/known map is incomplete")
        for signal, width in outputs.items():
            full = (1 << width) - 1
            value = _integer(bits[signal], full, "actual bits")
            mask_known = _integer(known[signal], full, "actual known mask")
            if value & ~mask_known:
                raise AssessmentError("unknown actual bits must not be fabricated as known values")
            key = (actual["case_id"], actual["step"], signal)
            context[key] = actual
            for bit in range(width):
                identity = (*key, bit)
                bitmask = 1 << bit
                if not anticipated["sample"] or anticipated["valid"][signal] is False:
                    excluded.add(identity)
                elif anticipated["valid"][signal] is None or anticipated["mask_known"][signal] != full:
                    unknown.add(identity)
                elif not anticipated["masks"][signal] & bitmask:
                    excluded.add(identity)
                elif not anticipated["expected_known"][signal] & mask_known & bitmask:
                    unknown.add(identity)
                elif (anticipated["expected_bits"][signal] ^ value) & bitmask:
                    failed.add(identity)
                else:
                    passed.add(identity)
    if not passed and not failed:
        raise AssessmentError("model evidence has zero actual known comparisons")
    if type(details.get("compared_bits")) is not int or details["compared_bits"] != len(passed) + len(failed):
        raise AssessmentError("model compared_bits summary disagrees with actual bit evidence")
    counterexample = None
    if failed:
        key = sorted(failed)[0]
        row = context[key[:3]]
        counterexample = {**row, "signal": key[2], "failed_bit": key[3],
                          "comparison_mask": 1 << key[3],
                          "expected_bits_value": row["expected_bits"][key[2]],
                          "actual_bits_value": row["actual_bits"][key[2]]}
    return {"passed": passed, "failed": failed, "unknown": unknown, "excluded": excluded,
            "present": passed | failed | unknown | excluded, "counterexample": counterexample,
            "mismatches": _model_mismatches(failed, context)}


def _properties(details, payload):
    if details.get("plan_hash") != sampling_hash(payload["sampling"]) or details.get("property_hash") != property_hash(payload):
        raise AssessmentError("property result plan/property hashes differ from frozen checker")
    properties = {prop["id"]: prop for prop in payload["properties"]}
    results = details.get("per_property")
    if not isinstance(results, list) or len(results) != len(properties):
        raise AssessmentError("property results are incomplete")
    case_events, sampled = {}, {}
    for case in payload["sampling"]["cases"]:
        indices = [index for index, step in enumerate(case["steps"])
                   if not payload["sampling"]["clock"] or step.get("edge", True)]
        case_events[case["id"]] = dict(enumerate(indices))
        sampled[case["id"]] = {index for index, step in enumerate(case["steps"]) if step.get("sample", True)}
    passed, failed, unknown, excluded, present = set(), set(), set(), set(), set()
    seen_properties, context, count_unknown = set(), {}, {}
    for result in results:
        if not isinstance(result, dict) or result.get("property_id") not in properties or result["property_id"] in seen_properties:
            raise AssessmentError("duplicate or unknown property result")
        name = result["property_id"]
        seen_properties.add(name)
        prop = properties[name]
        obligations = result.get("obligations")
        if not isinstance(obligations, list) or len(obligations) > 256:
            raise AssessmentError("property obligations are missing or exceed the plan size")
        counters = dict(satisfied=0, violated=0, unknown=0, incomplete=0, aborted=0)
        for obligation in obligations:
            if not isinstance(obligation, dict):
                raise AssessmentError("property obligation must be an object")
            case, step, tick = obligation.get("case_id"), obligation.get("trigger_step"), obligation.get("trigger_tick")
            if (obligation.get("property_id") != name or case not in case_events
                    or type(tick) is not int or type(step) is not int
                    or case_events[case].get(tick) != step or tick < prop["warmup_ticks"]
                    or step not in sampled[case]
                    or obligation.get("phase") != prop["sample_phase"]):
                raise AssessmentError("obligation trigger does not match its fixed case/phase/tick")
            key = (name, case, step, tick)
            if key in present:
                raise AssessmentError("duplicate property obligation")
            present.add(key)
            context[key] = obligation
            status = obligation.get("status")
            if status not in counters:
                raise AssessmentError("unknown property obligation status")
            counters[status] += 1
            observations = obligation.get("observations")
            if (not isinstance(observations, list) or len(observations) > 17
                    or type(obligation.get("response_evaluations")) is not int
                    or obligation["response_evaluations"] != len(observations)
                    or type(obligation.get("unknown_seen")) is not bool):
                raise AssessmentError("property observation count is inconsistent")
            prior_age = -1
            for observation in observations:
                if not isinstance(observation, dict):
                    raise AssessmentError("property observation must be an object")
                age = observation.get("age")
                if (type(age) is not int or not prop["window"]["min"] <= age <= prop["window"]["max"]
                        or age <= prior_age or case_events[case].get(tick + age) != observation.get("step")
                        or (type(observation.get("value")) is not bool and observation.get("value") is not None)
                        or (type(observation.get("abort")) is not bool and observation.get("abort") is not None)):
                    raise AssessmentError("property response observation is outside its fixed window")
                prior_age = age
            if status == "satisfied":
                if (not observations or observations[-1]["value"] is not True or observations[-1]["abort"] is not False
                        or obligation.get("abort_unknown") is True
                        or obligation.get("end_step") != observations[-1]["step"]):
                    raise AssessmentError("satisfied obligation lacks a known true response")
                passed.add(key)
            elif status == "violated":
                if (not observations or observations[-1]["age"] != prop["window"]["max"]
                        or [item["age"] for item in observations] != list(range(prop["window"]["min"], prop["window"]["max"] + 1))
                        or any(item["value"] is not False or item["abort"] is not False for item in observations)
                        or obligation.get("unknown_seen") is not False
                        or obligation.get("end_step") != observations[-1]["step"]):
                    raise AssessmentError("violated obligation lacks a complete known false window")
                failed.add(key)
            elif status in ("unknown", "incomplete"):
                unknown.add(key)
            else:
                if prop["abort"] is None:
                    raise AssessmentError("obligation abort is absent from the frozen property")
                excluded.add(key)
        if type(result.get("triggered")) is not int or result["triggered"] != len(obligations):
            raise AssessmentError("property trigger count disagrees with its obligations")
        for field in ("satisfied", "violated", "incomplete", "aborted"):
            if type(result.get(field)) is not int or result[field] != counters[field]:
                raise AssessmentError("property count disagrees with obligations: " + field)
        count_unknown[name] = counters["unknown"]
    unknown_triggers = details.get("unknown_triggers")
    if not isinstance(unknown_triggers, list) or len(unknown_triggers) > 1280:
        raise AssessmentError("unknown trigger evidence is missing or oversized")
    seen_unknown = set()
    for item in unknown_triggers:
        if not isinstance(item, dict):
            raise AssessmentError("unknown trigger must be an object")
        name, case, step = item.get("property_id"), item.get("case_id"), item.get("step")
        if name not in properties or case not in case_events or type(step) is not int:
            raise AssessmentError("unknown trigger identity is invalid")
        matches = [tick for tick, index in case_events[case].items() if index == step]
        if (not matches or matches[0] < properties[name]["warmup_ticks"]
                or step not in sampled[case]
                or item.get("phase") != properties[name]["sample_phase"]):
            raise AssessmentError("unknown trigger is outside the fixed property domain")
        key = (name, case, step, matches[0])
        if key in seen_unknown or key in present:
            raise AssessmentError("duplicate or conflicting unknown trigger")
        seen_unknown.add(key)
        count_unknown[name] += 1
        unknown.add(key)
    for result in results:
        if type(result.get("unknown")) is not int or result["unknown"] != count_unknown[result["property_id"]]:
            raise AssessmentError("property unknown count disagrees with evidence")
    return {"passed": passed, "failed": failed, "unknown": unknown, "excluded": excluded,
            "present": present, "counterexample": context[sorted(failed)[0]] if failed else None,
            "mismatches": _property_mismatches(failed, context)}


def _behavior(assessment, checker):
    payload = _frozen(checker)
    if (assessment.get("checker_hash") != checker.checker_hash
            or assessment.get("check_plan_hash") != check_plan_hash(checker)):
        raise AssessmentError("assessment checker/plan differs from frozen checker")
    behavior = assessment.get("behavior")
    if not isinstance(behavior, dict) or behavior.get("route") != checker.route:
        raise AssessmentError("behavior route differs from frozen checker")
    details = bound_details(behavior, assessment, behavior=True)
    if behavior.get("status") not in ("passed", "failed", "unknown", "untested", "error"):
        raise AssessmentError("behavior execution did not complete")
    if behavior.get("failure_kind") in ("checker", "environment", "timeout"):
        raise AssessmentError("behavior failure is not a complete DUT comparison")
    if details.get("plan_hash") != assessment["check_plan_hash"]:
        raise AssessmentError("behavior execution sampling plan differs from assessment")
    normalized = (_model if checker.route == "model" else _properties)(details, payload)
    normalized["execution_id"] = details["execution_id"]
    return normalized


def _has_behavior(assessment):
    behavior = assessment.get("behavior")
    if not isinstance(behavior, dict) or not isinstance(behavior.get("details"), dict):
        return False
    details = behavior["details"]
    return bool(details.get("traces") or details.get("per_property"))


def repair_opportunity(assessment, checker=None):
    """Return a reliable repair trigger, or None; never infer one from a summary."""
    try:
        validate_assessment(assessment)
        failures = structural_failures(assessment)
        if failures:
            kind = next(name for name in ("interface", "lint", "observation", "synth") if name in failures)
            if kind == "observation":
                _frozen(checker)
                if (assessment.get("checker_hash") != checker.checker_hash
                        or assessment.get("check_plan_hash") != check_plan_hash(checker)):
                    raise AssessmentError("observation error is not bound to the approved public checker")
            return {"kind": "structure", "check": kind, "failure": assessment["structure"][kind]}
        if not _has_behavior(assessment):
            return None
        facts = _behavior(assessment, checker)
        if facts["failed"]:
            return {"kind": "behavior", "route": checker.route,
                    "counterexample": facts["counterexample"],
                    "failed_mismatches": facts["mismatches"],
                    "failed": len(facts["failed"]), "passed": len(facts["passed"]),
                    "unknown": len(facts["unknown"])}
    except (ValueError, TypeError, KeyError, AttributeError, RecursionError):
        return None
    return None


def promotion_decision(parent, child, *, repair_kind, checker=None):
    """Promote only a bound, changed child with non-regressing completed evidence."""
    evidence, improved = {}, []
    try:
        if repair_kind not in ("structure", "behavior"):
            raise AssessmentError("repair_kind must be structure or behavior")
        validate_assessment(parent)
        validate_assessment(child)
        if child.get("parent_id") != parent["candidate_id"] or child.get("parent_hash") != parent["candidate_hash"]:
            raise AssessmentError("child lineage does not bind the actual parent candidate")
        if child["candidate_id"] == parent["candidate_id"] or child["candidate_hash"] == parent["candidate_hash"]:
            raise AssessmentError("repair did not create a changed candidate")
        if child["execution_id"] == parent["execution_id"]:
            raise AssessmentError("child assessment reused parent execution identity")
        if child["checker_implementation_hash"] != parent["checker_implementation_hash"]:
            raise AssessmentError("checker implementation changed between parent and child")
        if checker is not None:
            _frozen(checker)
            for assessment in (parent, child):
                if (assessment.get("checker_hash") != checker.checker_hash
                        or assessment.get("check_plan_hash") != check_plan_hash(checker)):
                    raise AssessmentError("parent/child checker or sampling plan differs from frozen checker")
        failures = structural_failures(parent)
        evidence["interface_unverified"] = _structure_ok(child)
        for kind, result in parent["structure"].items():
            if result["details"]["execution_id"] == child["structure"][kind]["details"]["execution_id"]:
                raise AssessmentError("child reused the parent " + kind + " execution")
            if result.get("status") == "passed" and child["structure"][kind].get("status") != "passed":
                raise AssessmentError("previously passed " + kind + " is no longer verified")
        old_executions = {result["details"]["execution_id"] for result in parent["structure"].values()}
        new_executions = {result["details"]["execution_id"] for result in child["structure"].values()}
        for assessment, executions in ((parent, old_executions), (child, new_executions)):
            behavior = assessment.get("behavior")
            if isinstance(behavior, dict) and isinstance(behavior.get("details"), dict) and behavior["details"].get("execution_id"):
                identity = behavior["details"]["execution_id"]
                if identity in executions:
                    observation = assessment["structure"].get("observation", {})
                    if observation.get("details", {}).get("execution_id") != identity:
                        raise AssessmentError("behavior execution reused an unrelated structure execution identity")
                    # Observation and interpretation describe the same actual sample run.
                    # A second invented UUID would incorrectly imply another execution.
                    alias = observation["details"].get("sampling_execution_id", identity)
                    if alias != identity:
                        raise AssessmentError("observation sampling execution alias is inconsistent")
                executions.add(identity)
        if old_executions & new_executions:
            raise AssessmentError("child reused an execution from a parent check")
        if repair_kind == "structure":
            if not failures:
                raise AssessmentError("parent has no explicit blocking RTL structure error")
            if any(child["structure"][kind].get("status") != "passed" for kind in failures):
                raise AssessmentError("child did not remove every known structural code failure")
            improved = ["structure:" + kind for kind in failures]
        if repair_kind == "behavior" or _has_behavior(parent):
            old, new = _behavior(parent, checker), _behavior(child, checker)
            if old["execution_id"] == new["execution_id"]:
                raise AssessmentError("child reused the parent behavioral execution")
            if old["present"] - new["present"]:
                raise AssessmentError("old sampled bits or triggered obligations disappeared")
            if old["passed"] - new["passed"]:
                raise AssessmentError("child did not preserve every previously passed bit/obligation")
            if new["failed"] - old["failed"]:
                raise AssessmentError("child introduced new failing bits/obligations")
            if new["unknown"] - old["unknown"]:
                raise AssessmentError("child introduced new unknown or incomplete evidence")
            resolved = old["failed"] & new["passed"]
            if old["failed"] - new["failed"] - resolved:
                raise AssessmentError("an old failure became skipped, aborted or unknown instead of passing")
            if repair_kind == "behavior" and not resolved:
                raise AssessmentError("child did not resolve any prior actual behavioral failure")
            improved.extend([list(key) for key in sorted(resolved)])
            evidence.update({
                "parent_failed": len(old["failed"]), "child_failed": len(new["failed"]),
                "parent_passed": len(old["passed"]), "child_passed": len(new["passed"]),
                "parent_unknown": len(old["unknown"]), "child_unknown": len(new["unknown"]),
                "resolved_behavior_failures": len(resolved), "functional_evidence_compared": True,
            })
        else:
            evidence["functional_evidence_compared"] = False
            evidence["functional_status"] = "unverified"
            if _has_behavior(child) and checker is not None:
                new = _behavior(child, checker)
                evidence.update(child_failed=len(new["failed"]), child_passed=len(new["passed"]),
                                child_unknown=len(new["unknown"]), functional_status="newly_observed_without_parent_comparison")
        return {"allowed": True, "reason": "changed child improves the diagnosed error without evidence regression",
                "improved": improved, "evidence": evidence}
    except (ValueError, TypeError, KeyError, AttributeError, RecursionError) as error:
        return {"allowed": False, "reason": str(error)[:4000], "improved": [], "evidence": evidence}
