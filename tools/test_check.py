"""tools/check.py's index rules, on entries written to break them. Run: python3 tools/test_check.py"""
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location("check", Path(__file__).with_name("check.py"))
C = importlib.util.module_from_spec(spec); spec.loader.exec_module(C)

SHA = "a" * 40
CORE = {"heat", "air-quality"}


def entry(**kw):
    e = {"id": "rain-gauge", "name": "Rain gauge", "source": "someone/planetai-pack-rain-gauge", "commit": SHA,
         "author": "Someone", "reads": "a tipping-bucket gauge on the LAN", "kind": "code",
         "licence": "AGPL-3.0-or-later; data CC BY 4.0", "tested_with": "v0.75.8", "status": "listed"}
    e.update(kw)
    return {k: v for k, v in e.items() if v is not None}


def has(errs, text):
    return any(text in x for x in errs)


hosted = entry(source="fabcity/planetai-wild-packs/packs/rain-gauge", commit=None)

assert C.problems([], CORE, set()) == []
assert C.problems([entry()], CORE, set()) == []
assert C.problems([hosted], CORE, {"rain-gauge"}) == []
assert C.problems([entry(source="someone/monorepo/rain-gauge")], CORE, set()) == []      # one folder of a bigger repo
assert C.problems([entry(source="someone/monorepo/packs/rain-gauge")], CORE, set()) == []  # nested deeper
assert has(C.problems([entry(source="someone/monorepo/../x")], CORE, set()), "owner/repo")
assert has(C.problems({}, CORE, set()), "must be a list")
assert has(C.problems([entry(id="heat")], CORE, set()), "is a core pack")
assert has(C.problems([entry(), entry()], CORE, set()), "listed twice")
assert has(C.problems([entry(id="Rain_Gauge")], CORE, set()), "lowercase")
assert has(C.problems([entry(status="trusted")], CORE, set()), "'listed' or 'reviewed'")
assert has(C.problems([entry(kind="script")], CORE, set()), "'data' or 'code'")
assert has(C.problems([entry(licence=None)], CORE, set()), "missing licence")
assert has(C.problems([entry(stars=5)], CORE, set()), "unknown field stars")
assert has(C.problems([entry(commit=None)], CORE, set()), "40-character commit")
assert has(C.problems([entry(commit="main")], CORE, set()), "40-character commit")
assert has(C.problems([entry(source="someone")], CORE, set()), "owner/repo")
assert has(C.problems([entry(source="someone//x")], CORE, set()), "owner/repo")
assert has(C.problems([dict(hosted, commit=SHA)], CORE, {"rain-gauge"}), "drop 'commit'")
assert has(C.problems([entry(source="fabcity/planetai-wild-packs/elsewhere")], CORE, set()), "has source fabcity/planetai-wild-packs/packs/rain-gauge")
assert has(C.problems([], CORE, {"orphan"}), "packs/orphan/ is here but packs.json does not list it")
assert has(C.problems([hosted], CORE, set()), "does not exist")
print("check.py: the index rules hold")
