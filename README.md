**English** | [Chinese](README.zh.md)

<p align="center">
  <img alt="MIT" src="assets/badges/license.svg" height="20">
  <img alt="Python 3.9+" src="assets/badges/python.svg" height="20">
  <img alt="dependencies none" src="assets/badges/dependencies.svg" height="20">
</p>

# Project Consistency Engineering

An agent skill that keeps a repository's structure honest: every file has a home, every folder has a one-line job, and the map is updated in the same change that moves the furniture.

It only checks **where things are and whether the map kept up** — not whether the docs are accurate or the code runs.

## The problem

A repo built together with an agent rots in four predictable ways:

1. Loose files pile up at the root, and nobody can say whether they belong there.
2. New folders get created, but no one can say what they are for.
3. Files move, and the documents and code that point at them do not.
4. Every new agent session starts by guessing the structure again.

None of this is a code-quality problem. It is a *structure* problem, and it gets worse in exactly the way a stale TODO comment never does: silently.

## How it holds

Three things, each one enforced by the next:

| Piece | What it is | Who reads it |
|---|---|---|
| **Contract** | `structure.yaml` — zones, root allow-list, naming, archive, ignore | the checker |
| **Maps** | one `navigation.md` per folder that has subfolders | you and the agent |
| **Check** | `tools/pce.py` — 12 rules, one pass, exit codes | you and CI |

The contract is the single source of truth. The maps are rendered from it and updated by the same change that touches the files. The checker is the only thing that decides whether any of it still holds.

## Install

```sh
git clone <repo-url> ~/.agents/skills/project-consistency-engineering
```

Some CLIs read a different folder (`~/.claude/skills/`, and so on). That only decides whether the skill *triggers*; everything it needs is copied into your repository, so `python3 tools/pce.py check` works either way.

## Thirty seconds

```sh
cd your-repo
python3 ~/.agents/skills/project-consistency-engineering/tools/pce.py init
python3 tools/pce.py check
```

`init` asks before it writes: what the general zone is called, what each zone is for, whether to claim an archive folder, and whether each stray root file belongs in the allow-list. It copies `tools/pce.py` into your repo, so the repo no longer depends on the skill being installed.

Old repository? Start read-only:

```sh
python3 tools/pce.py audit
```

## What it looks like

```console
$ python3 tools/pce.py check
README.md  I4  error  still points at the old path src/legacy/old.py; it now lives at archive/src/legacy/old.py
notes.txt  I1  error  root-level file notes.txt is not in root.allow; move it into a zone, or allow it with a reason

2 error, 0 warn
```

*(Translated from the real output, which is Chinese-only.)*

Each line is four things: location, the principle it breaks, the level, and what to do about it. `error` means the structure is broken (exit code 1). `warn` means it is worth a look; `--strict` turns those into failures too.

Output is currently Chinese only; the rules and the data model are language-neutral.

## Commands

| Command | What it does | Writes files? |
|---|---|---|
| `init` | Create the contract, entry point, maps; install `tools/pce.py` | yes, item by item |
| `audit` | Read-only survey: size, mess, what is missing | no |
| `check` | Run the 12 rules; print findings | no |
| `map` | Reconcile each map with the disk | yes, rows only |
| `new` | Create a file or folder in a place the contract allows | yes |
| `archive` | Move retired files into the archive zone and register them | yes |
| `explain` | Explain why a path is judged the way it is | no |
| `upgrade` | Update `tools/pce.py` | yes; stops if you edited it |
| `hook install/uninstall` | Install or remove a pre-commit hook | yes |

Every write prints a plan first. In a non-interactive shell (CI, scripts) writes require `--apply`; without it nothing is written.

## Five principles, twelve checks

The checks are not a style lint. Each one hangs off a principle:

- **I1 Ownership** — every file either sits in a zone or is explicitly allowed at the root.
- **I2 Map completeness** — every folder that has subfolders has a `navigation.md` saying what each subfolder is for.
- **I4 Name matches reality** — names follow the contract, and every link or path reference lands on a real file.
- **I5 Entry stays usable** — `AGENTS.md` stays short and free of logs; it is loaded on every turn.
- **I3 Freshness** — each map shows when its folder last changed, computed from git, never hand-written.

S1–S12 are the concrete checks (root files, map presence, two-way reconciliation, naming, dead links, archived paths, empty folders, overlapping zones, vague descriptions, archive registry, entry length). Details: [references/validation.md](references/validation.md).

## FAQ

**Will it change my files?** `audit`, `check` and `explain` never write. Anything that writes prints a plan and asks; a whole batch stops if one item violates the contract.

**Do I need git?** No. Without git, `map` cannot fill the "last updated" column and `archive` falls back to a plain move. Everything else works.

**Does it fight with other skills that write `AGENTS.md`?** It owns only the block between `<!-- pce:begin -->` and `<!-- pce:end -->`. It never touches text outside those markers; if the block was edited locally it is left alone unless you pass `--reset-agents`.

**Why Python and YAML?** `tools/pce.py` is one file, standard library only, Python 3.9+, no install step. YAML is parsed by a deliberately small subset parser shipped in the same file, so there is no dependency and no drift between versions.

**Monorepo?** One contract per repository root. Packages live inside zones; nested repositories are not supported yet.

**Can I use it without the skill?** Yes. The skill is only a way to trigger the workflow. `tools/pce.py` in your repo is the whole tool.

**Can it run in CI?** Yes: `python3 tools/pce.py check --strict` exits 1 on any finding. A pre-commit hook is optional and never installed by default.

## Repository layout

```
SKILL.md            the entry point an agent reads first
AGENTS.md           how to work on this package itself
references/         contract, placement, validation, migration, philosophy
assets/templates/   files copied into a new repository
tools/pce.py        the checker (single file, stdlib only)
```

## License

MIT — see [LICENSE](LICENSE).
