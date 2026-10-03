<!-- Listing or hosting a pack. AGENTS.md has the rules; tools/check.py enforces most of them. -->

**Pack:** `<id>` — listed from `<owner/repo[/folder]>` at `<40-char commit>` / hosted here in `packs/<id>/`

- [ ] the folder, the `id:` in `pack.yaml` and the entry's `id` are the same, and not a core pack's
- [ ] `kind` is `code` if there is an `adapter.py`
- [ ] `status` is `listed`
- [ ] `tested_with` is a release I ran it on: `v0.__`
- [ ] `requires: { node: ">=0.76" }` if it uses readouts or sections
- [ ] keys and tokens are under `secrets:`, and no value is anywhere in the pack or this PR
- [ ] the README says where the thresholds come from, the place it was written for, what it does not know, its licence
- [ ] hosted here: a CODEOWNERS line for `/packs/<id>/`
- [ ] `python3 tools/test_check.py && python3 tools/check.py --node ../planetai-node` exits 0

Written with an agent? Say which one.
