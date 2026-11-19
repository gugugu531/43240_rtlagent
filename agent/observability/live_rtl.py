"""Public RTL evidence for the live viewer, independent of full recording."""

import re

from .live import fields


_CHECK_NAMES = {"interface": "接口检查", "lint": "编译与展开", "synth": "综合"}
_VERDICT_ID = ("candidate_id", "candidate_hash", "checker_hash", "checker_version")
_BINDING = (*_VERDICT_ID, "sampling_plan_hash", "execution_id")
_COUNTS = ("checked_outputs", "unchecked_outputs", "compared_bits", "unknown_bits",
           "compared_bits_by_phase", "unknown_bits_by_phase")
_HISTORY = ("role", "stage", "round", "action", "reason", "case_id", "candidate_id", "candidate_hash",
            "child_id", "child_hash", "changed", "checked", "outcome", "checker_hash",
            "review_action", "review_reason", "reviewed_checker_hash", "source_call_id")


def comparison_status(data, *, identified):
    status = data.get("status", "unknown")
    if status in ("passed", "partial_passed"):
        bits = data.get("compared_bits")
        if type(bits) is not int or bits <= 0:
            return "unknown"
        if not identified:
            return "unverified"
    return status


def sampling_summary(value):
    summary = value.get("summary", "")
    # A failing Vivado stage appends raw stdout after this heading.
    stage = re.match(r"observation stage \d+ failed:", summary)
    return stage.group().rstrip(":") if stage else summary


