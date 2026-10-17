"""Bounded E2 repair depth and independent candidate width comparisons."""
from dataclasses import dataclass, replace
import hashlib
import re
import time

from agent.core.budget import BudgetExhausted
from agent.core.model import ModelCallError, ModelRequest
from agent.core.registry import NODE_REGISTRY, WORKFLOW_REGISTRY, build_node
from agent.core.replay import load_initial, save_initial, runtime_hashes, task_hash, digest
from agent.recording.artifacts import atomic_write_json
from agent.nodes.extract import ExtractInput
from agent.nodes.generate import GenerateNode, GenerateInput
from agent.workflows.evidence_ablation import EvidenceAblation
from agent.workflows.checks import candidate_checks


@NODE_REGISTRY.register('seeded_generate')
@dataclass(frozen=True)
class SeededGenerate(GenerateNode):
    base_seed: int = 20261013

    def __post_init__(self):
        super().__post_init__()
        ModelRequest([], seed=self.base_seed)
        ModelRequest([], seed=self.base_seed + 2)

    def run(self, ctx, input):
        return super().run(ctx, replace(input, seed=self.base_seed + input.round - 1))


def normalize_tool_paths(summary):
    # Only Agent-owned tool scratch directories. Raw checks/logs stay untouched.
    return re.sub(r'/[^\s\[\]\'\"]*/agent_(?:lint|synth)_[A-Za-z0-9_-]+', '<tool-work>', summary)


