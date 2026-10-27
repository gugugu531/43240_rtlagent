"""Host routing gates, Skill candidates and the generation plan projection.

These tests use synthetic public tasks and analysis advice only: no model request,
candidate RTL, checker payload or tool observation is involved.
"""
import dataclasses
import json
import unittest
from types import SimpleNamespace

from agent.domain.knowledge.policy import assert_automatic_skill_allowed, route_skill_ids
from agent.context.prompts import TemplateRenderer
from agent.domain.rtl.adaptive_analysis import RouteDecision, choose_route
from agent.domain.rtl.task import TaskSpec

NL = "\n"


def bullet_task(ports, description, top="TopModule"):
    listing = NL.join(" - " + port for port in ports)
    prompt = (
        "I would like you to implement a module named TopModule with the following" + NL
        + "interface. All input and output ports are one bit unless otherwise" + NL
        + "specified." + NL + NL + listing + NL + NL + description
    )
    return TaskSpec.from_text("synthetic", prompt, "", top=top)


def signature_task(module_text, description, top="TopModule"):
    prompt = ("Implement the design." + NL + NL + "Design signature:" + NL
              + "```verilog" + NL + module_text + NL + "```" + NL + NL + description)
    return TaskSpec.from_text("synthetic", prompt, "", top=top)


def advice(**overrides):
    values = dict(kind="sequential", route="model", model_cost="small", clocks=[],
                  risks=["state_update"], ambiguities=[], requirements=["public requirement"])
    values.update(overrides)
    return SimpleNamespace(**values)


LATCH_TASK = bullet_task(
    ["input  d", "input  ena", "output q"],
    "The module should impement a D latch using an always block.",
)
FSM_TASK = bullet_task(
    ["input  in", "input  state (4 bits)", "output next_state (4 bits)", "output out"],
    "The module should implement the state transition table for a Moore state machine "
    "with one input, one output, and four states. Use the following one-hot state encoding.",
)
DUAL_EDGE_TASK = bullet_task(
    ["input  clk", "input  d", "output q"],
    "A dual-edge triggered flip-flop is triggered on both edges of the clock.",
)
ASYNC_TASK = bullet_task(
    ["input  clk", "input  ar", "input  d", "output q"],
    'The module should implement a D flip flop, positive edge triggered, with an '
    'asynchronous reset "ar".',
)
WIDE_TASK = bullet_task(
    ["input  in  (1024 bits)", "input  sel (   8 bits)", "output out (   4 bits)"],
    "The module should implement a 4-bit wide, 256-to-1 multiplexer.",
)


