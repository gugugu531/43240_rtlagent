"""Launch the optional CPU embedding service from the shared runtime config."""

import argparse
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--port", type=int, default=8020)
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args()
    from agent.domain.knowledge.embedding import settings

    config = settings()
    if not args.binary.is_file():
        raise SystemExit("embedding binary is missing")
    if not args.model.is_file():
        raise SystemExit("embedding model is missing")
    if not 1 <= args.port <= 65535:
        raise ValueError("embedding_invalid_port")
    cmd = [
        str(args.binary), "-m", str(args.model),
        "--alias", config["model_alias"],
        "--host", "127.0.0.1", "--port", str(args.port),
        "--embedding", "--pooling", config["pooling"],
        "-c", str(config["max_length"]), "-b", "2048", "-ub", "2048",
        "-np", "1", "-t", "4", "--no-webui",
    ]
    if args.check_only:
        print(json.dumps({
            "status": "passed",
            "model_alias": config["model_alias"],
            "dimensions": config["dimensions"],
            "pooling": config["pooling"],
            "normalization": config["normalization"],
            "command": cmd,
        }))
        return
    env = dict(os.environ)
    env["LD_LIBRARY_PATH"] = str(args.binary.parent) + ":" + env.get("LD_LIBRARY_PATH", "")
    os.execvpe(cmd[0], cmd, env)


if __name__ == "__main__":
    main()
