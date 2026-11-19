"""Self-authored node integration checks for guided prompt context wiring."""

import copy
from contextlib import contextmanager, nullcontext
from tempfile import TemporaryDirectory
from pathlib import Path
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from agent.context.prompts import TemplateRenderer
from agent.domain.rtl.candidate import CandidateStore
from agent.llm.types import ModelError, Reply
from agent.runtime.allowance import CompletionLedger
from agent.submission.gateway import SubmissionGateway
from agent.domain.rtl.guided_checker import parse_checker
from agent.domain.rtl.result import CheckResult
from agent.domain.rtl.task import TaskSpec
from agent.kit import State
from agent.orchestration.nodes import guided
from agent.orchestration.workflows.guided_verify import GuidedParameters


TABLE = "case reset # Reset clears q and the first active edge captures d.\ninit reset=1 d=0 q=0\nstep reset=0 d=1 q=1\n"
PROMPT = "On each positive edge of clk, reset sets q to zero; otherwise q takes d."
INTERFACE = "module TopModule(input clk, input reset, input d, output q);"


class MemoryRecord:
    def __init__(self):
        self.artifacts = {}

    def write_text(self, name, value):
        self.artifacts[name] = value
        return name

    def span(self, *args, **kwargs):
        return nullcontext()

    def emit(self, *args, **kwargs):
        pass

    def write_json(self, name, value):
        self.artifacts[name] = copy.deepcopy(value)
        return name


class GuidedContextFlowTests(unittest.TestCase):
    def context(self, *, prompt=PROMPT):
        task = TaskSpec.from_text("self-authored-context", prompt, INTERFACE)
        candidate = SimpleNamespace(
            id="candidate-current", code_hash="CURRENT_CANDIDATE_HASH",
            code="module TopModule; /* PRIVATE_CANDIDATE */ endmodule",
        )
        settings = GuidedParameters(max_cases=3, max_steps_per_case=5,
                                    init_cycles=3, knowledge_select=0).model_dump()
        ctx = SimpleNamespace(
            task=task, store={}, record=MemoryRecord(), budget=SimpleNamespace(remaining=lambda: 840),
            prompts=TemplateRenderer(), candidates=SimpleNamespace(get=lambda _: candidate),
        )
        guided.initialize(ctx, State({"settings": settings}))
        ctx.store["guided"].update(
            plan={"skills": [], "knowledge": [], "focus": ["reset"]}, plan_source="planner",
            skill_assets={"skills": {"rtl-behavior-check-keycases": (None, "Write a test table.")},
                         "resources": {}},
        )
        return ctx

    def test_structure_repair_receives_root_diagnostics_after_warning_flood(self):
        ctx = self.context()
        data = ctx.store["guided"]
        warnings = "WARNING: unrelated declaration\n" * 200
        root_error = "ERROR: [VRFC 10-4982] syntax error near broken_token"
        diagnostics = {"root_errors": [{"message": root_error, "line": 91}]}
        data["assessments"]["candidate-current"] = {"checks": {
            "lint": {"status": "failed", "failure_kind": "code", "rc": 1,
                     "excerpt": warnings[:2000],
                     "details": {"repair_diagnostics": diagnostics}},
        }}
        with patch.object(guided, "_request", return_value=None) as request:
            guided.repair_structure(ctx, State({"target_id": "candidate-current"}))
        messages = request.call_args.args[2]
        body = messages[-1]["content"]
        self.assertNotIn(root_error, warnings[:2000])
        self.assertIn(root_error, body)
        self.assertIn(json.dumps(diagnostics), body)
        self.assertIn('"candidate_hash": "CURRENT_CANDIDATE_HASH"', body)
        self.assertIn('"candidate_id": "candidate-current"', body)
        self.assertIn("PRIVATE_CANDIDATE", body)

    def test_build_checker_sends_effective_limits_and_uses_same_init_count(self):
        ctx = self.context()
        reply = SimpleNamespace(content=TABLE, call_id="checker-call", finish_reason="stop")
        with patch.object(guided, "_request", return_value=reply) as request:
            state = guided.build_checker(ctx, State())
        self.assertEqual(state["checker_status"], "valid")
        body = request.call_args.args[2][-1]["content"]
        self.assertIn('"configured_limits":{"max_cases":3,"max_steps":5,"init_cycles":3}', body)
        self.assertIn('"max_table_lines_per_case":5', body)
        self.assertIn('"init_repeats":3', body)
        checker = ctx.store["guided"]["checker"]
        self.assertEqual(checker.cases[0].init_count, 3)
        self.assertEqual(set(checker.cases[0].expected), {2, 3})
        self.assertEqual(len(checker.plan["cases"][0]["steps"]), 4)

    def test_unsupported_table_retains_planner_intent_and_skills(self):
        ctx = self.context(prompt="On each negative edge of clk, q takes d.")
        reply = SimpleNamespace(content="method=table\nskills=chosen-method\nknowledge=\nfocus=\nreason=try table",
                                call_id="plan-call", finish_reason="stop")
        with patch.object(guided, "_shortlist", return_value=([("chosen-method", "self-authored skill")], [])), \
             patch.object(guided, "_request", return_value=reply) as request:
            state = guided.plan(ctx, State())
        self.assertEqual(state["method"], "table")
        self.assertEqual(ctx.store["guided"]["plan"]["skills"], ["chosen-method"])
        self.assertEqual(ctx.store["guided"]["checker_status"], "unsupported")
        report = ctx.record.artifacts["guided/plan-capability.json"]
        self.assertEqual(report["requested"], "table")
        self.assertFalse(report["table_supported"])
        self.assertIn("falling-edge", report["reason"])
        self.assertIn('"supported":false', request.call_args.args[2][-1]["content"])