class RouteGates(unittest.TestCase):
    def test_level_sensitive_gate_downgrades_clockless_latch(self):
        decision = choose_route(LATCH_TASK, advice(
            ambiguities=["A D latch is level-sensitive and keeps its previous value."]))
        self.assertEqual(decision.route, "structural")
        self.assertEqual(decision.reason, "level_sensitive_storage_requires_clock")
        self.assertIn("behavior_not_checked", decision.uncovered)
        self.assertEqual(decision.skill_candidates, ())

    def test_clockless_next_state_fsm_is_not_downgraded(self):
        # 079/135/143/150-style tasks: state is an input, next_state a combinational output.
        for route in ("model", "properties"):
            with self.subTest(route=route):
                decision = choose_route(FSM_TASK, advice(
                    kind="fsm", route=route, risks=["completeness"],
                    ambiguities=["Invalid one-hot states are unspecified."],
                    requirements=["Every listed state transition must be implemented."]))
                self.assertEqual(decision.route, route)
                self.assertEqual(decision.reason, "analysis_route_with_host_limits")
                self.assertNotIn("behavior_not_checked", decision.uncovered)
                self.assertEqual(decision.skill_candidates, ("rtl-fsm-state-output",))

    def test_clockless_level_word_without_stateful_analysis_is_ignored(self):
        task = bullet_task(["input  a", "input  b", "output y"],
                           "Implement y = a & b and do not create a latch.")
        decision = choose_route(task, advice(kind="combinational", route="model",
                                             risks=[], clocks=[]))
        self.assertEqual(decision.route, "model")
        self.assertEqual(decision.reason, "analysis_route_with_host_limits")

    def test_clockless_latch_with_edge_text_keeps_route(self):
        # The public text explicitly requests clock edges, so the shape is not G1.
        task = bullet_task(["input  d", "input  ena", "output q"],
                           "Implement a level-sensitive latch sampled on the clock edge.")
        decision = choose_route(task, advice(clocks=[]))
        self.assertEqual(decision.route, "model")
        self.assertEqual(decision.reason, "analysis_route_with_host_limits")

    def test_dual_edge_gate(self):
        for prompt in (
            "A dual-edge triggered flip-flop is triggered on both edges of the clock.",
            "The register samples on both the rising and falling edges of the clock.",
            "Use posedge and negedge of the same clock.",
        ):
            with self.subTest(prompt=prompt):
                task = bullet_task(["input  clk", "input  d", "output q"], prompt)
                decision = choose_route(task, advice(clocks=["clk"]))
                self.assertEqual(decision.route, "structural")
                self.assertEqual(decision.reason, "dual_edge_clock_not_supported")
                self.assertIn("behavior_not_checked", decision.uncovered)

    def test_dual_edge_gate_does_not_require_reported_clocks(self):
        decision = choose_route(DUAL_EDGE_TASK, advice(clocks=[]))
        self.assertEqual(decision.reason, "dual_edge_clock_not_supported")

    def test_async_reset_properties_route_moves_to_small_model(self):
        decision = choose_route(ASYNC_TASK, advice(
            route="properties", clocks=["clk"], model_cost="small",
            risks=["reset", "state_update"]))
        self.assertEqual(decision.route, "model")
        self.assertEqual(decision.reason, "async_reset_needs_off_edge_observation")
        self.assertNotIn("behavior_not_checked", decision.uncovered)
        self.assertEqual(decision.skill_candidates, ("rtl-sequential-state-update",))

    def test_async_reset_properties_route_is_structural_when_model_is_large(self):
        decision = choose_route(ASYNC_TASK, advice(
            route="properties", clocks=["clk"], model_cost="large",
            risks=["reset", "state_update"]))
        self.assertEqual(decision.route, "structural")
        self.assertEqual(decision.reason, "async_reset_needs_off_edge_observation")
        self.assertIn("behavior_not_checked", decision.uncovered)

    def test_synchronous_reset_properties_route_is_unchanged(self):
        task = bullet_task(["input  clk", "input  reset", "input  d", "output q"],
                           "Implement a positive edge triggered D flip flop with a "
                           "synchronous reset.")
        decision = choose_route(task, advice(route="properties", clocks=["clk"],
                                             risks=["reset", "state_update"]))
        self.assertEqual(decision.route, "properties")
        self.assertEqual(decision.reason, "analysis_route_with_host_limits")

    def test_async_reset_model_route_is_unchanged(self):
        decision = choose_route(ASYNC_TASK, advice(route="model", clocks=["clk"],
                                                   risks=["reset", "state_update"]))
        self.assertEqual(decision.route, "model")
        self.assertEqual(decision.reason, "analysis_route_with_host_limits")

    def test_width_gate_keeps_existing_behaviour_and_precedence(self):
        analysis = advice(kind="combinational", route="properties", risks=["width", "completeness"])
        decision = choose_route(WIDE_TASK, analysis)
        self.assertEqual(decision.route, "structural")
        self.assertEqual(decision.reason, "public_port_width_outside_checker_limits")
        self.assertIn("behavior_not_checked", decision.uncovered)
        # Earlier gates keep precedence over the new level-sensitive gate.
        blocked = choose_route(WIDE_TASK, advice(
            kind="sequential", route="model", risks=["state_update", "width"]))
        self.assertEqual(blocked.reason, "public_port_width_outside_checker_limits")

    def test_inout_gate_keeps_existing_behaviour(self):
        task = signature_task("module TopModule(inout a, input b, output y); endmodule",
                              "Drive a bidirectional pad.")
        decision = choose_route(task, advice(kind="combinational", route="model", risks=[]))
        self.assertEqual(decision.route, "structural")
        self.assertEqual(decision.reason, "inout_not_supported")

    def test_multiple_clock_gate_keeps_existing_behaviour(self):
        task = bullet_task(["input  clk1", "input  clk2", "input  d", "output q"],
                           "Implement a two clock domain register.")
        decision = choose_route(task, advice(clocks=["clk1", "clk2"]))
        self.assertEqual(decision.route, "structural")
        self.assertEqual(decision.reason, "multiple_clock_domains_not_supported")

    def test_unresolved_interface_and_missing_analysis_keep_existing_behaviour(self):
        task = TaskSpec.from_text("synthetic", "Implement module TopModule(); endmodule", "",
                                  top="TopModule")
        decision = choose_route(task, advice())
        self.assertEqual(decision.route, "structural")
        self.assertEqual(decision.reason, "public_interface_unresolved")
        unavailable = choose_route(task)
        self.assertEqual(unavailable.route, "structural")
        self.assertEqual(unavailable.reason, "analysis_unavailable")
        self.assertEqual(unavailable.skill_candidates, ())
        self.assertEqual(unavailable.uncovered, ("behavior_not_analyzed",))

    def test_unanalyzable_task_is_structural(self):
        task = bullet_task(["input  a", "output y"], "Implement y = a.")
        decision = choose_route(task, advice(kind="unknown", requirements=[]))
        self.assertEqual(decision.route, "structural")
        self.assertEqual(decision.reason, "no_grounded_check_scope")

    def test_model_cost_bound_keeps_existing_behaviour(self):
        task = bullet_task(["input  a", "output y"], "Implement y = a.")
        decision = choose_route(task, advice(kind="combinational", risks=[], model_cost="large"))
        self.assertEqual(decision.route, "properties")
        self.assertEqual(decision.reason, "full_model_outside_cost_bound")


