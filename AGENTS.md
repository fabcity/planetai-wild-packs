# For the agent working in this repository

This repository is the list of **wild** PLANETAI packs: packs that are not in the node's release, written for a place
by the people there. It holds `packs.json` (the list), `packs/<id>/` (packs hosted here for authors without a repository
of their own) and `tools/check.py` (what CI runs). The README is for people; this file is for you. The node itself,
and every rule about what a pack is, lives in [fabcity/planetai-node](https://github.com/fabcity/planetai-node).

## What the person in front of you is asking for

| the person says | read | then do this |
|---|---|---|
| "I want my node to use pack X", "how do I install a wild pack?" | README, *Adding a wild pack to your node* | On the node, from its folder (v0.76 or later): `planetai packs add <owner>/<repo>[/<folder>]`, or `planetai packs add <id>` for a pack in `packs.json` (read it first: it may be empty), then `planetai restart`. Never `git clone` on a node: a default install has no git. |
| "help me write a pack for my place" | the node's [`docs/PACKS.md`](https://github.com/fabcity/planetai-node/blob/main/docs/PACKS.md) | Write it in the author's own repository, or as `packs/<id>/` here. Start from a core pack of the same kind in the node's `packs/`, not from a blank file. |
| "list my pack", "publish it so other nodes can use it" | README, *Listing a pack* | One pull request adding one entry to `packs.json`, pinned to a full 40-character commit. Run the checks below before you open it. |
| "host it here, I don't want my own repo" | README, *Hosting a pack here* | Same pull request adds `packs/<id>/` and a CODEOWNERS line naming the author. Leave `commit` out of a hosted entry. |
| "make this pack core", "ship it with the node" | README, *Becoming core* | That is a pull request to planetai-node, not here. Its `AGENTS.md` and `skills/preflight/` say how to work there. |
| "the Monday check went red and I changed nothing" | `tools/check.py` | The check runs against the node's current `main`, which moves without a commit here. Read which step failed; usually the node changed a rule or a schema the pack relies on. |

## Before you open a pull request

From this repository's folder, with a checkout of planetai-node beside it:

```
pip install pyyaml sqlglot duckdb          # what CI installs; a pack's tests may use nothing else
python3 tools/test_check.py                # the checker's own tests
python3 tools/check.py --node ../planetai-node
```

Exit 0 is the only pass. It fetches a pack listed from elsewhere the way a node does, at its pinned commit, so push
that commit before you run it.

## What must hold

These are what the checks and the node enforce. Breaking one is a red check at best and, at worst, a pack that loads
on nobody's node without saying why.

- **`id` is the folder name and the `id:` in `pack.yaml`**, lowercase letters, digits and hyphens, and never the id of
  a core pack. The node namespaces rules by folder, so a mismatch is a pack whose rules point nowhere.
- **`commit` is the full 40-character sha** for a pack that lives elsewhere. A branch name is not a version anybody
  checked.
- **`kind` is the truth.** `code` whenever the pack has an `adapter.py`. A code pack runs Python with the node's
  privileges, and only once the person running the node sets `PACKS_ALLOW_CODE=1`.
- **`status` is `listed`.** Only a maintainer changes it to `reviewed`, and only after reading the pack (for a code
  pack, its adapter). Never set `reviewed` on your own pack or anyone else's.
- **`requires: { node: ">=0.76" }`** in `pack.yaml` whenever the pack uses `readouts:` or `sections:`. An older node
  ignores both without a word; with `requires:` it leaves the pack out and says why.
- **A key or token the pack needs is listed under `secrets:`** in `pack.yaml` and read from the environment. Never put
  a value in the pack, in `packs.json`, in a test or in a pull request.
- **A script an agent may run is named under `agent_scripts:`** in `pack.yaml`. A wild pack's other scripts run only
  from the node's own terminal (`planetai run`), never through the agent's `run_pack_script` tool.
- **Tests** live in `<id>/tests/test_*.py`, run from a node's folder (`python3 packs/<id>/tests/test_x.py`), and use
  only the standard library, PyYAML and duckdb.
- **The README says** where each threshold comes from, which place it was written for, what the pack does not know,
  and its licence (the code's and the data's, if they differ).
- **A wild pack ships no code for the dashboard.** It can add readouts to an issue and declare a section the page
  draws with its own cards; that is all.

## What not to do

- Do not edit another author's `packs/<id>/` folder; CODEOWNERS gives them the review, and hosting is not adopting.
- Do not change `tools/check.py` or the workflow to make a pack pass. If the check is wrong, say so in its own pull
  request.
- Do not list a pack you have not run on a node. `tested_with` is a release somebody actually ran it on.
