"""Reuse the raw-request batch auditor with batch-49 paths and call limits."""
import argparse
import inspect
import sys
from pathlib import Path

from common49 import HERE, ROOT, load, save, validate

sys.path.insert(0, str(ROOT / 'dev/optimization-v45'))
import audit45

audit45.HERE = HERE
audit45.validate = validate


def run(host, directory, output):
    source = inspect.getsource(audit45.run).replace('calls!=8', 'calls!=20')
    exec(compile(source, '<batch49-auditor>', 'exec'), audit45.__dict__)
    audit45.run(host, directory, output)
    result = load(output)
    result['boundary'] = (
        'Twenty fixed-card repair screens reuse declared historical mechanical contexts with new seeds. '
        'They test current rendering risk and delivery, not production retrieval, automatic routing, or independent-context generalization.'
    )
    result['promotion_rule'] = (
        'A passing pair may add current-rendering model-screen evidence while the card remains shadow. '
        'Restricted routing additionally requires a bounded predicate, refusal tests and actual routed-request validation.'
    )
    save(output, result)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--host', type=int, required=True)
    parser.add_argument('--directory', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    run(args.host, args.directory, args.output)
