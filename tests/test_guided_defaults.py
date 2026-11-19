"""Default guided routing and context boundaries, using only in-memory HTTP."""

from contextlib import nullcontext
import copy
import json
import os
from pathlib import Path
from types import SimpleNamespace
from tempfile import TemporaryDirectory
from agent.domain.rtl.candidate import CandidateStore
import unittest
from unittest.mock import patch

import httpx

from agent.config import load_config
from agent.context.prompts import TemplateRenderer
from agent.domain.knowledge import guided as knowledge
from agent.domain.rtl.task import TaskSpec
from agent.kit import State
from agent.llm.client import Client
from agent.orchestration.nodes import guided
from agent.orchestration.workflows.guided_verify import GuidedParameters
from agent.runtime.budget import Budget
from serve import serve_api


class MemoryRecord:
    def __init__(self):
        self.artifacts = {}

    def emit(self, *args, **kwargs):
        pass

    def scope(self):
        return nullcontext()

    def write_json(self, name, value):
        self.artifacts[name] = copy.deepcopy(value)
        return name

    def write_text(self, name, value):
        self.artifacts[name] = value
        return name


class GuidedDefaultTests(unittest.TestCase):
    def setUp(self):
        self.environment = patch.dict(os.environ, {}, clear=True)
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def test_cli_and_http_resolve_same_default_and_effective_overrides(self):
        config, evidence = load_config()
        service, path = serve_api._service_config()
        self.assertEqual(Path(evidence["path"]), path)
        self.assertEqual(config.model_dump(), service.model_dump())
        self.assertEqual(config.workflow, "guided_verify")
        self.assertEqual(config.params["retrieval_mode"], "off")
        self.assertFalse(any(p.enabled for p in config.services.profiles.values()))

        # An explicit local serving override must still reach both entry points.
        with patch.dict(os.environ, {"LLM_BASE_URL": "http://127.0.0.1:8123/v1",
                                     "LLM_MODEL": "test-explicit-alias"}):
            cli, _ = load_config()
            http, _ = serve_api._service_config()
        self.assertEqual(cli.services.model, http.services.model)
        self.assertEqual(cli.services.model.base_url, "http://127.0.0.1:8123/v1")
        self.assertEqual(http.services.model.model, "test-explicit-alias")

    def test_real_guided_stages_share_model_but_not_conversation_history(self):
        config, _ = load_config()
        settings = GuidedParameters(**config.params).model_dump()
        record = MemoryRecord()
        budget = Budget(config.runtime.deadline_s, config.runtime.reserve_s)
        requests = []
        answers = {
            "guided_plan": (
                "method=table\nskills=rtl-sequential-state-update\n"
                "knowledge=unavailable-card\nfocus=reset\n"
                "reason=PRIVATE_PLANNER_RESPONSE"
            ),
            "guided_solve": (
                "module TopModule(input clk, input reset, output reg q);\n"
                "// PRIVATE_CANDIDATE_RESPONSE\n"
                "always @(posedge clk) if (reset) q <= 0; else q <= ~q;\n"
                "endmodule"
            ),
            "guided_checker": "case reset # Reset clears q and the next edge toggles it.\ninit reset=1 q=0\nstep reset=0 q=1\n",
        }

        def transport(request):
            payload = json.loads(request.content) if request.content else None
            requests.append((str(request.url), copy.deepcopy(payload)))
            if request.url.path == "/apply-template":
                return httpx.Response(200, json={"prompt": "test-rendered-prompt"})
            if request.url.path == "/tokenize":
                return httpx.Response(200, json={"tokens": [1, 2, 3]})
            self.assertEqual(request.url.path, "/v1/chat/completions")
            purpose = request.extensions["purpose"]
            return httpx.Response(200, json={
                "model": payload["model"],
                "choices": [{"message": {"role": "assistant", "content": answers[purpose]},
                             "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 3, "completion_tokens": 20},
            })

        llm = Client(config.services.model, budget, record, {},
                     transport=httpx.MockTransport(transport),
                     profiles=config.services.profiles)
        self.addCleanup(llm.close)
        # Stored evidence is deliberately hostile to implicit history replay.
        llm.requests.append({"messages": [{"role": "assistant", "content": "PRIVATE_OLD_LOG"}]})
        task = TaskSpec.from_text("independent-context", """Implement a module named TopModule.
 - input clk
 - input reset
 - output q
On each positive clock edge, reset sets q to 0; otherwise q toggles.""")
        ctx = SimpleNamespace(
            task=task, llm=llm, record=record, budget=budget,
            prompts=TemplateRenderer(),
            store={},
        )
        output = TemporaryDirectory()
        self.addCleanup(output.cleanup)
        ctx.candidates = CandidateStore(record, output.name)
        guided.initialize(ctx, State({"settings": settings}))
        with patch.object(knowledge, "load_cards", side_effect=AssertionError("RAG read")), \
             patch.object(knowledge, "card_map", side_effect=AssertionError("RAG map")), \
             patch.object(knowledge, "dense_rank", side_effect=AssertionError("embedding call")):
            state = guided.plan(ctx, State())
            state = guided.solve(ctx, state)
            state = guided.build_checker(ctx, state)

        self.assertEqual(state["target_id"], ctx.candidates.values()[0].id)
        self.assertEqual(state["checker_status"], "valid")
        self.assertEqual(ctx.store["guided"]["plan"]["knowledge"], [])
        completions = [(url, body) for url, body in requests if url.endswith("/chat/completions")]
        self.assertEqual(len(completions), 3)
        for url, body in completions:
            self.assertEqual(url, "http://127.0.0.1:8000/v1/chat/completions")
            self.assertEqual(body["model"], "qwen38-27b-q4-k-m")
            self.assertEqual([m["role"] for m in body["messages"]], ["system", "user"])
            self.assertNotIn("PRIVATE_OLD_LOG", json.dumps(body))
        self.assertTrue(all(":8011/" not in url for url, _ in requests))
        plan, solve, checker = [body for _, body in completions]
        self.assertIn("rtl-sequential-state-update", json.dumps(plan))
        self.assertIn("[Skill rtl-sequential-state-update]", json.dumps(solve))
        self.assertNotIn("PRIVATE_PLANNER_RESPONSE", json.dumps(solve))
        self.assertNotIn("PRIVATE_PLANNER_RESPONSE", json.dumps(checker))
        self.assertNotIn("PRIVATE_CANDIDATE_RESPONSE", json.dumps(checker))
        self.assertEqual(llm.usage_summary()["calls"], 3)

    def test_off_shortlist_never_loads_cards_or_embeddings_but_keeps_skills(self):
        config, _ = load_config()
        for strategy in ("bm25", "dense"):
            with self.subTest(strategy=strategy):
                settings = GuidedParameters(**config.params).model_dump()
                settings.update(retrieval_strategy=strategy,
                                embedding_url="http://127.0.0.1:8020")
                ctx = SimpleNamespace(
                    task=SimpleNamespace(prompt="A resettable counter", interface=""),
                    record=MemoryRecord(), store={"guided": {"settings": settings}},
                )
                with patch.object(knowledge, "load_cards", side_effect=AssertionError("card read")), \
                     patch.object(knowledge, "load_vectors", side_effect=AssertionError("vector read")), \
                     patch.object(knowledge, "dense_rank", side_effect=AssertionError("embedding call")):
                    skills, cards = guided._shortlist(ctx, 5)
                self.assertIn("rtl-sequential-state-update", dict(skills))
                self.assertEqual(cards, [])
                self.assertEqual(ctx.store["guided"]["retrieval"]["reason"], "disabled")
                resources = ctx.store["guided"]["skill_assets"]["resources"]
                self.assertTrue(resources)
                self.assertTrue(all(path.startswith("skill/") for path in resources))
