"""Check packs.json and every wild pack it lists against a checkout of planetai-node.

    python3 tools/check.py --node ../planetai-node

1. Every entry has the fields the README asks for, with values of the right shape.
2. No id is a core pack's id, and no two entries share one.
3. Every folder under packs/ here has an entry, and every entry hosted here has a folder.
4. Each pack is fetched into the node's packs/ (copied when hosted here, downloaded at its pinned commit when not),
   and its pack.yaml says the same id and the same kind as its entry.
5. The node's own tools/check_rules.py runs over core and wild rules together.
6. Each pack's own tests (<id>/tests/test_*.py) run from the node's folder.

Standard library and PyYAML. Exits 1 on the first step that fails, after printing every problem that step found.
"""
from __future__ import annotations

import argparse
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
REPO = "fabcity/planetai-wild-packs"
FIELDS = {"id", "name", "source", "author", "reads", "kind", "licence", "tested_with", "status"}
OPTIONAL = {"commit"}
ID = re.compile(r"^[a-z0-9][a-z0-9-]*$")
SHA = re.compile(r"^[0-9a-f]{40}$")


def problems(entries, core_ids: set[str], hosted_dirs: set[str]) -> list[str]:
    """Steps 1 to 3. Pure, so tools/test_check.py can hold it to its word."""
    if not isinstance(entries, list):
        return ["packs.json must be a list"]
    out, seen = [], set()
    for i, e in enumerate(entries):
        where = f"entry {i}"
        if not isinstance(e, dict):
            out.append(f"{where}: not an object"); continue
        pid = e.get("id")
        where = f"entry {i} ({pid})" if pid else where
        missing = sorted(FIELDS - set(e))
        extra = sorted(set(e) - FIELDS - OPTIONAL)
        if missing:
            out.append(f"{where}: missing {', '.join(missing)}")
        if extra:
            out.append(f"{where}: unknown field {', '.join(extra)}")
        if not isinstance(pid, str) or not ID.match(pid):
            out.append(f"{where}: id must be lowercase letters, digits and hyphens")
            continue
        if pid in seen:
            out.append(f"{where}: id listed twice")
        seen.add(pid)
        if pid in core_ids:
            out.append(f"{where}: '{pid}' is a core pack in planetai-node; a wild pack needs another id")
        if e.get("status") not in ("listed", "reviewed"):
            out.append(f"{where}: status is 'listed' or 'reviewed'")
        if e.get("kind") not in ("data", "code"):
            out.append(f"{where}: kind is 'data' or 'code'")
        src = e.get("source")
        if not isinstance(src, str) or src.count("/") < 1 or "" in src.split("/") or ".." in src.split("/"):
            out.append(f"{where}: source is owner/repo, or owner/repo/path/to/folder")
            continue
        hosted = src == f"{REPO}/packs/{pid}"
        if hosted and "commit" in e:
            out.append(f"{where}: a pack hosted here is checked at this repository's own commit; drop 'commit'")
        if not hosted:
            if src.startswith(REPO + "/"):
                out.append(f"{where}: a pack hosted here has source {REPO}/packs/{pid}")
            if not SHA.match(str(e.get("commit", ""))):
                out.append(f"{where}: a pack hosted elsewhere pins the full 40-character commit it was listed at")
    listed_here = {e["id"] for e in entries if isinstance(e, dict) and e.get("source") == f"{REPO}/packs/{e.get('id')}"}
    for d in sorted(hosted_dirs - listed_here):
        out.append(f"packs/{d}/ is here but packs.json does not list it")
    for d in sorted(listed_here - hosted_dirs):
        out.append(f"'{d}' says it is hosted here, but packs/{d}/ does not exist")
    return out