class GuidedEmptyRecoveryTests(unittest.TestCase):
    context = GuidedContextFlowTests.context
    RTL = "module TopModule(input clk, input reset, input d, output q); assign q=d; endmodule"

    def run_context(self, replies, *, remaining=840, max_calls=8, max_tokens=65536):
        ctx = self.context()
        data = ctx.store["guided"]
        data.update(attempted=set(), request_outcomes={}, method="structural",
                    observations={}, behaviors={}, checker_hash=None)
        ctx.budget = SimpleNamespace(remaining=lambda: remaining)
        data["ledger"] = CompletionLedger(ctx.budget, ctx.record,
                                           max_calls=max_calls, max_output_tokens=max_tokens)
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        ctx.candidates = CandidateStore(ctx.record, temporary.name)
        ctx.store["submission"] = SubmissionGateway(ctx, policy="author_decides")
        ctx.sent = []
        pending = iter(replies)

        class Model:
            @contextmanager
            def permitted(self, permit):
                self.permit = permit
                permit._begin()
                try:
                    yield
                finally:
                    permit._finish()

            def chat(self, messages, **kwargs):
                ctx.sent.append((copy.deepcopy(messages), kwargs))
                response = next(pending)
                call = f"m{len(ctx.sent)}"
                if isinstance(response, dict) and "metadata_error" in response:
                    # Real metadata requests have their own call ids but never
                    # call permit._sent; only the completion does so.
                    raise response["metadata_error"]
                self.permit._sent(call, kwargs["max_tokens"])
                if isinstance(response, Exception):
                    self.permit._response({})
                    raise response
                content, finish, usage = response
                self.permit._response({"usage": usage})
                return Reply(call, content, finish,
                             usage.get("prompt_tokens") if usage else None,
                             usage.get("completion_tokens") if usage else None,
                             reasoning={"content": "PRIVATE_REASONING"})

        ctx.llm = Model()
        return ctx

    @staticmethod
    def response(content, finish="stop", usage=True):
        return content, finish, ({"prompt_tokens": 3, "completion_tokens": 7} if usage else None)

    def test_identical_returned_recoveries_stop_but_different_reasoning_can_continue(self):
        for distinct in (False, True):
            with self.subTest(distinct=distinct):
                empty = self.response("", "length")
                final = self.response(self.RTL)
                ctx = self.run_context([empty, empty, empty, final])
                data = ctx.store["guided"]
                chat = ctx.llm.chat
                if distinct:
                    from dataclasses import replace

                    def vary(*args, **kwargs):
                        reply = chat(*args, **kwargs)
                        return replace(reply, reasoning={"reasoning_content": reply.call_id})

                    ctx.llm.chat = vary
                state = guided.solve(ctx, State())
                if distinct:
                    self.assertIsNotNone(state["target_id"])
                    self.assertEqual(ctx.candidates.get(state["target_id"]).source_stage,
                                     "guided_solve_recovery_3")
                else:
                    self.assertIsNone(state["target_id"])
                    self.assertEqual(data["stop_detail"], "repeated_empty_recovery")
                self.assertEqual(data["solve_recoveries_sent"], 3 if distinct else 2)

    def test_advisory_interface_allows_tools_but_cannot_claim_all_three_checks_passed(self):
        from agent.domain.rtl.result import CheckResult

        ctx = self.run_context([self.response(self.RTL)])
        state = guided.solve(ctx, State())
        ctx.call = lambda name, **kwargs: (CheckResult("failed", "advisory width", blocking=False)
                                           if name == "interface" else CheckResult("passed", name))
        state = guided.structure(ctx, state.update(method="structural"))
        self.assertEqual(state["action"], "finish")
        guided.finish(ctx, state)
        result = ctx.record.artifacts["guided/result.json"]
        self.assertTrue(result["toolchain_passed"])
        self.assertFalse(result["interface_verified"])
        self.assertFalse(result["structural_passed"])
        self.assertEqual(result["submission_mode"], "structural_auto")
        self.assertEqual(result["status"], "completed")

    def test_same_rtl_is_rechecked_and_repair_may_repeat_until_shared_limit(self):
        ctx = self.run_context([self.response(self.RTL)] * 3, max_calls=3)
        ctx.call = lambda name, **kwargs: (CheckResult("failed", "source error", failure_kind="code")
                                           if name == "lint" else CheckResult("passed", name))
        state = guided.solve(ctx, State()).update(method="structural")
        for _ in range(3):
            self.assertEqual(guided.structure(ctx, state)["action"], "repair_structure")
            state = guided.repair_structure(ctx, state)
        self.assertEqual(guided.structure(ctx, state)["action"], "finish")
        guided.finish(ctx, state)
        result = ctx.record.artifacts["guided/result.json"]
        self.assertEqual(result["stop_detail"], "call_limit")
        self.assertEqual(result["fallback_basis"], "latest_complete")
        self.assertEqual(len(ctx.store["guided"]["assessments"]), 3)
        self.assertEqual(result["published_id"], state["target_id"])
        self.assertFalse(result["decision_history"][-1]["changed"])
        self.assertIn("source error", ctx.sent[2][0][-1]["content"])

    def test_solve_stop_and_length_empty_recover_once_and_bind_actual_answer(self):
        for finish in ("stop", "length"):
            with self.subTest(finish=finish):
                ctx = self.run_context([self.response("", finish), self.response(self.RTL)])
                state = guided.solve(ctx, State())
                candidate = ctx.candidates.get(state["target_id"])
                self.assertEqual(candidate.source_call_id, "m2")
                self.assertEqual(candidate.source_stage, "guided_solve_recovery")
                self.assertEqual(len(ctx.sent), 2)
                self.assertEqual(ctx.store["guided"]["ledger"].snapshot()["calls_sent"], 2)
                self.assertEqual(ctx.store["guided"]["ledger"].snapshot()["known_output_tokens"], 14)
                first, second = (entry[0] for entry in ctx.sent)
                self.assertEqual([x["role"] for x in second], ["system", "user"])
                for marker in ("PRIVATE_REASONING", "PRIVATE_CANDIDATE", "PRIVATE_MEASUREMENT"):
                    self.assertNotIn(marker, str(second))
                self.assertIn(PROMPT, str(second))
                self.assertNotIn("Failure category", str(first))
                self.assertIn(f"Failure category: {finish}_no_final", str(second))
                self.assertEqual(ctx.sent[0][1]["profile"], ctx.sent[1][1]["profile"])
                data = ctx.store["guided"]
                data["assessments"][candidate.id] = {"structural_passed": True}
                guided.finish(ctx, state)
                result = ctx.record.artifacts["guided/result.json"]
                self.assertEqual(result["published_id"], candidate.id)
                self.assertEqual(result["evidence_candidate_id"], candidate.id)
                self.assertEqual(result["solve_recovery_attempts"], 1)
                self.assertEqual(result["solve_recoveries_sent"], 1)
                self.assertEqual(Path(ctx.candidates.output_dir, "solution.v").read_text(), candidate.code)
                self.assertEqual(ctx.record.artifacts["guided/solve-failure.json"]["kind"],
                                 f"{finish}_no_final")

    def test_repeated_empty_is_bounded_and_preserves_both_failures(self):
        for stage in ("solve", "checker"):
            with self.subTest(stage=stage):
                ctx = self.run_context([self.response("", "length"), self.response("", "stop")],
                                       max_calls=3 if stage == "checker" else 2)
                state = getattr(guided, "build_checker" if stage == "checker" else "solve")(ctx, State())
                self.assertEqual(len(ctx.sent), 2)
                self.assertEqual(ctx.record.artifacts[f"guided/{stage}-failure.json"]["kind"],
                                 "length_no_final")
                self.assertEqual(ctx.record.artifacts[f"guided/{stage}_recovery-failure.json"]["kind"],
                                 "stop_no_final")
                self.assertEqual(ctx.store["guided"][f"{stage}_recoveries_sent"], 1)
                if stage == "checker":
                    self.assertEqual(state["checker_status"], "invalid")
                else:
                    self.assertIsNone(state["target_id"])
                self.assertEqual(len(ctx.candidates.values()), 0)

    def test_checker_recovery_is_independent_of_planner_candidate_and_measurements(self):
        ctx = self.run_context([self.response("", "stop"), self.response(TABLE)])
        data = ctx.store["guided"]
        data["plan"]["focus"] = ["PRIVATE_PLANNER_FORMULA"]
        data["behavior"] = {"actual": "PRIVATE_MEASUREMENT"}
        data["adjudication"] = {"reason": "PRIVATE_DIAGNOSIS"}
        state = guided.build_checker(ctx, State())
        self.assertEqual(state["checker_status"], "valid")
        self.assertEqual(data["checker_reviews"], 0)
        self.assertEqual(data["checker_recovery_attempts"], 1)
        self.assertEqual(data["checker_recoveries_sent"], 1)
        for messages, kwargs in ctx.sent:
            self.assertEqual([x["role"] for x in messages], ["system", "user"])
            self.assertIn(PROMPT, str(messages))
            for marker in ("PRIVATE_PLANNER_FORMULA", "PRIVATE_CANDIDATE", "PRIVATE_REASONING",
                           "PRIVATE_MEASUREMENT", "PRIVATE_DIAGNOSIS"):
                self.assertNotIn(marker, str(messages))
        self.assertEqual(ctx.sent[0][1]["profile"], ctx.sent[1][1]["profile"])

    def test_nonempty_invalid_unknown_finish_and_transport_error_do_not_retry(self):
        for stage in ("solve", "checker"):
            for response in (self.response("not a valid artifact"), self.response("", "other"),
                             ModelError("HTTP 500", kind="http", call_id="m1")):
                with self.subTest(stage=stage, response=response):
                    ctx = self.run_context([response], max_calls=2 if stage == "checker" else 1)
                    getattr(guided, "build_checker" if stage == "checker" else "solve")(ctx, State())
                    self.assertEqual(len(ctx.sent), 1)
                    self.assertEqual(ctx.store["guided"].get(f"{stage}_recovery_attempts", 0), 0)
                    outcome = ctx.store["guided"]["request_outcomes"][stage]
                    if isinstance(response, Exception):
                        self.assertEqual(outcome["status"], "error")
                        self.assertEqual(outcome["kind"], "http")
                    else:
                        self.assertEqual(outcome["failure_kind"],
                                         "empty_unknown_finish" if not response[0]
                                         else ("invalid_rtl" if stage == "solve" else "invalid_checker"))

    def test_recovery_denied_by_calls_tokens_unknown_usage_and_time(self):
        for stage in ("solve", "checker"):
            denials = ["output_token_limit", "unknown_usage", "insufficient_followup_time"]
            if stage == "solve":
                denials.append("call_limit")
            for denial in denials:
                with self.subTest(stage=stage, denial=denial):
                    ctx = self.run_context([self.response("", usage=denial != "unknown_usage")],
                                           max_calls=1 if denial == "call_limit" else 8,
                                           max_tokens=7 if denial == "output_token_limit" else 65536)
                    if denial == "insufficient_followup_time":
                        original_chat = ctx.llm.chat
                        def consume_time(*args, **kwargs):
                            reply = original_chat(*args, **kwargs)
                            ctx.budget.remaining = lambda: 139
                            return reply
                        ctx.llm.chat = consume_time
                    getattr(guided, "build_checker" if stage == "checker" else "solve")(ctx, State())
                    self.assertEqual(len(ctx.sent), 1)
                    data = ctx.store["guided"]
                    self.assertEqual(data[f"{stage}_recovery_attempts"], 1)
                    self.assertEqual(data[f"{stage}_recoveries_sent"], 0)
                    self.assertEqual(data["request_outcomes"][f"{stage}_recovery"],
                                     {"status": "not_sent", "reason": denial})

    def test_recovery_metadata_error_call_id_does_not_count_as_sent(self):
        for stage in ("solve", "checker"):
            for operation in ("tokenize", "apply-template"):
                with self.subTest(stage=stage, operation=operation):
                    ctx = self.run_context([
                        self.response(""),
                        {"metadata_error": ModelError(f"{operation} HTTP 500", kind="http",
                                                      call_id="metadata-m2")},
                    ])
                    getattr(guided, "build_checker" if stage == "checker" else "solve")(ctx, State())
                    data = ctx.store["guided"]
                    self.assertEqual(data[f"{stage}_recovery_attempts"], 1)
                    self.assertEqual(data[f"{stage}_recoveries_sent"], 0)
                    outcome = data["request_outcomes"][f"{stage}_recovery"]
                    self.assertEqual(outcome["status"], "error")
                    self.assertEqual(outcome["call_id"], "metadata-m2")
                    ledger = data["ledger"].snapshot()
                    self.assertEqual(ledger["calls_sent"], 1)
                    self.assertEqual(ledger["permits"][-1]["stage"], f"{stage}_recovery")
                    self.assertEqual(ledger["permits"][-1]["state"], "released")
                    self.assertIsNone(ledger["permits"][-1]["call_id"])
                    self.assertEqual(len(ctx.sent), 2)

    def test_recovery_http_error_counts_as_sent_without_another_retry(self):
        for stage in ("solve", "checker"):
            with self.subTest(stage=stage):
                ctx = self.run_context([self.response(""),
                                        ModelError("HTTP 500", kind="http", call_id="m2")])
                getattr(guided, "build_checker" if stage == "checker" else "solve")(ctx, State())
                self.assertEqual(len(ctx.sent), 2)
                data = ctx.store["guided"]
                self.assertEqual(data[f"{stage}_recovery_attempts"], 1)
                self.assertEqual(data[f"{stage}_recoveries_sent"], 1)
                ledger = data["ledger"].snapshot()
                self.assertEqual(ledger["calls_sent"], 2)
                self.assertEqual(ledger["permits"][-1]["state"], "settled")
                self.assertEqual(ledger["permits"][-1]["call_id"], "m2")
                self.assertEqual(data["request_outcomes"][f"{stage}_recovery"]["status"], "error")
                self.assertEqual(ctx.record.artifacts[f"guided/{stage}-failure.json"]["kind"],
                                 "stop_no_final")

    def test_planner_uses_minimum_solve_reserve_not_maximum_stage_timeout(self):
        ctx = self.run_context([self.response(
            "method=table\nskills=\nknowledge=\nfocus=reset\nreason=public reset")])
        settings = ctx.store["guided"]["settings"]
        settings["solve"]["timeout_s"] = 900
        with patch.object(guided, "_shortlist", return_value=([], [])):
            state = guided.plan(ctx, State())
        self.assertEqual(state["method"], "table")
        permit = ctx.store["guided"]["ledger"].snapshot()["permits"][0]
        self.assertEqual(permit["followup_s"], 240)
        self.assertEqual(permit["timeout_s"], 90)
        self.assertLessEqual(permit["timeout_s"] + permit["followup_s"], 840)

    def comb_context(self, replies, *, max_calls=8, method="table"):
        ctx = self.run_context([self.response(text) for text in replies], max_calls=max_calls)
        ctx.task = TaskSpec.from_text("self-authored-inverter", "Set y to the complement of a.",
                                      "module TopModule(input a, output y);")
        data = ctx.store["guided"]
        data.update(method=method, plan={"method": method, "skills": ["rtl-module-interface-contract"],
                                         "focus": [], "knowledge": [], "reason": "PRIVATE_PLANNER"})
        data.pop("skill_assets")
        ctx.call = lambda stage, **kwargs: CheckResult("passed", stage)
        return ctx

    @staticmethod
    def sample(ctx, candidate, plan, **kwargs):
        from agent.domain.rtl.observation import parse_observations
        marker = "abcdef0123456789"
        rows = []
        for ci, case in enumerate(plan["cases"]):
            for si, step in enumerate(case["steps"]):
                a = step["inputs"]["a"]
                y = int(not a) if "~a" in candidate.code else a
                if "UNKNOWN_SAMPLE" in candidate.code:
                    y = "x"
                for phase, tick in (("pre", si), ("post", si + 1)):
                    rows.append(f"RTLA_OBS_{marker}|{ci}|{si}|{tick}|{phase}|b:{a}|b:{y}")
        rows.append(f"RTLA_OBS_DONE_{marker}")
        return parse_observations("\n".join(rows), plan, marker, candidate_hash=candidate.code_hash,
                                  execution_id="self-authored-" + candidate.id)

    GOOD = "module TopModule(input a, output y); /* PRIVATE_RTL */ assign y=~a; endmodule"
    POINT = "case polarity # A low input produces a high output.\nstep a=0 y=1"
    ASK = "action=review\nreason=PRIVATE_AUTHOR_OBJECTION\ncase_id=polarity"
    SUBMIT = "action=submit\nreason=I choose this implementation for the public task."

    def active(self, ctx):
        state = guided.solve(ctx, State()).update(method="table")
        self.assertEqual(guided.structure(ctx, state)["action"], "build_checker")
        self.assertEqual(guided.build_checker(ctx, state)["checker_status"], "valid")
        with patch.object(guided, "observe", side_effect=self.sample):
            self.assertEqual(guided.run_checker(ctx, state)["action"], "author_decision")
        return state

    def test_check_format_and_individual_review_preserve_authority_and_history(self):
        wrong = self.POINT.replace("y=1", "y=0")
        other = "\ncase high # A high input gives a low output.\nstep a=1 y=0"
        for command in ("keep", "correct", "withdraw", "withdraw_last"):
            with self.subTest(command=command):
                change = command.split("_")[0]
                reviewer = f"review polarity {change} # PUBLIC_REVIEW_REASON"
                if change == "correct":
                    reviewer += "\n" + self.POINT
                table = wrong + ("" if command == "withdraw_last" else other)
                ctx = self.comb_context([self.GOOD, "case polarity\nstep a=0 y=0",
                                         table, self.ASK, reviewer, self.SUBMIT])
                state = self.active(ctx)
                data = ctx.store["guided"]
                initial = guided._behavior_for(data, state["target_id"])
                self.assertEqual(initial["status"], "failed")
                self.assertEqual(initial["failed"][0]["actual_bits"], 1)
                self.assertEqual(data["checker_format_repairs"], 1)
                self.assertEqual(guided.author_decision(ctx, state)["action"], "review")
                old_hash = data["checker_hash"]
                after = guided.checker_review(ctx, state)
                if command in ("withdraw", "correct"):
                    self.assertEqual(after["action"], "run_checker")
                    self.assertEqual(guided._behavior_for(data, state["target_id"]), {})
                    with patch.object(guided, "observe", side_effect=self.sample):
                        guided.run_checker(ctx, state)
                else:
                    self.assertEqual(after["action"], "author_decision")
                self.assertEqual(data["checker_hash"] == old_hash, change == "keep")
                self.assertEqual(guided.author_decision(ctx, state)["action"], "submit")
                guided.finish(ctx, state)
                result = ctx.record.artifacts["guided/result.json"]
                self.assertEqual(result["submission_mode"], "author_submit")
                self.assertFalse(result["functional_passed"])
                self.assertEqual(result["current_table_passed"], command in ("correct", "withdraw"))
                self.assertEqual(result["withdrawn_cases"], ["polarity"] if change == "withdraw" else [])
                self.assertEqual(result["checker_status"], "withdrawn" if command == "withdraw_last" else "valid")
                roles = [args[1]["purpose"] for args in ctx.sent]
                self.assertEqual(roles, ["guided_solve", "guided_checker", "guided_checker_format_repair",
                                         "guided_author_decision", "guided_checker_review", "guided_author_decision_2"])
                for i in (1, 2, 4):
                    messages = str(ctx.sent[i][0])
                    for forbidden in ("PRIVATE_RTL", "PRIVATE_AUTHOR_OBJECTION", "PRIVATE_REASONING",
                                      "PRIVATE_PLANNER", '"actual_bits":', "self-authored-c001",
                                      ctx.candidates.get(state["target_id"]).code_hash, "Skill rtl-module-interface-contract"):
                        self.assertNotIn(forbidden, messages)
                self.assertIn("Host parser diagnostic", str(ctx.sent[2][0]))
                last = str(ctx.sent[-1][0])
                for marker in ("PRIVATE_RTL", "PRIVATE_AUTHOR_OBJECTION", "PUBLIC_REVIEW_REASON",
                               "Skill rtl-module-interface-contract", old_hash):
                    self.assertIn(marker, last)
                self.assertNotIn("PRIVATE_REASONING", last)
                self.assertEqual(len(ctx.candidates.values()), 1)

    def test_failed_review_keeps_evidence_and_explains_the_failure_to_the_author(self):
        ctx = self.comb_context([self.GOOD, self.POINT, self.ASK, "review alien keep # Wrong point.",
                                 self.SUBMIT], max_calls=5)
        state = self.active(ctx)
        data = ctx.store["guided"]
        prior = guided._behavior_for(data, state["target_id"])
        self.assertEqual(guided.author_decision(ctx, state)["action"], "review")
        self.assertEqual(guided.checker_review(ctx, state)["action"], "author_decision")
        self.assertIs(prior, guided._behavior_for(data, state["target_id"]))
        self.assertEqual(data["last_revision"]["review_action"], "unresolved")
        self.assertEqual(guided.author_decision(ctx, state)["action"], "submit")
        self.assertIn("unresolved", str(ctx.sent[-1][0]))

    def test_revision_in_same_reply_rechecks_child_and_changes_measured_result(self):
        wrong = self.GOOD.replace("~a", "a").replace("PRIVATE_RTL", "PRIVATE_OLD_RTL")
        revision = "action=revise\nreason=Invert the input.\n```verilog\n" + self.GOOD + "\n```"
        ctx = self.comb_context([wrong, self.POINT, revision, self.SUBMIT])
        state = self.active(ctx)
        data = ctx.store["guided"]
        parent = ctx.candidates.get(state["target_id"])
        self.assertEqual(guided._behavior_for(data, parent.id)["status"], "failed")
        state = guided.author_decision(ctx, state)
        child = ctx.candidates.get(state["target_id"])
        self.assertEqual((state["action"], child.parent_id, child.source_call_id), ("revise", parent.id, "m3"))
        self.assertEqual(guided._behavior_for(data, child.id), {})
        self.assertEqual(guided.structure(ctx, state)["action"], "run_checker")
        with patch.object(guided, "observe", side_effect=self.sample):
            guided.run_checker(ctx, state)
        self.assertEqual(guided._behavior_for(data, child.id)["status"], "passed")
        self.assertEqual(guided.author_decision(ctx, state)["action"], "submit")
        guided.finish(ctx, state)
        result = ctx.record.artifacts["guided/result.json"]
        self.assertTrue(result["functional_passed"])
        self.assertEqual(result["published_id"], child.id)
        self.assertEqual(result["budget"]["calls_sent"], 4)
        self.assertIn("Invert the input.", str(ctx.sent[-1][0]))
        self.assertNotIn("PRIVATE_OLD_RTL", str(ctx.sent[-1][0]))

    def test_zero_comparisons_and_unavailable_simulation_go_to_author(self):
        from agent.domain.rtl.observation import TraceRun
        for unavailable in (False, True):
            with self.subTest(unavailable=unavailable):
                ctx = self.comb_context([self.GOOD.replace("PRIVATE_RTL", "UNKNOWN_SAMPLE"), self.POINT,
                                         self.SUBMIT])
                state = guided.solve(ctx, State()).update(method="table")
                guided.structure(ctx, state)
                guided.build_checker(ctx, state)
                trace = TraceRun("unavailable", "", "", "absent", summary="Missing simulation executable.",
                                 failure_kind="environment")
                with patch.object(guided, "observe", side_effect=(lambda *a, **k: trace) if unavailable else self.sample):
                    self.assertEqual(guided.run_checker(ctx, state)["action"], "author_decision")
                self.assertEqual(guided.author_decision(ctx, state)["action"], "submit")
                guided.finish(ctx, state)
                result = ctx.record.artifacts["guided/result.json"]
                self.assertEqual(result["behavior"]["status"], "unavailable" if unavailable else "unknown")
                self.assertEqual(result["behavior"]["compared_bits"], 0)
                self.assertFalse(result["functional_passed"])
                self.assertEqual(result["submission_mode"], "author_submit")

    def test_invalid_strategy_falls_back_but_unconfirmed_strategy_blocks_next_call(self):
        for interrupted in (False, True):
            with self.subTest(interrupted=interrupted):
                ctx = self.run_context([self.response("invalid plan")] if interrupted else
                                       [self.response("invalid plan"), self.response(self.RTL)])
                if interrupted:
                    def timeout(messages, **kwargs):
                        ctx.sent.append((messages, kwargs))
                        ctx.llm.permit._sent("m1", kwargs["max_tokens"])
                        raise ModelError("No terminal response.", kind="timeout", call_id="m1")
                    ctx.llm.chat = timeout
                with patch.object(guided, "_shortlist", return_value=([], [])):
                    state = guided.plan(ctx, State())
                self.assertEqual(ctx.store["guided"]["plan_source"], "fallback")
                self.assertEqual((state["method"], ctx.store["guided"]["plan"]["skills"]), ("structural", []))
                state = guided.solve(ctx, state)
                if interrupted:
                    self.assertIsNone(state["target_id"])
                    self.assertEqual(len(ctx.sent), 1)
                    self.assertEqual(ctx.store["guided"]["request_outcomes"]["solve"]["reason"], "unconfirmed_completion")
                else:
                    ctx.call = lambda stage, **kw: CheckResult("passed", stage)
                    self.assertEqual(guided.structure(ctx, state)["action"], "finish")
                    guided.finish(ctx, state)
                    self.assertEqual(ctx.record.artifacts["guided/result.json"]["submission_mode"], "structural_auto")
                    self.assertEqual(len(ctx.sent), 2)

    def test_table_request_on_unsupported_interface_keeps_skills_and_asks_author(self):
        plan = ("method=table\nskills=rtl-module-interface-contract\nknowledge=\nfocus=\nreason=Plan")
        ctx = self.comb_context([plan, self.RTL, self.SUBMIT])
        ctx.task = TaskSpec.from_text("falling", "Capture d on the falling edge of clk.", INTERFACE)
        state = guided.plan(ctx, State())
        self.assertEqual((state["method"], ctx.store["guided"]["checker_status"]), ("table", "unsupported"))
        state = guided.solve(ctx, state)
        self.assertEqual(guided.structure(ctx, state)["action"], "author_decision")
        self.assertEqual(guided.author_decision(ctx, state)["action"], "submit")
        guided.finish(ctx, state)
        for i in (1, 2):
            self.assertIn("[Skill rtl-module-interface-contract]", str(ctx.sent[i][0]))
        self.assertIn("falling-edge", str(ctx.sent[-1][0]))
        self.assertEqual(ctx.record.artifacts["guided/result.json"]["submission_mode"], "author_submit")
        self.assertFalse(ctx.record.artifacts["guided/result.json"]["functional_passed"])
        self.assertEqual(len(ctx.sent), 3)

    def test_review_of_an_active_table_cannot_bypass_a_childs_unavailable_synthesis(self):
        revision = "action=revise\nreason=Use the explicit inversion.\n```verilog\n" + self.GOOD + "\n```"
        keep_high = "\ncase high # A high input produces a low output.\nstep a=1 y=0"
        ctx = self.comb_context([self.GOOD.replace("~a", "a"), self.POINT + keep_high, revision,
                                 self.ASK, "review polarity withdraw # This scenario is redundant.", self.SUBMIT])
        data = ctx.store["guided"]
        state = self.active(ctx)
        updated = guided.author_decision(ctx, state)
        ctx.call = lambda stage, **kw: (CheckResult("unavailable", "Vivado license unavailable.",
                                                    failure_kind="environment") if stage == "synth"
                                        else CheckResult("passed", stage))
        self.assertEqual(guided.structure(ctx, updated)["action"], "author_decision")
        self.assertEqual(guided.author_decision(ctx, updated)["action"], "review")
        self.assertEqual(guided.checker_review(ctx, updated)["action"], "author_decision")
        self.assertEqual(guided._behavior_for(data, updated["target_id"]), {})
        self.assertEqual(data["checker_status"], "valid")
        self.assertEqual(guided.author_decision(ctx, updated)["action"], "submit")
        guided.finish(ctx, updated)
        result = ctx.record.artifacts["guided/result.json"]
        self.assertEqual(result["published_id"], updated["target_id"])
        self.assertEqual(result["submission_mode"], "author_submit")
        self.assertFalse(result["toolchain_passed"])
        self.assertFalse(result["functional_passed"])

    def test_last_call_goes_to_author_when_initial_builder_or_reviewer_cannot_reply_in_time(self):
        for review in (False, True):
            with self.subTest(review=review):
                replies = [self.GOOD, self.POINT, self.ASK, self.SUBMIT] if review else [self.GOOD, self.SUBMIT]
                ctx = self.comb_context(replies, max_calls=len(replies))
                if review:
                    state = self.active(ctx)
                    self.assertEqual(guided.author_decision(ctx, state)["action"], "review")
                    self.assertEqual(guided.checker_review(ctx, state)["action"], "author_decision")
                    skipped = "checker_review"
                else:
                    state = guided.solve(ctx, State()).update(method="table")
                    self.assertEqual(guided.structure(ctx, state)["action"], "build_checker")
                    self.assertEqual(guided.build_checker(ctx, state)["checker_status"], "unavailable")
                    skipped = "checker"
                self.assertEqual(guided.author_decision(ctx, state)["action"], "submit")
                guided.finish(ctx, state)
                result = ctx.record.artifacts["guided/result.json"]
                self.assertEqual(result["budget"]["calls_sent"], len(replies))
                self.assertEqual(result["request_outcomes"][skipped],
                                 {"status": "not_sent", "reason": "reserved_last_call_for_author"})
                self.assertIn("reserved_last_call_for_author", str(ctx.sent[-1][0]))
                self.assertEqual(result["submission_mode"], "author_submit")
                self.assertFalse(result["functional_passed"])

    def test_one_review_cannot_settle_another_unresolved_test_point(self):
        table = self.POINT + "\ncase high # A high input gives a low output.\nstep a=1 y=0"
        ask_b = self.ASK.replace("case_id=polarity", "case_id=high")
        ctx = self.comb_context([self.GOOD, table, self.ASK, "", ask_b,
                                 "review high keep # This follows the public specification.", self.SUBMIT])
        state = self.active(ctx)
        for _ in range(2):
            self.assertEqual(guided.author_decision(ctx, state)["action"], "review")
            self.assertEqual(guided.checker_review(ctx, state)["action"], "author_decision")
        self.assertEqual(guided.author_decision(ctx, state)["action"], "submit")
        guided.finish(ctx, state)
        result = ctx.record.artifacts["guided/result.json"]
        self.assertEqual(list(result["unresolved_reviews"]), ["polarity"])
        self.assertIn('"unresolved_reviews":{"polarity"', ctx.sent[-1][0][-1]["content"])
        self.assertTrue(result["checker_disputed"])
        self.assertTrue(result["current_table_passed"])
        self.assertFalse(result["functional_passed"])

    def test_empty_structural_repair_retries_the_same_diagnostic_before_rechecking(self):
        fixed = self.RTL.replace("assign q=d", "assign q=~d")
        ctx = self.run_context([self.response(self.RTL), self.response("", "stop"), self.response(fixed)])
        checked = []
        def tool(name, *, candidate_id, **kwargs):
            checked.append((candidate_id, name))
            if name == "lint" and candidate_id == first:
                return CheckResult("failed", "ERROR near example_lint_token", rc=1, failure_kind="code")
            return CheckResult("passed", name)
        ctx.call = tool
        state = guided.solve(ctx, State()).update(method="structural")
        first = state["target_id"]
        self.assertEqual(guided.structure(ctx, state)["action"], "repair_structure")
        retry = guided.repair_structure(ctx, state)
        self.assertEqual((retry["action"], retry["target_id"]), ("retry", first))
        fixed_state = guided.repair_structure(ctx, retry)
        self.assertEqual(fixed_state["action"], "recheck")
        self.assertNotEqual(fixed_state["target_id"], first)
        self.assertIn("example_lint_token", ctx.sent[-1][0][-1]["content"])
        self.assertIn("stop_no_final", ctx.sent[-1][0][-1]["content"])
        self.assertEqual(guided.structure(ctx, fixed_state)["action"], "finish")
        guided.finish(ctx, fixed_state)
        self.assertEqual(checked.count((first, "lint")), 1)
        result = ctx.record.artifacts["guided/result.json"]
        self.assertEqual(result["structure_repairs"], 1)
        self.assertEqual(result["structure_repair_attempts"], 2)
        self.assertEqual(result["submission_mode"], "structural_auto")
        self.assertEqual(result["published_id"], fixed_state["target_id"])

    def test_last_available_call_is_returned_to_author_after_invalid_checker(self):
        ctx = self.run_context([self.response("case missing_note"), self.response("action=submit\nreason=Verification unavailable.")], max_calls=2)
        data = ctx.store["guided"]
        parent = ctx.candidates.create(self.RTL, source_stage="self_authored")
        ctx.store["submission"].register(parent, reason="fixture")
        ctx.call = lambda name, **kw: CheckResult("passed", name)
        data["method"] = "table"
        state = State({"target_id": parent.id, "method": "table"})
        self.assertEqual(guided.structure(ctx, state)["action"], "build_checker")
        self.assertEqual(guided.build_checker(ctx, state)["checker_status"], "invalid")
        self.assertEqual(guided.author_decision(ctx, state)["action"], "submit")
        guided.finish(ctx, state)
        result = ctx.record.artifacts["guided/result.json"]
        self.assertEqual(result["submission_mode"], "author_submit")
        self.assertFalse(result["functional_passed"])
        self.assertIn("explanation", ctx.sent[-1][0][-1]["content"])

if __name__ == "__main__":
    unittest.main()
