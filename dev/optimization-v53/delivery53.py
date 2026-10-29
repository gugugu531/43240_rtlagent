"""Build and optionally deploy the immutable rc4.3 delivery candidate."""
import argparse
import io
import json
from pathlib import Path
import shlex
import subprocess
import sys
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(ROOT / "dev/optimization-v42"), str(ROOT)]
from common42 import load, save, sha


ARCHIVE_NAME = "rag-catalog-v3-rc43-candidate.tar.gz"
REMOTE_ROOT = "/root/rtl-rag-catalog-v3-rc43-20261029"
PROMOTED = {
    "v9-lang-context-before-operation",
    "v9-public-batch-final-sample",
    "v9-public-block-carry-chain",
}


def verification_code(manifest_path):
    return f"""
import hashlib,json,os,pathlib,sys
sys.path.insert(0,sys.argv[1])
from agent.knowledge.research import load_bundle,validate_vector_index
from agent.knowledge.pregen import read_vector_index
from agent.nodes.generate import generate
import baseline
root=pathlib.Path(sys.argv[1])
m=json.loads((root/{manifest_path!r}).read_text())
assert all(hashlib.sha256((root/n).read_bytes()).hexdigest()==h for n,h in m['files'].items())
d=load_bundle();validate_vector_index(read_vector_index(),d)
assert d['release_id']=='rag-catalog-v3-rc4.3'
assert sum(c['activation_state']=='restricted' for c in d['cards'])==8
promoted={PROMOTED!r}
assert {{c['card_id'] for c in d['cards'] if c['card_id'] in promoted and c['activation_state']=='restricted'}}==promoted
assert all(c.get('injection_stages')==['pre_generation'] for c in d['cards'] if c['card_id'] in promoted)
assert baseline.load_generation()['chat_template_kwargs']['enable_thinking']
assert all(os.access(root/n,os.X_OK) for n in ('run.sh','run_baseline.sh'))
"""


def build():
    archive = HERE / ARCHIVE_NAME
    if archive.exists():
        raise FileExistsError("preserve_final_candidate")
    checks = load(HERE / "final-checks.json")
    assert checks["status"] == "passed" and checks["unit_tests"]["returncode"] == 0
    with tarfile.open(ROOT / "dev/optimization-v48/rag-catalog-v3-rc42-candidate.tar.gz") as tar:
        files = {member.name: tar.extractfile(member).read() for member in tar.getmembers() if member.isfile()}
    files.pop("dev/optimization-v48/candidate-manifest.json", None)
    for name in list(files):
        path = ROOT / name
        if path.exists() and (name.startswith(("agent/", "knowledge/", "config/", "serve/", "tests/"))
                              or name in ("manifest.json", "model/MODEL.md")):
            files[name] = path.read_bytes()
    include = [
        "docs/2026-10-28-rag-final-day-batch-and-embedding-plan.md",
        "docs/2026-10-28-rag-handoff.md",
        "docs/2026-10-29-rag-97-readiness.md",
        "docs/2026-10-29-rag-catalog-v3-runbook.md",
        "docs/2026-10-29-rag-rc42-runbook.md",
        "dev/optimization-v49/audit-33589.json",
        "dev/optimization-v51/tasks.json",
        "dev/optimization-v4/thinking-staged.yaml",
        "dev/optimization-v25/retrieval-queries.json",
        "dev/optimization-v26/examples.py",
        "dev/optimization-v26/local_checks.py",
        "dev/optimization-v28/admission.py",
        "dev/optimization-v28/fixtures.py",
        "dev/optimization-v32/card-overrides.json",
        "dev/optimization-v32/common.py",
        "dev/optimization-v32/fixtures.py",
        "dev/optimization-v32/policy.py",
        "dev/optimization-v32/query_projection.py",
        "dev/optimization-v35/campaign.json",
        "dev/optimization-v35/cards.json",
        "dev/optimization-v35/night.py",
        "dev/optimization-v35/night_queue.py",
        "dev/optimization-v35/tasks.json",
        "dev/optimization-v53/README.md",
        "dev/optimization-v53/audit53.py",
        "dev/optimization-v53/batch.json",
        "dev/optimization-v53/final-checks.json",
        "dev/optimization-v53/model-audit-summary.json",
        "dev/optimization-v53/post-promotion-smoke.json",
        "dev/optimization-v53/release-note.json",
        "dev/optimization-v53/route-results.json",
        "dev/optimization-v53/routed-audit-33376.json",
        "dev/optimization-v53/routed-audit-33589.json",
        "dev/optimization-v53/tokenizer-results.json",
        "dev/optimization-v53/unittest.log",
    ]
    include.extend(str(path.relative_to(ROOT)) for path in sorted((ROOT / "tests").glob("test_*.py")))
    for name in include:
        files[name] = (ROOT / name).read_bytes()
    manifest = {
        "release_id": "rag-catalog-v3-rc4.3",
        "files": {name: sha(body) for name, body in files.items()},
        "generation_calls_to_build": 0,
        "thinking_enabled": True,
        "default_configuration_changed": False,
        "restricted_count": 8,
        "new_restricted": sorted(PROMOTED),
        "new_restricted_stage": "pre_generation_only",
        "embedding_runtime_included": False,
        "embedding_runtime_hash_locked": True,
    }
    save(HERE / "candidate-manifest.json", manifest)
    files["dev/optimization-v53/candidate-manifest.json"] = (HERE / "candidate-manifest.json").read_bytes()
    with tarfile.open(archive, "w:gz") as tar:
        for name, body in sorted(files.items()):
            info = tarfile.TarInfo(name)
            info.size = len(body)
            info.mode = (ROOT / name).stat().st_mode & 0o777
            tar.addfile(info, io.BytesIO(body))
    with tempfile.TemporaryDirectory(prefix="rag-rc43-") as tmp:
        with tarfile.open(archive) as tar:
            tar.extractall(tmp, filter="data")
        subprocess.run([sys.executable, "-c", verification_code("dev/optimization-v53/candidate-manifest.json"), tmp],
                       cwd=tmp, check=True, capture_output=True)
        subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py"],
                       cwd=tmp, check=True, capture_output=True)
    receipt = {
        "release_id": manifest["release_id"],
        "sha256": sha(archive.read_bytes()),
        "bytes": archive.stat().st_size,
        "files": len(files),
        "isolated_import_hashes_and_tests_verified": True,
        "generation_calls": 0,
        "online_configuration_changed": False,
    }
    save(HERE / "candidate-receipt.json", receipt)
    print(receipt)


