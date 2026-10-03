# PLANETAI wild packs

A [PLANETAI node](https://github.com/fabcity/planetai-node) grows by packs: folders that bring rules, Index cells or
a new source. The packs that ship in the node's release are **core**. Every other pack is **wild**: written for a
place, by the people there, and added to a node by whoever runs it. This repository lists the wild packs, and it can
host one for an author who would rather not keep a repository of their own.

The rules for both tiers are in the node's decision record,
[`docs/decisions/2026-10-01-packs.md`](https://github.com/fabcity/planetai-node/blob/main/docs/decisions/2026-10-01-packs.md).

**Listed is not reviewed.** Every entry says which it is. A `listed` pack has passed the checks below and nobody here
has read it. A code pack (one with an `adapter.py`) runs Python with your node's privileges, and only once you set
`PACKS_ALLOW_CODE=1`. Read it before you turn that on.

Writing or listing a pack with an AI agent? Point it at [`AGENTS.md`](AGENTS.md) or [`llms.txt`](llms.txt). `CLAUDE.md` and
`GEMINI.md` send their tools there too. It carries the rules below in the form an agent checks against.

## The list

[`packs.json`](packs.json). Empty for now.

| field | what it says |
|---|---|
| `id` | the pack's folder name on a node, and the `id:` in its `pack.yaml`. Never a core pack's id |
| `name` | what a person calls it |
| `source` | `owner/repo` when the repository is the pack, `owner/repo/path/to/folder` when it is one folder of a bigger one, `fabcity/planetai-wild-packs/packs/<id>` when it lives here |
| `commit` | the full 40-character commit it was listed at. Required for a pack that lives elsewhere; left out for one that lives here |
| `author` | who wrote it and answers for it |
| `reads` | one line: what it measures or fetches, and from where |
| `kind` | `data` (YAML only) or `code` (it has an `adapter.py`) |
| `licence` | the pack's licence. Say the code's and the data's if they differ |
| `tested_with` | the node release it was last run on, for example `v0.75.8` |
| `status` | `listed`, or `reviewed` once a maintainer has read it. A code pack is `reviewed` only after somebody read its adapter |

## Adding a wild pack to your node

From your node's folder, on v0.76 or later:

```
planetai packs add <id>                                  # a pack on this list, at the commit it was listed at
planetai packs add <owner>/<repo>[/<folder>][@<ref>]      # any pack on GitHub; a branch or tag is pinned to its commit
planetai restart
```

It fetches the pack with curl and tar (a node installed the default way has no git), writes where it came from and at
which commit to `packs/<id>/.wild`, and runs `planetai packs install`. It never replaces a core pack. It says at once
if the pack is written for a newer node than yours. `planetai packs` lists core and wild apart. Running it again
updates the pack; deleting `packs/<id>` and restarting removes it. `planetai update` leaves a wild pack alone, and
stops before it would overwrite one that a release has made core.

On a node older than v0.76, do the same by hand. When the repository is the pack:

```
mkdir packs/<id>
curl -fsSL https://codeload.github.com/<owner>/<repo>/tar.gz/<commit> | tar xz -C packs/<id> --strip-components=1
planetai packs install      # the settings it needs into .env, its Python libraries into the image
planetai restart
```

For a pack hosted here, extract just its folder:

```
curl -fsSL https://codeload.github.com/fabcity/planetai-wild-packs/tar.gz/main | tar xz -C packs --strip-components=2 planetai-wild-packs-main/packs/<id>
```

Use the `commit` from the pack's entry rather than `main` when there is one: that is the version that was checked.
With a commit, the folder inside the archive is `<repo>-<commit>/...`.

## What a wild pack can carry

Everything a pack can, as [docs/PACKS.md](https://github.com/fabcity/planetai-node/blob/main/docs/PACKS.md) describes:
rules and Index cells, an adapter for a new source, and since v0.76:

- **readouts on an issue**: numbers a pack adds to Air, Heat, Coast or Land, shown in Figures and, on a context issue,
  in its sentence. It adds; it never changes an issue's line, distances or sentences.
- **a declared section of the dashboard**: a band on Now, and columns on the wall if you ask, drawn with the page's
  own readout cards. A wild pack ships no code for the page.
- **`requires: { node: ">=0.76" }`**: a node that does not match leaves the pack out and says why. Declare it when
  your pack uses readouts or a section, because an older node ignores both without a word.

## Listing a pack

Open a pull request that adds one entry to `packs.json`. Anyone may. Before you do:

- the pack's folder name and the `id:` in its `pack.yaml` are the same, and not the name of a core pack;
- its README says where its thresholds come from, which place they were written for, and what it does not know;
- its tests, if it has any, are in `tests/test_*.py` inside the pack and run from a node's folder
  (`python3 packs/<id>/tests/test_x.py`), with the standard library, PyYAML and duckdb.

## Hosting a pack here

The same pull request also adds the folder as `packs/<id>/`, and a line in [`.github/CODEOWNERS`](.github/CODEOWNERS)
naming you for that folder, so a change to it needs your review. Its README says its licence. Hosting is not
adopting: the pack stays yours.

## What the checks run

On every push and pull request, and every Monday, against the node's current `main`
([`tools/check.py`](tools/check.py)):

1. every entry has the fields above, with values of the right shape, and no id collides with a core pack's;
2. every folder under `packs/` has an entry, and every entry hosted here has a folder;
3. each pack is fetched the way a node fetches it, and its `pack.yaml` agrees with its entry on `id` and `kind`;
4. the node's own `tools/check_rules.py` runs over core and wild rules together, against the node's schema;
5. each pack's own tests pass.

Locally: `python3 tools/test_check.py && python3 tools/check.py --node ../planetai-node`.

## Becoming core

A wild pack that a second place can use may move into the node's release. That is a pull request to
`fabcity/planetai-node` that adds the folder, passes every gate there, and finds a maintainer who will keep it. The
decision record lists what a reviewer asks for. The entry here then says where it went.
