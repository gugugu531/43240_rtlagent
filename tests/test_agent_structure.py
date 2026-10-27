"""Role routing, stage descriptors, context bundles, and assembly evidence."""

from types import SimpleNamespace
import tempfile
import unittest
from pathlib import Path

from agent.llm.client import Client
from agent.llm.router import profile_for_stage, role_for_stage
from agent.domain.rtl.task import TaskSpec
from agent.runtime.budget import Budget
from agent.context.prompt import (
    ContextBundle,
    assembly_from_report,
    record_assembly,
)
from agent.observability.recorder import Recorder
from agent.orchestration.stages import ADAPTIVE_STAGES, stage_spec


class RouterTests(unittest.TestCase):
    def test_stage_labels_resolve_to_roles(self):
        self.assertEqual(role_for_stage("profile"), "analyst")
        self.assertEqual(role_for_stage("draft"), "author")
        self.assertEqual(role_for_stage("draft_tool_2"), "author")
        self.assertEqual(role_for_stage("construction"), "builder")
        self.assertEqual(role_for_stage("review_retry"), "reviewer")
        self.assertEqual(profile_for_stage("repair"), "large")
        self.assertEqual(profile_for_stage("unknown_stage"), "")

    def test_stage_roles_come_from_the_single_map(self):
        for node, spec in ADAPTIVE_STAGES.items():
            self.assertEqual(spec.role, role_for_stage(node), node)
        self.assertEqual(ADAPTIVE_STAGES["repair"].role, "attributor")

    def test_author_stage_declares_tools_and_step_bound(self):
        spec = stage_spec("generate")
        self.assertEqual(spec.role, "author")
        self.assertEqual(spec.tools, ("submit_answer", "finish_task"))
        self.assertEqual(spec.max_steps, 3)
        # Tool-loop suffix maps back to the same stage.
        self.assertEqual(stage_spec("draft_tool_2"), spec)
        self.assertEqual(stage_spec("check").tools, ())
        self.assertEqual(ADAPTIVE_STAGES["finish"].max_steps, 0)


class PromptStructureTests(unittest.TestCase):
    def test_context_bundle_records_task_interface_and_route(self):
        task = TaskSpec.from_text(
            "t1", "Implement a module named TopModule.\n- input x\n- output z"
        )
        route = SimpleNamespace(public_dict=lambda: {"route": "structural"})
        bundle = ContextBundle.for_task(task, route)
        ids = [section["id"] for section in bundle.sections]
        self.assertEqual(ids, ["task", "interface", "route"])
        self.assertEqual(bundle.sections[0]["content"]["top"], "TopModule")
        self.assertEqual(bundle.sections[2]["content"]["route"], "structural")

    def test_assembly_report_keeps_and_drops(self):
        report = {
            "assembly_id": "a1",
            "messages_sha256": "m1",
            "required_messages_sha256": "r1",
            "packed_tokens": 123,
            "sent": ["skill-a"],
            "pieces": [
                {"id": "skill-a", "status": "included"},
                {"id": "skill-b", "status": "context_limit"},
            ],
        }
        assembly = assembly_from_report("generate", [{"role": "user"}], report)
        self.assertEqual(assembly.kept, ("skill-a",))
        self.assertEqual(assembly.dropped, ("skill-b",))
        self.assertEqual(assembly.tokens, 123)

    def test_record_assembly_emits_event_and_artifact(self):
        with tempfile.TemporaryDirectory() as directory:
            record = Recorder(directory, level="full")
            ctx = SimpleNamespace(record=record)
            report = {
                "assembly_id": "a1", "messages_sha256": "m1",
                "sent": [], "pieces": [], "packed_tokens": 5,
            }
            assembly = record_assembly(ctx, "generate", [{"role": "user"}], report)
            record.close()
            self.assertEqual(assembly.stage, "generate")
            self.assertTrue((record.record_dir / "prompt/a1.json").is_file())
            rows = [
                __import__("json").loads(line)
                for line in (Path(directory) / "trace.jsonl")
                .read_text(encoding="utf-8").splitlines()
            ]
            self.assertTrue(any(
                row["tool"] == "prompt" and row["event"] == "assembly"
                for row in rows
            ))


class ModelProfileTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.record = Recorder(self.directory.name, level="basic")
        self.addCleanup(self.record.close)
        self.config = {
            "backend": "mock",
            "base_url": "http://127.0.0.1:8000/v1",
            "model": "",
            "profiles": {
                "small": {"enabled": True, "model": "tiny-model"},
                "large": {"enabled": False, "model": "large-model"},
            },
        }
        self.client = Client(
            self.config, Budget(60, 5, record=self.record), self.record, {}
        )
        self.addCleanup(self.client.close)

    def test_enabled_profile_selects_its_model(self):
        self.client.chat([{"role": "user", "content": "x"}], profile="small")
        self.assertEqual(self.client.requests[-1]["model"], "tiny-model")

    def test_disabled_profile_falls_back_to_primary(self):
        self.client.chat([{"role": "user", "content": "x"}], profile="large")
        self.assertEqual(self.client.requests[-1]["model"], "mock-model")

    def test_unknown_profile_falls_back_to_primary(self):
        self.client.chat([{"role": "user", "content": "x"}], profile="missing")
        self.assertEqual(self.client.requests[-1]["model"], "mock-model")

    def test_load_config_profile_reaches_request_payload(self):
        from agent.config import load_config

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "profile.yaml"
            path.write_text(
                "workflow: adaptive_verify\n"
                "runtime: {deadline_s: 900, reserve_s: 20}\n"
                "services:\n"
                "  model: {backend: mock, base_url: 'http://127.0.0.1:8000/v1'}\n"
                "  profiles:\n"
                "    small: {enabled: true, model: tiny-model}\n",
                encoding="utf-8",
            )
            config, _ = load_config(path)
            self.assertTrue(config.services.profiles["small"].enabled)
            client = Client(
                config.services.model, Budget(60, 5, record=self.record), self.record,
                {}, profiles=config.services.profiles,
            )
            self.addCleanup(client.close)
            client.chat([{"role": "user", "content": "x"}], profile="small")
            self.assertEqual(client.requests[-1]["model"], "tiny-model")


if __name__ == "__main__":
    unittest.main()