def fetch(e: dict, dest: Path) -> None:
    """Step 4: put the pack at dest. The same archive-and-extract a node uses, so CI fetches what a node would."""
    if e["source"] == f"{REPO}/packs/{e['id']}":
        shutil.copytree(HERE / "packs" / e["id"], dest)
        return
    owner, repo, *folder = e["source"].split("/")
    url = f"https://codeload.github.com/{owner}/{repo}/tar.gz/{e['commit']}"
    prefix = f"{repo}-{e['commit']}/" + ("/".join(folder) + "/" if folder else "")
    with urllib.request.urlopen(url, timeout=60) as r:
        tar = tarfile.open(fileobj=io.BytesIO(r.read()), mode="r:gz")
    dest.mkdir(parents=True)
    for m in tar.getmembers():
        if not m.name.startswith(prefix) or m.name == prefix.rstrip("/"):
            continue
        rel = m.name[len(prefix):]
        if not rel or rel.startswith("/") or ".." in Path(rel).parts or not (m.isfile() or m.isdir()):
            continue                                   # no absolute paths, no escapes, no links
        target = dest / rel
        if m.isdir():
            target.mkdir(parents=True, exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(tar.extractfile(m).read())
    if not any(dest.iterdir()):
        raise RuntimeError(f"{e['source']} at {e['commit'][:12]} has nothing at that path")


def manifest_problems(e: dict, d: Path) -> list[str]:
    import yaml
    f = d / "pack.yaml"
    if not f.is_file():
        return [f"{e['id']}: no pack.yaml at {e['source']}"]
    m = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
    out = []
    if m.get("id") != e["id"]:
        out.append(f"{e['id']}: pack.yaml says id '{m.get('id')}'; the node namespaces rules by folder, so they must match")
    kind = "code" if (d / "adapter.py").is_file() else "data"
    if kind != e["kind"]:
        out.append(f"{e['id']}: listed as {e['kind']}, but it is a {kind} pack (adapter.py {'present' if kind == 'code' else 'absent'})")
    return out


def step(name: str, errs: list[str]) -> None:
    if errs:
        print(f"x {name}"); [print(f"    {x}") for x in errs]; sys.exit(1)
    print(f"  {name}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--node", required=True, help="a checkout of fabcity/planetai-node (its main)")
    node = Path(ap.parse_args().node).resolve()
    entries = json.loads((HERE / "packs.json").read_text(encoding="utf-8"))
    core = {p.parent.name for p in (node / "packs").glob("*/pack.yaml")}
    if not core:
        sys.exit(f"x no packs under {node}/packs: --node is not a planetai-node checkout")
    hosted = {p.name for p in (HERE / "packs").iterdir() if p.is_dir()}
    step(f"packs.json: {len(entries)} wild pack(s), none named like one of {len(core)} core packs", problems(entries, core, hosted))

    errs = []
    for e in entries:
        d = node / "packs" / e["id"]
        try:
            fetch(e, d)
            errs += manifest_problems(e, d)
        except Exception as ex:  # noqa: BLE001
            errs.append(f"{e['id']}: could not fetch {e['source']} ({ex})")
    step("every pack fetched, and its pack.yaml agrees with its entry", errs)

    r = subprocess.run([sys.executable, "tools/check_rules.py"], cwd=node, capture_output=True, text=True)
    lines = [x for x in (r.stdout + r.stderr).splitlines() if x.startswith("  x ") or "check out" in x]
    step("rules and cells check out against the node's schema, core and wild together",
         [] if r.returncode == 0 else lines or [r.stdout[-400:] + r.stderr[-400:]])

    errs, ran = [], 0
    env = dict(os.environ, PYTHONPATH=str(node / "app"), PACKS_DIR="packs")
    for e in entries:
        for t in sorted((node / "packs" / e["id"] / "tests").glob("test_*.py")):
            ran += 1
            r = subprocess.run([sys.executable, str(t)], cwd=node, env=env, capture_output=True, text=True, timeout=300)
            if r.returncode:
                last = (r.stdout + r.stderr).strip().splitlines()
                errs.append(f"{e['id']}/tests/{t.name} exit {r.returncode}: {last[-1] if last else 'no output'}")
    step(f"{ran} pack test file(s) pass", errs)
    print("ok")


if __name__ == "__main__":
    main()
