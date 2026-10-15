"""Evidence ledger: every merged decision = one JSON file = one git commit.

entry hash binds: input parameters + patch + seed + n_paths + engine version.
Anyone can re-run engine with the same inputs and must get the same result (seeded).
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import subprocess
import time
import urllib.request
from pathlib import Path

from . import ENGINE_VERSION

ROOT = Path(__file__).resolve().parent.parent
LEDGER_DIR = ROOT / "ledger"


def canonical(obj) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def input_hash(params, patch, seed, n_paths, T) -> str:
    return hashlib.sha256(canonical(dict(params=params, patch=patch, seed=seed, n_paths=n_paths,
                                         T=T, engine=ENGINE_VERSION)).encode()).hexdigest()


def write_entry(kind: str, name: str, params, patch, result: dict, reason: str, seed, n_paths, T) -> dict:
    LEDGER_DIR.mkdir(exist_ok=True)
    ts = time.strftime("%Y%m%dT%H%M%S")
    slug = "".join(ch if ch.isalnum() else "-" for ch in name.lower())[:40] or "entry"
    fname = f"{ts}-{kind}-{slug}.json"
    entry = dict(kind=kind, name=name, reason=reason, engine_version=ENGINE_VERSION,
                 input_sha256=input_hash(params, patch, seed, n_paths, T),
                 seed=seed, n_paths=n_paths, horizon=T, patch=patch, result=result,
                 created_at=time.strftime("%Y-%m-%dT%H:%M:%S%z"))
    text = json.dumps(entry, ensure_ascii=False, indent=2, sort_keys=True)
    (LEDGER_DIR / fname).write_text(text + "\n", encoding="utf-8")
    sha = hashlib.sha256(text.encode()).hexdigest()
    return dict(file=f"ledger/{fname}", sha256=sha, entry=entry)


def commit(rel_file: str, message: str) -> dict:
    """Publish a ledger file.

    * GITHUB_TOKEN + GITHUB_REPO set (hosted demo, e.g. Render): create the file via the GitHub contents API
      -> the commit appears on GitHub live. Token needs 'Contents: read & write' on that repo.
    * otherwise: local git commit (works on a dev machine).
    """
    tok, repo = os.getenv("GITHUB_TOKEN"), os.getenv("GITHUB_REPO")
    if tok and repo:
        try:
            body = json.dumps(dict(
                message=message, branch=os.getenv("GITHUB_BRANCH", "main"),
                content=base64.b64encode((ROOT / rel_file).read_bytes()).decode(),
                committer=dict(name="Branch CFO", email="branch-cfo@users.noreply.github.com"))).encode()
            req = urllib.request.Request(
                f"https://api.github.com/repos/{repo}/contents/{rel_file}", body, method="PUT",
                headers={"Authorization": f"Bearer {tok}", "Accept": "application/vnd.github+json",
                         "X-GitHub-Api-Version": "2022-11-28", "Content-Type": "application/json",
                         "User-Agent": "branch-cfo"})
            with urllib.request.urlopen(req, timeout=20) as r:
                res = json.loads(r.read())
            return dict(via="github_api", commit=res["commit"]["sha"][:7], url=res["content"]["html_url"],
                        commit_url=res["commit"]["html_url"])
        except Exception as e:
            return dict(via="github_api", error=str(e)[:200])
    out = dict(via="local_git")
    try:
        ident = ["-c", "user.name=Branch CFO", "-c", "user.email=branch-cfo@users.noreply.github.com"]
        subprocess.run(["git", "add", rel_file], cwd=ROOT, check=True, capture_output=True)
        r = subprocess.run(["git", *ident, "commit", "-m", message], cwd=ROOT, capture_output=True, text=True)
        out["git"] = (r.stdout or r.stderr).strip().splitlines()[:1]
        out["commit"] = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT,
                                       capture_output=True, text=True).stdout.strip()
    except Exception as e:  # pragma: no cover
        out["git_error"] = str(e)
    return out


def list_entries() -> list[dict]:
    res = []
    if LEDGER_DIR.exists():
        for f in sorted(LEDGER_DIR.glob("*.json")):
            res.append(dict(file=f"ledger/{f.name}", sha256=hashlib.sha256(f.read_bytes().rstrip(b"\n")).hexdigest()))
    return res