class SkillCandidates(unittest.TestCase):
    def test_clockless_sequential_skill_is_removed(self):
        decision = choose_route(LATCH_TASK, advice())
        self.assertEqual(decision.skill_candidates, ())
        self.assertEqual(decision.skill_ids, ())

    def test_clockless_protocol_skill_is_removed(self):
        task = bullet_task(["input  req", "input  ack", "output rdy"],
                           "Implement a request/acknowledge handshake protocol.")
        decision = choose_route(task, advice(kind="protocol", route="model",
                                             risks=["handshake"], requirements=["handshake"]))
        self.assertEqual(decision.route, "model")
        self.assertEqual(decision.skill_candidates, ())

    def test_clocked_sequential_skill_is_kept(self):
        task = bullet_task(["input  clk", "input  d", "output q"],
                           "Implement a positive edge triggered D flip flop.")
        decision = choose_route(task, advice(clocks=["clk"]))
        self.assertEqual(decision.skill_candidates, ("rtl-sequential-state-update",))

    def test_configured_sequential_skill_version_is_used(self):
        task = bullet_task(["input  clk", "input  d", "output q"],
                           "Implement a positive edge triggered D flip flop.")
        decision = choose_route(task, advice(clocks=["clk"]),
                                sequential_skill="rtl-sequential-state-update-v3")
        self.assertEqual(decision.skill_candidates, ("rtl-sequential-state-update-v3",))

    def test_skill_candidates_are_the_route_selector_result_before_limits(self):
        analysis = advice(kind="arithmetic", risks=["width", "signed"], clocks=["clk"])
        task = bullet_task(["input  clk", "input  [7:0] a", "output [7:0] y"],
                           "Implement a signed add and shift arithmetic register.")
        decision = choose_route(task, analysis)
        expected = route_skill_ids("arithmetic", ["width", "signed"])
        self.assertEqual(decision.skill_candidates, expected)


class RouteDecisionContract(unittest.TestCase):
    def test_skill_candidates_is_public_and_skill_ids_is_a_read_only_alias(self):
        task = bullet_task(["input  clk", "input  d", "output q"],
                           "Implement a positive edge triggered D flip flop.")
        decision = choose_route(task, advice(clocks=["clk"]))
        self.assertIsInstance(decision, RouteDecision)
        self.assertEqual(decision.skill_ids, decision.skill_candidates)
        public = decision.public_dict()
        self.assertEqual(set(public), {"route", "reason", "skill_candidates", "uncovered"})
        self.assertNotIn("skill_ids", public)
        self.assertEqual(public["skill_candidates"], list(decision.skill_candidates))
        self.assertIsInstance(public["uncovered"], list)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            decision.skill_candidates = ()
        with self.assertRaises(dataclasses.FrozenInstanceError):
            decision.skill_ids = ()

    def test_structural_replacement_keeps_candidates(self):
        task = bullet_task(["input  clk", "input  d", "output q"],
                           "Implement a positive edge triggered D flip flop.")
        decision = choose_route(task, advice(clocks=["clk"]))
        redirected = dataclasses.replace(decision, route="structural", reason="first_draft_rescue")
        self.assertEqual(redirected.skill_candidates, decision.skill_candidates)
        self.assertEqual(redirected.skill_ids, decision.skill_candidates)


