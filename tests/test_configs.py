"""Every retained configuration must load and be buildable."""

import tempfile
import unittest
from pathlib import Path

import agent.orchestration.nodes  # noqa: F401 - register nodes/tools
import agent.orchestration.workflows  # noqa: F401 - register workflows
from agent.config import load_config
from agent.context.prompts import TemplateRenderer
from agent.domain.rtl.candidate import CandidateStore
from agent.domain.rtl.task import TaskSpec
from agent.observability.recorder import Recorder
from agent.orchestration.graph import build_graph
from agent.tools.registry import WORKFLOWS
from agent.runtime.budget import Budget
from agent.runtime.context import Ctx

ROOT = Path(__file__).resolve().parents[1]
CONFIGS = (
    "single_generate.yaml",
    "guided_verify.yaml",
    "guided_verify_large_v3.yaml",
    "guided_verify_rag_bm25.yaml",
    "guided_verify_rag_dense.yaml",
    "guided_verify_rag_dense_large_v3.yaml",
    "rag97_pregen_bm25.yaml",
    "rag97_pregen_dense.yaml",
    "rag_catalog_v3_shadow.yaml",
)


class ConfigTests(unittest.TestCase):
    def test_only_single_and_guided_workflows_are_registered(self):
        self.assertEqual(set(WORKFLOWS), {"single_generate", "guided_verify"})

    def test_all_retained_configs_load_and_build(self):
        for name in CONFIGS:
            with self.subTest(config=name):
                config, _ = load_config(ROOT / "config" / name, {})
                with tempfile.TemporaryDirectory() as out:
                    record = Recorder(out, level="basic")
                    try:
                        ctx = Ctx(
                            task=TaskSpec.from_text(
                                "config", "module TopModule(input a, output y); assign y=a; endmodule"
                            ),
                            budget=Budget(900, 20, record=record),
                            llm=None,
                            record=record,
                            processes=None,
                            candidates=CandidateStore(record, out),
                            prompts=TemplateRenderer(),
                            config=config,
                        )
                        build_graph(ctx)
                    finally:
                        record.close()

    def test_dense_switch_requires_an_embedding_endpoint(self):
        from agent.orchestration.workflows.guided_verify import GuidedParameters

        with self.assertRaises(ValueError):
            GuidedParameters(retrieval_mode="rag", retrieval_strategy="dense")
        configured = GuidedParameters(
            retrieval_mode="rag",
            retrieval_strategy="dense",
            embedding_url="http://127.0.0.1:8020",
        )
        self.assertEqual(configured.retrieval_strategy, "dense")

    def test_removed_workflow_configs_are_absent(self):
        for name in (
            "adaptive_verify.yaml", "adaptive_dev_900.yaml", "adaptive_hip.yaml",
            "adaptive_tools.yaml", "design_verify_loop.yaml", "repair_loop.yaml",
            "repair_knowledge.yaml", "repair_rag_shadow.yaml", "rag97_feedback_shadow.yaml",
        ):
            self.assertFalse((ROOT / "config" / name).exists(), name)


if __name__ == "__main__":
    unittest.main()
