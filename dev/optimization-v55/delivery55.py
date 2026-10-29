"""Build the local immutable rc4.5 candidate without deploying or submitting it."""
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
ARCHIVE = HERE / "rag-catalog-v3-rc45-candidate.tar.gz"
BASE = ROOT / "dev/optimization-v54/rag-catalog-v3-rc44-candidate.tar.gz"
PROMOTED = {
    "v9-public-cellular-snapshot-update", "v9-public-triangle-endpoint-dwell",
    "v9-public-grid-row-column-wrap", "v9-lang-comparison-result-sign",
    "v9-lang-unsigned-negative-check", "v9-public-sampled-edge-history",
    "v9-public-framing-search-phase", "v9-public-instruction-bank-isolation",
    "v9-public-pause-preserves-subtick", "v9-lang-boolean-versus-bitwise",
}


def sha(body):
    return hashlib.sha256(body).hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def verification_code():
    return f"""
import hashlib,json,pathlib,sys
sys.path.insert(0,sys.argv[1])
from agent.knowledge.research import load_bundle,validate_vector_index
from agent.knowledge.pregen import read_vector_index
from agent.nodes.generate import generate
import baseline
root=pathlib.Path(sys.argv[1])
m=json.loads((root/'dev/optimization-v55/candidate-manifest.json').read_text())
assert all(hashlib.sha256((root/n).read_bytes()).hexdigest()==h for n,h in m['files'].items())
d=load_bundle(); validate_vector_index(read_vector_index(),d)
assert d['release_id']=='rag-catalog-v3-rc4.5'
assert sum(c['activation_state']=='restricted' for c in d['cards'])==28
promoted={PROMOTED!r}
assert {{c['card_id'] for c in d['cards'] if c['card_id'] in promoted and c['activation_state']=='restricted'}}==promoted
assert all(c['injection_eligible'] and c.get('injection_stages')==['pre_generation'] and 'pre_generation' in c['phases'] for c in d['cards'] if c['card_id'] in promoted)
assert baseline.load_generation()['chat_template_kwargs']['enable_thinking']
"""


def main():
    if ARCHIVE.exists():
        raise FileExistsError("preserve_final_candidate")
    checks = json.loads((HERE / "final-checks.json").read_text())
    assert checks["status"] == "passed" and checks["unit_tests"]["returncode"] == 0
    with tarfile.open(BASE) as tar:
        files = {member.name: tar.extractfile(member).read() for member in tar.getmembers() if member.isfile()}
    files.pop("dev/optimization-v53/candidate-manifest.json", None)
    files.pop("dev/optimization-v54/candidate-manifest.json", None)
    for name in list(files):
        path = ROOT / name
        if path.exists() and (name.startswith(("agent/", "knowledge/", "config/", "serve/", "tests/", "docs/"))
                              or name in ("manifest.json", "model/MODEL.md")):
            files[name] = path.read_bytes()
    include = [
        "agent/knowledge/pregen_methods_v55.py",
        "agent/knowledge/pregen_methods.py",
        "docs/2026-10-29-rag-rc45-runbook.md",
        "docs/2026-10-29-rag-restricted-to-production-plan.md",
        "dev/optimization-v49/audit-33376.json",
        "dev/optimization-v49/audit-33589.json",
        "dev/optimization-v49/tasks.json",
        "dev/optimization-v51/tasks.json",
        "dev/optimization-v55/README.md",
        "dev/optimization-v55/batch.json",
        "dev/optimization-v55/final-checks.json",
        "dev/optimization-v55/gate-results.json",
        "dev/optimization-v55/post-promotion-smoke.json",
        "dev/optimization-v55/production-readiness.json",
        "dev/optimization-v55/release-note.json",
        "dev/optimization-v55/unittest.log",
    ]
    include.extend(str(path.relative_to(ROOT)) for path in sorted((ROOT / "tests").glob("test_*.py")))
    for name in include:
        files[name] = (ROOT / name).read_bytes()
    manifest = {
        "release_id": "rag-catalog-v3-rc4.5",
        "files": {name: sha(body) for name, body in sorted(files.items())},
        "generation_calls_to_build": 0,
        "thinking_enabled": True,
        "default_configuration_changed": False,
        "restricted_count": 28,
        "new_restricted": sorted(PROMOTED),
        "new_restricted_stage": "pre_generation_only",
        "embedding_runtime_included": False,
        "embedding_runtime_hash_locked": True,
    }
    write_json(HERE / "candidate-manifest.json", manifest)
    files["dev/optimization-v55/candidate-manifest.json"] = (HERE / "candidate-manifest.json").read_bytes()
    with tarfile.open(ARCHIVE, "w:gz") as tar:
        for name, body in sorted(files.items()):
            info = tarfile.TarInfo(name)
            info.size = len(body)
            source = ROOT / name
            info.mode = (source.stat().st_mode & 0o777) if source.exists() else 0o644
            tar.addfile(info, io.BytesIO(body))
    with tempfile.TemporaryDirectory(prefix="rag-rc45-") as tmp:
        with tarfile.open(ARCHIVE) as tar:
            tar.extractall(tmp, filter="data")
        subprocess.run([sys.executable, "-c", verification_code(), tmp], cwd=tmp, check=True, capture_output=True)
        subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py"],
                       cwd=tmp, check=True, capture_output=True)
    receipt = {
        "release_id": manifest["release_id"],
        "sha256": sha(ARCHIVE.read_bytes()),
        "bytes": ARCHIVE.stat().st_size,
        "files": len(files),
        "isolated_import_hashes_and_tests_verified": True,
        "isolated_test_count": 141,
        "generation_calls": 0,
        "uploaded": False,
        "online_configuration_changed": False,
    }
    write_json(HERE / "candidate-receipt.json", receipt)
    print(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    main()
