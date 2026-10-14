#!/usr/bin/env python3
"""本来源的导入入口；由datasets.py docs生成。"""
from pathlib import Path
import subprocess
import sys

repo = next(p for p in Path(__file__).resolve().parents if (p/'43240-agent/dev/tools/datasets.py').is_file())
raise SystemExit(subprocess.call([sys.executable, str(repo/'43240-agent/dev/tools/datasets.py'),
                                  'convert', '--dataset', 'example', *sys.argv[1:]]))