class AutomaticSkillAdmission(unittest.TestCase):
    def test_default_sequential_skill_is_allowed(self):
        self.assertIsNone(assert_automatic_skill_allowed("rtl-sequential-state-update"))

    def test_v3_candidate_is_rejected_before_any_model_call(self):
        with self.assertRaises(ValueError) as caught:
            assert_automatic_skill_allowed("rtl-sequential-state-update-v3")
        self.assertIn("not_approved_for_automatic_selection", str(caught.exception))

    def test_fixed_ab_rejected_skill_is_rejected(self):
        with self.assertRaises(ValueError) as caught:
            assert_automatic_skill_allowed("rtl-width-signed-arithmetic")
        self.assertIn("rejected_fixed_ab", str(caught.exception))

    def test_unknown_skill_is_rejected(self):
        with self.assertRaises(ValueError) as caught:
            assert_automatic_skill_allowed("rtl-no-such-method")
        self.assertIn("unknown_skill", str(caught.exception))


class GenerationPlanProjection(unittest.TestCase):
    def setUp(self):
        self.task = bullet_task(["input  clk", "input  d", "output q"],
                                "Implement a positive edge triggered D flip flop.")
        self.renderer = TemplateRenderer()
        self.classification = {"kind": "sequential", "clocks": ["clk"],
                               "risks": ["state_update"]}

    def render(self, plan):
        return self.renderer.render("repair.j2", task=self.task, feedback="",
                                    parent=None, plan=plan)[1]["content"]

    @staticmethod
    def section(text, heading):
        lines = text.splitlines()
        index = lines.index(heading)
        return json.loads(lines[index + 1])

    def test_classification_and_ambiguities_get_their_own_sections(self):
        projection = {"classification": self.classification,
                      "ambiguities": ["Reset value is not specified.",
                                      "Reset polarity is not specified."]}
        text = self.render(projection)
        self.assertEqual(
            self.section(text, "## Task classification (host routing only; not a verified design)"),
            self.classification)
        self.assertIn("Classification is routing metadata, not a chosen implementation; "
                      "the original task takes precedence.", text)
        self.assertEqual(
            self.section(text, "## Unresolved ambiguities (do not invent semantics)"),
            projection["ambiguities"])

    def test_empty_ambiguities_omit_only_that_section(self):
        text = self.render({"classification": self.classification, "ambiguities": []})
        self.assertIn("## Task classification (host routing only; not a verified design)", text)
        self.assertNotIn("## Unresolved ambiguities (do not invent semantics)", text)

    def test_absent_plan_omits_both_sections(self):
        text = self.render(None)
        self.assertNotIn("## Task classification", text)
        self.assertNotIn("## Unresolved ambiguities", text)

    def test_projection_carries_no_routing_verdict_fields(self):
        projection = {"classification": self.classification,
                      "ambiguities": ["Reset value is not specified."]}
        text = self.render(projection)
        for forbidden in ("rationale", "model_cost", '"route"', "analysis_route_with_host_limits"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, text)

    def test_legacy_plan_shape_keeps_shared_template_contract(self):
        # repair.j2 is shared with single_generate/repair_loop/design_verify: their
        # legacy plan shape must keep rendering under the original guarded heading,
        # while the adaptive classification/advisory branch stays mutually exclusive.
        text = self.render({"requirements": ["public evidence"],
                            "plan": ["step one"], "uncertain": ["legacy advice"]})
        self.assertIn("Design plan (may be incorrect; the original task takes precedence):", text)
        self.assertIn("legacy advice", text)
        self.assertNotIn("## Task classification", text)
        self.assertNotIn("## Unresolved ambiguities", text)


if __name__ == "__main__":
    unittest.main()
