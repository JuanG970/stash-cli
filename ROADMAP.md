# stash-cli roadmap — prioritized candidates

Planning-only document. State verified on `master` at `afdce36` ("Makefile improvements"),
package version 0.2.1, Python `>=3.10`, build backend `uv_build` with a committed `uv.lock`.
No dates or delivery commitments are implied by this document.

`stash-cli` is a Typer CLI over the Bitbucket Server (Stash) REST API. It is imported and
exercised here in a throwaway venv with `PYTHONPATH=src`; every claim below is reproducible
offline from a clean checkout. Nothing here is approval to implement: each candidate needs its
own issue and a separate `overnight-approved` label before code work starts.

## Current state (measured, not asserted)

- One Python module: `src/stash_cli/main.py`, 1143 lines, 25 module-level functions plus 4
  methods (12 of the module-level ones `_private`), 6 CLI commands: `list-prs`, `create-pr`,
  `pr`, `pr-comment`, `pr-add-reviewer`, `pr-remove-reviewer`.
- **Zero tests.** No `tests/`, no `.github/`, no lint or type configuration. `Makefile` has a
  single target, `install` (`uv tool install --force -e .`).
- `--dry-run` exists on all six commands and works offline: `create-pr --dry-run` exits 0 and
  prints `"Authorization": "Bearer ***REDACTED***"`, so the `Secret` wrapper does redact through
  f-strings.
- `--output-format {table,json}` exists on `pr` only.
- All HTTP calls carry explicit `timeout=` and `verify=get_ssl_verify()`; no call site was found
  without a timeout.
- `README.md` is stale in ways a reader would hit immediately (details under P3).

## P1 — Offline test harness for the pure paths (highest value, lowest risk)

**Evidence.** There is no test suite at all, yet large parts of the module are already pure and
callable without network: `_parse_pr_url`, `_format_timestamp`, `_parse_pr_url`'s URL regex family,
`get_git_context`'s remote-parsing regexes, `_pr_to_dict`, `Secret`. Probed behaviour:
`_parse_pr_url("nonsense")` raises `typer.Exit` from inside a library-level helper (verified), so
tests either assert on `SystemExit` or the helper needs a `ValueError` seam first. `--dry-run`
gives a network-free integration seam for all six commands.

**Acceptance criteria.**
- `make test` runs `pytest` in the uv-managed environment and passes from a clean clone without
  `STASH_*` variables or network access.
- At least one test per pure helper, including invalid PR URL, `_format_timestamp(None)`,
  milliseconds-vs-seconds input, `Secret` repr/str/f-string redaction, and the three documented
  remote URL shapes (`ssh://…:7999/PROJ/repo.git`, `https://…/scm/PROJ/repo.git`,
  `git@host:PROJ/repo.git`).
- At least one CLI-level test per command asserting `--dry-run` exit code 0 and that stdout
  contains no unredacted token.
- No production behaviour changes required for the tests to pass (or the seam change is argued
  explicitly in the PR).

## P2 — Correctness of the missing-variable and error-reporting contract

**Evidence.** In `get_env_vars` the guard is `if not base_url or not token.get():`, but the
subsequent `if not token:` tests a `Secret` object, which has no `__bool__`; the object is always
truthy, so `STASH_ACCESS_TOKEN` is never listed. Reproduced: with no environment set,
`list-prs` prints only `STASH_BASE_URL` and exits 1. Two bare `except:` clauses (lines 232 and
365) swallow arbitrary exceptions. In `pr --output-format json` a comment-fetch
`RequestException` is printed to stderr and the command still exits 0 with partial JSON, so a
consumer cannot distinguish complete from truncated output. A DNS failure surfaces as a raw
urllib3 `NameResolutionError` blob rather than an actionable message.

**Acceptance criteria.**
- Missing-credential errors list every missing variable, with a test for the both-missing case.
- Bare `except:` removed; each handler narrows to the exception types it actually expects, or
  re-raises.
- Exit codes documented in the README and enforced by tests: 0 success, 1 user/API error, 2 usage
  error.
