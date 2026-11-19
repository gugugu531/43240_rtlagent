"""Directory protocol entry point with one in-process Burr application."""

from __future__ import annotations
import argparse
import hashlib
import math
import os
from pathlib import Path
import signal
import shutil
import time


def positive_seconds(value):
    seconds = float(value)
    if not math.isfinite(seconds) or seconds <= 0:
        raise argparse.ArgumentTypeError("deadline must be positive and finite")
    return seconds


def main(argv=None):
    started = time.monotonic()
    parser = argparse.ArgumentParser(description="Burr RTL workflows")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=os.environ.get("AGENT_CONFIG"))
    parser.add_argument("--top", default=os.environ.get("RTL_TOP", ""))
    parser.add_argument("--deadline-s", type=float)
    parser.add_argument("--hard-deadline-s", type=positive_seconds)
    parser.add_argument("--reserve-s", type=float)
    parser.add_argument("--record-root", type=Path)
    parser.add_argument("--record-level", choices=("basic", "full"))
    args = parser.parse_args(argv)
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "solution.v").write_text("", encoding="utf-8")
    from agent.observability.recorder import Recorder
    from agent.runtime.budget import Budget, BudgetExhausted, Deadline

    record = Recorder(args.output, level="basic")
    processes = llm = ctx = config = None
    summary = {}
    model_error_type = ()
    status, reason = "error", "initialization_error"
    old_handlers = {}

    def arm_deadline():
        # Re-arm long deadlines without overflowing the platform timer.
        remaining = budget.remaining_s(include_reserve=True)
        signal.setitimer(signal.ITIMER_REAL, min(86400.0, max(0.001, remaining)))

    def interrupt(signum, frame):
        if signum == signal.SIGALRM and budget.remaining_s(include_reserve=True) > 0:
            arm_deadline()
            return
        raise Deadline("deadline" if signum == signal.SIGALRM else "cancelled")

    try:
        from agent.config import load_config, ROOT

        overrides = {}
        for flag, field in [
            ("deadline_s", "runtime.deadline_s"),
            ("reserve_s", "runtime.reserve_s"),
            ("record_root", "runtime.recording.root"),
            ("record_level", "runtime.recording.level"),
        ]:
            value = getattr(args, flag)
            if value is not None:
                overrides[field] = (
                    str(value.resolve()) if isinstance(value, Path) else value
                )
        config, evidence = load_config(args.config, overrides)
        configured_record = Recorder(
            args.output,
            level=config.runtime.recording.level,
            root=config.runtime.recording.root,
            secrets=[config.services.model.api_key],
        )
        record.close()
        record = configured_record
        deadline = config.runtime.deadline_s
        if args.hard_deadline_s is not None:
            deadline = min(deadline, args.hard_deadline_s)
        budget = Budget(
            deadline,
            min(config.runtime.reserve_s, max(0, deadline - 0.001)),
            started_at=started,
            record=record,
        )
        for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGALRM):
            old_handlers[sig] = signal.signal(sig, interrupt)
        arm_deadline()
        record.emit(
            "run", "start", input=str(args.input.resolve()), source_root=str(ROOT)
        )
        record.emit(
            "run", "config", configuration=evidence, record_dir=str(record.record_dir)
        )
        record.emit(
            "budget", "configured", configured_s=config.runtime.deadline_s,
            external_limit_s=args.hard_deadline_s, effective_s=deadline,
            reserve_s=budget.reserve_s,
        )
        record.write_json("configuration.json", evidence)
        from agent.runtime.process import ProcessManager

        processes = ProcessManager(budget, record)
        revision = changes = None
        if shutil.which("git") and (ROOT / ".git").exists():
            revision = processes.run(
                ["git", "rev-parse", "HEAD"], cwd=ROOT, timeout_s=5
            )
            changes = processes.run(
                ["git", "status", "--porcelain"], cwd=ROOT, timeout_s=5
            )
        hashes = {
            str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
            for directory in ("agent", "config", "skill", "knowledge")
            for p in sorted((ROOT / directory).rglob("*"))
            if p.is_file() and "__pycache__" not in p.parts
        }
        for name in ("manifest.json", "baseline.py", "run.sh", "requirements.txt"):
            hashes[name] = hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
        plugins = {
            str(Path(path).resolve()): hashlib.sha256(
                Path(path).read_bytes()
            ).hexdigest()
            for path in config.plugins
        }
        record.write_json(
            "source.json",
            dict(
                revision=revision.stdout.strip()
                if revision and revision.rc == 0
                else None,
                changes=changes.stdout if changes and changes.rc == 0 else None,
                files=hashes,
                plugins=plugins,
            ),
        )
        from agent.tools.registry import load_plugins
        from agent.orchestration.graph import run_graph
        from agent.runtime.context import Ctx
        from agent.domain.rtl.task import TaskSpec
        from agent.domain.rtl.candidate import CandidateStore
        from agent.llm.client import Client, ModelError

        model_error_type = ModelError
        from agent.context.prompts import TemplateRenderer
        from baseline import load_generation
        import agent.orchestration.nodes  # noqa: F401 - register built-in nodes
        import agent.orchestration.workflows  # noqa: F401 - register built-in workflows

        load_plugins(config.plugins)
        task = TaskSpec.from_directory(
            args.input, task_id=os.environ.get("AGENT_TASK_ID"), top=args.top
        )
        record.write_json(
            "task.json", dict(task_id=task.id, prompt=task.prompt, top=task.top)
        )
        llm = Client(
            config.services.model, budget, record, load_generation(),
            profiles=config.services.profiles,
        )
        ctx = Ctx(
            task=task,
            budget=budget,
            llm=llm,
            record=record,
            processes=processes,
            candidates=CandidateStore(record, args.output),
            prompts=TemplateRenderer(),
            config=config,
        )
        llm.tool_dispatch = ctx.dispatch
        state = run_graph(ctx)
        llm.assert_replay_consumed()
        status, reason = (
            state.get("status", "completed"),
            state.get("stop_reason", "completed"),
        )
    except (Deadline, BudgetExhausted) as exc:
        status, reason = "stopped", str(exc) or "deadline"
        record.emit("budget", "stopped", reason=reason)
    except Exception as exc:
        status, reason = (
            ("stopped", f"model_{exc.kind}")
            if isinstance(exc, model_error_type)
            else ("error", f"{type(exc).__name__}: {exc}")
        )
        record.emit("run", "failed", error_type=type(exc).__name__, error=str(exc))
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        # Ignore repeated cancellation while reclaiming only this task's groups.
        for sig in old_handlers:
            signal.signal(sig, signal.SIG_IGN)
        try:
            if processes:
                processes.close()
            if llm:
                llm.close()
            gateway = ctx.store.get("submission") if ctx else None
            if gateway is not None:
                try:
                    gateway.finalize(reason if gateway.state.policy == "author_decides" else "run_end")
                except Exception as error:
                    record.emit(
                        "submission", "finalize_failed", rc=1,
                        error_type=type(error).__name__, error=str(error),
                        excerpt="submission finalize failed",
                    )
            elif (config and config.workflow == "guided_verify"
                  and not (args.output / "solution.v").stat().st_size):
                # A deadline can interrupt entry setup before the first graph step.
                record.emit("submission", "finalized", policy="author_decides", mode="fallback",
                            target_id=None, code_hash=None, selected_id=None, overrode_selected=False,
                            published=False, delivery="empty", reason=reason,
                            fallback_basis="no_complete_candidate", structure_status="not_checked")
            if ctx or (config and config.workflow == "guided_verify"):
                from agent.domain.knowledge.outcome import summarize
                summary = summarize(args.output / 'trace.jsonl', args.output / 'solution.v')
                record.write_json('framework-outcome.json', summary)
                record.emit('knowledge', 'outcome', **summary)
            record.emit(
                "run",
                "end",
                status=status,
                stop_reason=reason,
                candidate_id=summary.get("published_candidate_id"),
                published_id=summary.get("published_candidate_id"),
                published_sha256=summary.get("published_candidate_sha256"),
                submission_mode=summary.get("submission_mode"),
                submission_reason=summary.get("submission_reason"),
                submission_finalized=summary.get("submission_finalized"),
                fallback_basis=summary.get("fallback_basis"),
                submission_structure_status=summary.get("submission_structure_status"),
                selected_id=summary.get("selected_candidate_id"),
                selected_sha256=summary.get("selected_candidate_sha256"),
                elapsed_s=time.monotonic() - started,
                **(
                    llm.usage_summary()
                    if llm
                    else {"calls": 0, "tokens_in": None, "tokens_out": None}
                ),
            )
        finally:
            record.close()
            for sig, handler in old_handlers.items():
                signal.signal(sig, handler)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
