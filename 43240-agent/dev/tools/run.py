#!/usr/bin/env python3
"""One development entry point for task selection, solving and optional metrics."""
from pathlib import Path
import argparse
import os
import sys
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from agent.core.configuration import load_config,resolve_config,RunOverrides
from dev.tools.experiment import parse_experiment,select_tasks,build_sample_plan,ExperimentRunner,ResolvedExperiment


def main(argv=None):
    parser = argparse.ArgumentParser(description='统一实验入口')
    parser.add_argument('--config',type=Path,required=True)
    parser.add_argument('--task')
    parser.add_argument('--workflow')
    parser.add_argument('--modes',nargs='+')
    parser.add_argument('--metrics',nargs='*')
    parser.add_argument('--samples',type=int)
    parser.add_argument('--solve-jobs',type=int)
    parser.add_argument('--metric-jobs',type=int)
    parser.add_argument('--tag')
    args = parser.parse_args(argv)
    try:
        overrides = RunOverrides({'workflow.type':args.workflow} if args.workflow else {})
        config = resolve_config(load_config(args.config),env=os.environ,overrides=overrides)
        fields = ('task','modes','metrics','samples','solve_jobs','metric_jobs','tag')
        exp = parse_experiment(config,{key:tuple(getattr(args,key)) if key in ('modes','metrics') else getattr(args,key)
                                      for key in fields if getattr(args,key) is not None})
        manifest = select_tasks(exp.selection); plan = build_sample_plan(manifest,exp)
        result = ExperimentRunner().run(plan,ResolvedExperiment(config,exp,manifest))
        print(result.output_dir); print(result.status)
        return 130 if result.status=='cancelled' else 0
    except Exception as exc:
        # Configuration errors can include parser/provider values; only expose the type.
        from agent.core.configuration import ConfigError
        print(str(exc) if isinstance(exc,ConfigError) else f'experiment failed ({type(exc).__name__})',file=sys.stderr)
        return 2


if __name__=='__main__': raise SystemExit(main())