- JSON mode either fails non-zero when comment retrieval fails or marks the payload as partial;
  the choice is stated in the PR body and covered by a test with a stubbed failing request.

## P3 — Make the README true (docs only)

**Evidence.** `README.md` still prescribes Poetry end to end — 13 mentions across 12 lines, including
`poetry install`, `poetry shell`, `poetry run`, and a structure block listing `poetry.lock` and a
top-level `stash_cli/main.py`. The repository actually uses `uv` (`uv.lock`, `uv_build`
backend, `.python-version` = 3.12, `make install` = `uv tool install`); there is no `poetry.lock`
and the package lives under `src/stash_cli/`. The documented "Key functions" list includes
`redact_dict()`, which does not exist in the source. The "Commands" section documents 2 of the 6
commands and omits `pr --output-format json`.

**Acceptance criteria.**
- No `poetry` mention remains; install/dev/test instructions work copy-pasted on a clean
  machine with uv.
- Every command, its options, and both output formats are documented with one runnable example
  each; `--dry-run` semantics and its redaction guarantees are stated.
- The structure block matches the tree; the function list matches `grep -n "^def "`.
- A reader can follow the README start to finish without hitting a command that does not exist.

## P4 — Packaging metadata truth-up

**Evidence.** `pyproject.toml` declares `requires-python = ">=3.10"` while its classifiers still
advertise Python 2, 2.7, and 3.4–3.9. `.python-version` is 3.12. Version appears as both
`0.2.1` (pyproject) and "v0.2.0" (last feature commit message), and there are no git tags.

**Acceptance criteria.**
- Classifiers match the supported range actually tested.
- One source of truth for the version, and `uv build` produces an artifact whose name and
  metadata agree with it.
- CI (P5) asserts the installed console script reports the same version.

## P5 — CI: fast, secret-free lint and test on every PR

**Evidence.** No `.github/` directory and no automated checks exist; the only quality gate today
is a human reading `--dry-run` output. The toolchain is already frozen (`uv.lock`), so a runner
needs no credentials to lint and test.

**Acceptance criteria.**
- A workflow triggers on `pull_request` and pushes to `master`, uses `astral-sh/setup-uv` with
  `uv sync --frozen`, runs `ruff check` and `pytest`, and finishes well under five minutes.
- No repository secrets are referenced; fork PRs run the same unprivileged checks.
- README carries the status badge; a deliberately failing test makes the check red.
- Sequenced after P1 so the workflow has something to run.

## P6 — Split `main.py` into cohesive modules

**Evidence.** 1143 lines in one file mixing CLI wiring, environment and git-context resolution,
HTTP calls, rich rendering, comment-tree assembly, and formatting helpers; 12 private helpers
already suggest the seams. Every new command lands in this file, and merge conflicts are likely
whenever two changes touch it — the two most recent commits to modify it (`defee25`, `2c6b9dc`)
both did so.

**Acceptance criteria.**
- No behaviour change: `--help` output for the app and all six commands is unchanged, and the
  P1/P2 tests pass untouched.
- Modules grouped by concern (e.g. `config`, `gitctx`, `api`, `render`, `commands`) with no file
  above roughly 400 lines and no circular imports.
- Public console-script entry point `stash_cli.main:app` keeps working, or the change is
  reflected in `pyproject.toml` and the README.

## Not planned here

Live calls against a real Stash instance, credential handling changes beyond the reporting bug,
new commands, and any dependency upgrade beyond what P4/P5 require. Those need a separate,
explicitly approved change.

## How to reproduce the measurements

```bash
uv sync --frozen                      # or: python3 -m venv .venv && .venv/bin/pip install -e .
PYTHONPATH=src .venv/bin/python -m stash_cli.main --help
PYTHONPATH=src .venv/bin/python -m stash_cli.main create-pr -t demo --dry-run
PYTHONPATH=src .venv/bin/python -m stash_cli.main list-prs     # no env: reports missing vars
grep -n "poetry" README.md ; grep -n "redact_dict" README.md
grep -n "except:" src/stash_cli/main.py
```
