"""Content identities shared by result evidence and suite contracts."""

import hashlib
import json
from copy import deepcopy


def suite_hash(suite):
    body = json.dumps(
        deepcopy(suite), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return hashlib.sha256(body.encode()).hexdigest()
