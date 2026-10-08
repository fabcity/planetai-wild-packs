"""posidonia: offline validation for the Posidonia wild pack.
Run from a node's folder: python3 packs/posidonia/tests/test_posidonia.py
"""
from pathlib import Path
import yaml

PACK_DIR = Path(__file__).resolve().parent.parent

# 1. pack.yaml manifest validation
manifest = yaml.safe_load((PACK_DIR / "pack.yaml").read_text(encoding="utf-8"))
assert manifest["id"] == "posidonia"
assert manifest["kind"] == "data"
assert manifest["domain"] == "coast"
assert manifest["metrics"] == ["sea_surface_temp"]
assert "requires" in manifest and "node" in manifest["requires"]
assert manifest["author"] == "Lucas Marangoni (Fab City Foundation)"
print("  manifest: pack.yaml structure and metadata valid")

# 2. rules.yml validation
rules = yaml.safe_load((PACK_DIR / "rules.yml").read_text(encoding="utf-8"))
assert len(rules) == 2
rule_ids = {r["id"] for r in rules}
assert rule_ids == {"thermal_stress", "warm_watch"}
for r in rules:
    assert r["level"] == "info"
    assert "sql" in r and "readings_1h" in r["sql"]
    assert "marine-point" in r["sql"]
    for lang in ("en", "id", "es"):
        assert lang in r["message"], f"missing {lang} in {r['id']}"
print("  rules: 2 info rules, SQL target marine-point, en/id/es messages present")

# 3. cells.yml validation
cells = yaml.safe_load((PACK_DIR / "cells.yml").read_text(encoding="utf-8"))
assert len(cells) == 1
assert cells[0]["cell"] == "Environmental|Bioregion"
assert cells[0]["state"] == "partial"
assert "28.4" in cells[0]["sql"]
print("  cells: Environmental|Bioregion partial cell valid")

print("posidonia: ok")