REMOTE_SCRIPT = r'''import hashlib,json,pathlib,sys,tarfile,subprocess
host=sys.argv[1];expected=sys.argv[2]
archive=pathlib.Path('/root/rag-catalog-v3-rc43-candidate.tar.gz')
root=pathlib.Path('/root/rtl-rag-catalog-v3-rc43-20261029')
if hashlib.sha256(archive.read_bytes()).hexdigest()!=expected:raise ValueError('uploaded_archive_hash')
root.mkdir(exist_ok=False)
with tarfile.open(archive) as tar:tar.extractall(root,filter='data')
m=json.loads((root/'dev/optimization-v53/candidate-manifest.json').read_text())
for n,h in m['files'].items():
 if hashlib.sha256((root/n).read_bytes()).hexdigest()!=h:raise ValueError('member_hash:'+n)
python='/root/rtl-rag-v27-20261028/.venv312/bin/python'
code="from agent.knowledge.research import load_bundle,validate_vector_index;from agent.knowledge.pregen import read_vector_index;from agent.nodes.generate import generate;import baseline;d=load_bundle();validate_vector_index(read_vector_index(),d);assert d['release_id']=='rag-catalog-v3-rc4.3';assert sum(c['activation_state']=='restricted' for c in d['cards'])==8;assert all(c.get('injection_stages')==['pre_generation'] for c in d['cards'] if c['card_id'] in {'v9-lang-context-before-operation','v9-public-batch-final-sample','v9-public-block-carry-chain'});assert baseline.load_generation()['chat_template_kwargs']['enable_thinking']"
subprocess.run([python,'-c',code],cwd=root,check=True,capture_output=True)
print(json.dumps({'host':int(host),'root':str(root),'release_id':m['release_id'],'files_verified':len(m['files']),'runtime_import_passed':True,'restricted_count':8,'services_started':0,'active_configuration_changed':False}))
'''


def deploy(host):
    receipt = load(HERE / "candidate-receipt.json")
    archive = HERE / ARCHIVE_NAME
    subprocess.run(["scp", "-q", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes", "-P", str(host),
                    str(archive), "root@36.150.116.206:/root/" + ARCHIVE_NAME], check=True, timeout=90)
    command = shlex.join(["/usr/bin/python3", "-c", REMOTE_SCRIPT, str(host), receipt["sha256"]])
    result = subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes", "-p", str(host),
                             "root@36.150.116.206", command], capture_output=True, text=True, timeout=60)
    if result.returncode:
        raise RuntimeError(result.stderr)
    row = json.loads(result.stdout)
    save(HERE / f"deployment-{host}.json", row)
    print(result.stdout)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--deploy", type=int, choices=[33376, 33589])
    args = parser.parse_args()
    deploy(args.deploy) if args.deploy else build()