class RtlEvidence:
    # Keys are registered implementations, so aliases and workflow upgrades
    # continue to use the actual graph emitted by Burr.
    node_titles = {
        "guided_initialize": ("初始化", "运行框架"),
        "guided_plan": ("制定验证策略", "策略分析员"),
        "guided_solve": ("编写 RTL", "RTL 作者"),
        "guided_structure": ("检查 RTL 结构", "验证工具"),
        "guided_repair_structure": ("修复结构问题", "RTL 作者"),
        "guided_build_checker": ("编写独立检查表", "检查员"),
        "guided_run_checker": ("运行检查表", "验证工具"),
        "guided_author_decision": ("决定提交、改稿或复核", "RTL 作者"),
        "guided_checker_review": ("复核测试点", "检查员"),
        "guided_finish": ("汇总交付", "运行框架"),
        "baseline_generate": ("生成 RTL", "RTL 作者"),
        "rtl_generate": ("生成 RTL", "RTL 作者"),
        "baseline_extract": ("提取候选 RTL", "运行框架"),
        "select": ("选择候选 RTL", "运行框架"),
        "finish": ("结束运行", "运行框架"),
    }

    def __init__(self, detail):
        self.detail = detail
        self.table_hash = None
        self.cases = {}
        self.observation = None
        self.outcomes = {}
        self.request_notices = {}

    def event(self, tool, event, row):
        if tool == "candidate" and event in ("create", "change"):
            label = "候选身份" if event == "create" else "父子候选差异"
            self.detail(label, fields(row, "candidate_id", "code_hash", "source_stage", "source_call_id",
                                      "parent_id", "round", "extraction_status", "code_bytes",
                                      "changed", "added_lines", "removed_lines"))
        elif (tool, event) == ("select", "result"):
            self.detail("已选候选", fields(row, "candidate_id", "code_hash", "reason"))
        elif (tool, event) == ("extract", "result"):
            self.detail("RTL 提取", fields(row, "candidate_id", "source_call_id", "status", "empty_content",
                                       "complete_new_draft", "finish_reason", "diagnostics", "retained_candidate_id"))
        elif tool == "submission" and event in ("decision", "finalized"):
            label = "提交决定" if event == "decision" else "最终交付"
            self.detail(label, fields(row, "mode", "candidate_id", "target_id", "selected_id", "code_hash",
                                      "published", "delivery", "reason", "fallback_basis", "structure_status"))
        elif (tool, event) == ("guided", "verification"):
            data = fields(
                row, *_BINDING, "method", "submission_mode", "structural_passed", "toolchain_passed",
                "interface_verified", "behavior_status", "compared_bits", "functional_passed",
                "current_table_passed", "expectations_revised", "withdrawn_cases", "checker_disputed",
                "submitted_with_mismatch", "unresolved_reviews",
            )
            verdict = row.get("behavior_status") or "not_run"
            if verdict in ("passed", "partial_passed"):
                identity = tuple(row.get(key) for key in _VERDICT_ID)
                if self.outcomes.get(identity) != verdict:
                    verdict = "unverified"
            data["behavior_status"] = verdict
            if verdict not in ("passed", "failed"):
                data.update(current_table_passed=None, functional_passed=None)
            self.detail("交付候选的验证结果", data)
        elif (tool, event) == ("knowledge", "skills"):
            self.detail("选用的技能", fields(row, "mode", "phase", "selected", "sent", "rejected"))

    def artifact(self, name, value):
        if name == "plan":
            self.detail("验证策略与所选技能", fields(value, "method", "skills", "knowledge", "focus", "reason"))
        elif name == "plan-capability":
            self.detail("检查表适用性", fields(value, "requested", "plan_source", "table_supported", "reason"))
        elif name == "material" or name.startswith("material-"):
            self.detail("本次请求采用的技能", fields(value, "phase", "sent", "cards_sent", "rejected"))
        elif name == "decision-history" and value:
            note = fields(value[-1], *_HISTORY)
            self.detail("检查员复核决定" if note.get("role") == "checker" else "作者决定", note)
        elif name == "checker":
            self.checker(value)
        elif name == "request-outcomes" and value:
            stage = next(reversed(value))
            outcome = value[stage]
            if outcome.get("status") in ("not_sent", "error"):
                notice = {"stage": stage, **fields(outcome, "status", "reason", "kind", "call_id")}
                if self.request_notices.get(stage) != notice:
                    self.detail("请求未取得结果", notice, status=notice["status"])
                    self.request_notices[stage] = notice
        elif name in ("plan-error", "checker-error", "checker-build") or name.endswith("-failure"):
            self.detail("阶段结果", fields(value, "status", "stage", "kind", "reason", "source_call_id",
                                      "finish_reason", "checker_hash"), status=value.get("status") or value.get("kind"))
        else:
            match = re.fullmatch(r"assessments/(c[0-9]+)/(interface|lint|synth|assessment|observations|behavior)", name)
            if match:
                self.assessment(match[1], match[2], value)

    def checker(self, value):
        self.table_hash = value.get("checker_hash")
        plan = value.get("plan") or {}
        stimuli = {case["id"]: case["steps"] for case in plan.get("cases", [])}
        self.cases = {}
        self.detail("独立检查表", {
            **fields(value, "status", "checker_hash", "schema_version", "checked_outputs", "unchecked_outputs"),
            **fields(plan, "clock", "ports"), "case_count": len(value.get("cases", [])),
        }, status=value.get("status"))
        for case in value.get("cases", []):
            data = fields(case, "id", "explanation", "init_count", "checked_outputs", "unchecked_outputs",
                          "expected", "pre_expected")
            data.update(checker_hash=self.table_hash, steps=stimuli.get(case["id"], []))
            self.cases[case["id"]] = data
            self.detail("测试点 · " + case["id"], data)

    def assessment(self, candidate_id, stage, value):
        if stage in _CHECK_NAMES:
            details = value.get("details") or {}
            status = value["status"]
            if status == "passed" and (type(value.get("rc")) is not int or value["rc"] != 0):
                status = "unverified"
            data = {**fields(value, "id", "kind", "candidate_id", "blocking", "elapsed_s", "rc", "failure_kind"),
                    **fields(details, "candidate_hash", "checker_hash", "tool_version", "differences", "warnings",
                             "expected_module", "actual_module", "parse_error_scope", "synthesis_hints"),
                    "status": status}
            diagnostics = details.get("repair_diagnostics") or {}
            if diagnostics:
                public = fields(diagnostics, "complete", "omitted", "truncated")
                for key in ("items", "root_errors"):
                    if key in diagnostics:
                        public[key] = [fields(item, "code", "severity", "message", "line_number", "symbols",
                                              "message_truncated", "cascade") for item in diagnostics[key]]
                data["diagnostics"] = public
            excerpt = value.get("excerpt", "")
            if stage == "interface" or "\n" not in excerpt:
                data["summary"] = excerpt
            self.detail(_CHECK_NAMES[stage] + " · " + candidate_id, data, status=status)
        elif stage == "assessment":
            self.detail("结构检查汇总", {
                **fields(value, "candidate_id", "candidate_hash", "code_failed", "structural_passed",
                         "toolchain_passed", "interface_verified"),
                "not_run": [stage for stage in _CHECK_NAMES if stage not in value["checks"]],
            })
        elif stage == "observations":
            self.observation = fields(value, "candidate_hash", "plan_hash", "execution_id", "rows", "status")
            self.detail("采样结果", {
                **fields(value, "candidate_hash", "plan_hash", "execution_id", "status", "failure_kind",
                         "elapsed_s", "rc"), "summary": sampling_summary(value),
                "sample_rows": len(value.get("rows", [])),
            }, status=value.get("status"))
        elif stage == "behavior":
            self.behavior(candidate_id, value)

    def behavior(self, candidate_id, value):
        binding = fields(value, *_BINDING)
        observation, self.observation = self.observation or {}, None
        cases = self.cases if self.table_hash and self.table_hash == binding.get("checker_hash") else {}
        samples = {}
        # A repeated node may receive the same RTL with a new table or run. Only
        # show samples associated with this exact execution and sampling plan.
        same_execution = (
            binding.get("candidate_id") == candidate_id and binding.get("checker_version")
            and observation.get("status") == "complete"
            and all(observation.get(src) and observation[src] == binding.get(dst) for src, dst in (
                ("candidate_hash", "candidate_hash"), ("plan_hash", "sampling_plan_hash"), ("execution_id", "execution_id"),
            ))
        )
        if cases and same_execution:
            samples = {(r["case_id"], r["step"], r["phase"]): r["values"] for r in observation.get("rows", [])}
        results = value.get("case_results", [])
        status = comparison_status(value, identified=bool(samples and results))
        self.outcomes[tuple(binding.get(key) for key in _VERDICT_ID)] = status
        self.detail("行为比对汇总", {**binding, **fields(value, *_COUNTS, "failure_kind"),
                                   "summary": sampling_summary(value), "status": status}, status=status)
        executed = set()
        for result in results:
            case_id = result["case_id"]
            executed.add(case_id)
            data = {**binding, **fields(result, "case_id", "explanation", *_COUNTS, "mismatches"),
                    "failed": [r for r in value.get("failed", []) if r["case_id"] == case_id],
                    "unknown": [r for r in value.get("unknown", []) if r["case_id"] == case_id]}
            comparisons = []
            for field, phase in (("pre_expected", "pre"), ("expected", "post")):
                for step, expected in cases.get(case_id, {}).get(field, {}).items():
                    measured = samples.get((case_id, int(step), phase))
                    if measured is not None:
                        comparisons.append({"step": int(step), "phase": phase, "expected": expected,
                                            "actual": {name: measured[name] for name in expected if name in measured}})
            if comparisons:
                data["comparisons"] = sorted(comparisons, key=lambda row: (row["step"], row["phase"] == "post"))
            case_status = comparison_status(result, identified=bool(comparisons))
            data["status"] = case_status
            self.detail("测试点比对 · " + case_id, data, status=case_status)
        for case_id, case in cases.items():
            if case_id not in executed:
                self.detail("测试点比对 · " + case_id, {
                    **binding, "case_id": case_id, "explanation": case.get("explanation"),
                    "status": "not_run", "execution_status": status,
                }, status="not_run")