class SearchAblation(EvidenceAblation):
    limit = 2
    strategy = 'repair'

    def __init__(self, initial_state=None, base_seed=20261013, temperature=0.6, top_p=0.95,
                 corpus_path=None):
        super().__init__(initial_state, corpus_path=corpus_path)
        self.max_rounds = self.max_model_calls = self.limit
        self.max_request_retries = 0
        self._prefix_ready = False
        self._source = None
        self.generate = build_node('seeded_generate', base_seed=base_seed, max_tokens=8192,
                                   temperature=temperature, top_p=top_p, timeout_s=300.0,
                                   prompt_style='repair', use_skills=False)

    def build_check_feedback(self, ctx, checks):
        normalized = [replace(c, summary=normalize_tool_paths(c.summary)) for c in checks]
        return super().build_check_feedback(ctx, normalized)

    def save_stop_after_two(self, ctx, reason):
        """Solver-only view of stopping now; never restores or invokes the model."""
        path = ctx.output_dir / 'stop_after_two.json'
        if self.limit != 3 or not self._prefix_ready or path.exists():
            return
        initial = self._initial_checkpoint
        initial_sha256 = initial['sha256'] if 'sha256' in initial else digest(initial)
        elapsed = time.monotonic() - ctx.started_at
        branch_wall_s = max(0.0, elapsed - (initial['initial_wall_s'] if not self._source else 0))
        selected = ctx.state.candidates.get(ctx.state.selected_candidate_id)
        data = dict(schema_version=1, source_workflow=self._registration_name,
            task_hash=task_hash(ctx.task), runtime_hashes=runtime_hashes(), service=dict(ctx.llm.backend.describe()),
            initial_sha256=initial_sha256, shared_initial_wall_s=initial['initial_wall_s'],
            branch_wall_s=branch_wall_s, requests=ctx.llm.requests,
            tokens=ctx.llm.tokens.snapshot(), candidate_ids=list(ctx.state.candidates),
            selected_candidate_id=selected.id if selected else None, code=selected.code if selected else '',
            stop_reason=reason)
        # Candidate.code_hash uses SHA256 over UTF-8, including the empty answer.
        data['code_sha256'] = hashlib.sha256(data['code'].encode()).hexdigest()
        data['sha256'] = digest(data)
        atomic_write_json(path, data)
        ctx.emit('stop_after_two', sha256=data['sha256'], calls=data['tokens']['calls'],
                 selected_candidate_id=data['selected_candidate_id'], path=str(path))

    def restore(self, ctx):
        result = super().restore(ctx)
        self._prefix_ready = self._initial_checkpoint is not None
        return result

    def capture_initial(self, ctx, reply, result, checks, reason):
        if self.limit == 3 and not self._source and self._initial_checkpoint is None:
            self._initial_checkpoint = save_initial(ctx.output_dir / 'initial.json', ctx, reply,
                                                    result, checks, reason, self._identity)
            self._prefix_ready = True

    def after_round(self, ctx, reply, result, checks, choice, round):
        super().after_round(ctx, reply, result, checks, choice, round)
        if round == 1:
            self.capture_initial(ctx, reply, result, checks, choice.reason)
        if round == 2:
            reason = 'model_call_limit' if choice.action == 'repair' else choice.reason
            self.save_stop_after_two(ctx, 'verification_unavailable' if reason == 'environment' else reason)

    def run(self, ctx):
        configured = getattr(ctx, 'configuration', {}).get('effective', {}).get('runtime', {}).get('initial_state')
        self._source = self.initial_state or configured
        try:
            if self.strategy != 'candidates':
                return super().run(ctx)
            return self.run_candidates(ctx)
        finally:
            if ctx.llm.tokens.snapshot()['calls'] <= 2:
                self.save_stop_after_two(ctx, ctx.state.stop_reason or 'candidate_limit')

    def run_candidates(self, ctx):
        source = self._source
        if source:
            data, reply, result, checks = load_initial(source, ctx, self.extract)
            self._initial_checkpoint = data
            self._prefix_ready = True
            ctx.apply_selection(self.choose(ctx.state))
            round_start = data['tokens']['calls'] + 1
            if checks and checks[-1].classify() in ('environment', 'unknown', 'timeout'):
                return ctx.finish(reason=checks[-1].classify(), status='stopped')
        else:
            self._identity = ctx.tools.identify()
            round_start = 1
        for round in range(round_start, self.limit + 1):
            if round == 3:
                self.save_stop_after_two(ctx, 'candidate_limit')
            try:
                ctx.budget.timeout_s(300.0)
                reply = ctx.execute(self.generate, GenerateInput(ctx.task, round=round))
            except BudgetExhausted:
                return ctx.finish(reason='deadline', status='stopped')
            except ModelCallError as exc:
                return ctx.finish(reason=f'model_{exc.kind}', status='stopped')
            result = ctx.execute(self.extract, ExtractInput(reply, round, source_stage='generate'))
            if result.candidate is None:
                if round == 1:
                    self.capture_initial(ctx, reply, result, [], 'extraction')
                continue
            ctx.apply_selection(self.choose(ctx.state))
            checks = []
            try:
                for check in candidate_checks(ctx, result.candidate, interface=self.interface,
                                               lint=self.lint, synth=self.synth):
                    checks.append(check)
                    ctx.apply_selection(self.choose(ctx.state))
                if check.classify() in ('environment', 'unknown', 'timeout'):
                    if round == 1:
                        self.capture_initial(ctx, reply, result, checks, check.classify())
                    return ctx.finish(reason=check.classify(), status='stopped')
            except BudgetExhausted:
                if round == 1:
                    self.capture_initial(ctx, reply, result, checks, 'deadline')
                return ctx.finish(reason='deadline', status='stopped')
            if round == 1:
                self.capture_initial(ctx, reply, result, checks, self.choose(ctx.state).reason)
        return ctx.finish(reason='candidate_limit')


@WORKFLOW_REGISTRY.register('search_initial')
class SearchInitial(SearchAblation):
    arm = 'A0'
    limit = 1


@WORKFLOW_REGISTRY.register('search_r1')
class SearchRepairOnce(SearchAblation):
    pass


@WORKFLOW_REGISTRY.register('search_r2')
class SearchRepairTwice(SearchAblation):
    limit = 3


@WORKFLOW_REGISTRY.register('search_r2_guided')
class SearchGuidedRepairTwice(SearchRepairTwice):
    arm = 'A2'


@WORKFLOW_REGISTRY.register('search_c2')
class SearchTwoCandidates(SearchAblation):
    strategy = 'candidates'


@WORKFLOW_REGISTRY.register('search_c3')
class SearchThreeCandidates(SearchAblation):
    strategy = 'candidates'
    limit = 3
