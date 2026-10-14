# Contributing

[한국어](CONTRIBUTING.md) | English

AtelierX is in its pre-1.0 releases (0.x). The design documents in [docs/](docs/README.md) are written in Korean.

## Reports and the task flow

- Bug reports, feature requests and questions are taken in [Discussions](https://github.com/kiritype/AtelierX/discussions).
  Issues are the task list of confirmed work (the new-issue page points to Discussions).
- A post that will be worked on becomes an issue whose body says `Source: Discussion #n`. The post gets a reply with the
  issue number, and later the release that contains it. A post that turns out to be a usage question ends with an answer,
  and the manual is improved when needed.
- Security vulnerabilities are reported privately as described in the [security policy](SECURITY.md), not in public.
- One issue, one branch; the PR body says `Closes #n`. PRs are merged into `dev`, which is not the default branch, so
  issues do not close by themselves: after merging, note what landed on the issue and close it.

## Writing and maintaining task issues

External reports follow the Discussions flow above. Maintainers may directly register confirmed bugs, improvements,
or work agreed with the user after searching existing issues. Label an investigation as such instead of asserting an
unconfirmed defect. Reading and reproduction may precede registration; implementation starts after it. Security
findings follow the private reporting policy.

- **Title**: use `<area>: <problem or intended outcome>`.
- **Body**: describe the purpose/problem, current behavior and confirmed facts, expected behavior and scope, a completion
  checklist, and references. Bugs include the version or commit, reproduction conditions/steps, and actual/expected
  results. Improvements explain the user flow and friction; investigations state questions, measurements and deliverables.
  State exclusions and dependencies when relevant.
- **Evidence**: distinguish user reports, source inspection, mock reproduction and real-service verification. Do not state
  suspected causes as facts. Prefer commit-pinned source links; remove credentials and private data from logs/screenshots.
- **Duplicates and scope**: add evidence about the same problem in a comment on the existing issue. Separate follow-up work
  with independent completion criteria into linked issues. Reopen a closed issue only for its unresolved original scope,
  with evidence, rather than for a separate follow-up.
- **Source**: write `Source: Discussion #n` only for an actual Discussion conversion. Link related issues and dependencies;
  summarize requests from conversation so the issue stands on its own.

Check the repository's existing label names and descriptions first. Ordinary tasks get one primary type, one priority,
and one or more relevant areas. Do not invent new labels.

| Category | Criteria |
|---|---|
| Type | `bug` for incorrect behavior/data loss, `enhancement` for features/usability, `documentation` for documentation work |
| Priority | `priority: P1`: data loss/core failures to address before the next release; `P2`: ordinary defects/planned improvements; `P3`: deferrable improvements |
| Area | `area: editor`, `llm`, `image`, `install`, `release`, `ui`, or `security`; every actual name has the `area: ` prefix |
| Supporting | `accessibility`; `needs reproduction` for missing evidence; `needs verification` for implemented work awaiting real-service checks; `status: blocked` for external conditions/decisions |
| Resolution/contribution | Explain `duplicate`, `invalid`, or `wontfix` in a comment with relevant links. Use `help wanted` and `good first issue` only when their contribution conditions apply |

The existence of `area: security` does not authorize public disclosure of private findings. Remove supporting labels when
their conditions no longer apply. Assign milestones only to work committed to the next release under the version policy
below; leave tentative candidates unassigned.

Keep the body aligned with the current scope and completion criteria; use comments for dated progress. When scope changes,
update the body and explain why in a comment. Completion comments include the changes, validation commands/results/limits,
commit and PR. Local implementation alone does not close an issue: verify the merge and completion criteria first. Record
the shipped version after release.

## Development setup

Requirements: Python 3.12 with [uv](https://github.com/astral-sh/uv), Node.js 24 (npm). Development happens on Windows.

```bash
uv sync
cd web && npm ci && npm run build
```

- Run the server: `uv run python -m atelierx --dev --root <test app folder>`. Without `--root` the repository itself is the
  app folder and `config/`, `data/`, `state/` and `output/` appear inside it (never committed). `--dev` uses port 8765 and
  allows the Vite dev server's origin.
- UI development: `cd web && npm run dev`, then `http://localhost:5173`; `/api` goes to the server on 8765. The server alone
  serves the build in `web/dist`.
- Keep a separate test app folder without real keys or passwords. Features that need ComfyUI, NovelAI and other services
  have stand-ins in the tests (`tests/`).

## Checks

Pull requests must pass the CI `test` check. Run the same locally:

```bash
uv sync --locked
uv run --locked ruff check
uv run --locked pytest -q -p no:cacheprovider
cd web && npm test && npm run typecheck && npm run build
```

- Python code follows `uv run ruff check` and `uv run ruff format` (settings in `pyproject.toml`).
- After editing the manual, run `uv run python tools/build_manual.py dist/manual-check` to check the offline manual's links.
  The package build runs the same check, so a failure here fails the release.
- Public file audit: `uv run python tools/audit_public.py`. It checks some credential patterns and file names in the Git
  history; it is not a complete secret scan.
- Do not report external providers, ComfyUI, models or the trainer as verified unless you actually ran them.

## Code rules

- **UI text (i18n)**: semantic keys, added to both `web/src/locales/ko.json` and `en.json`. Messages the server shows to the
  user are `Msg(key, English sentence)`; the UI translates the key (and shows the English sentence for unknown keys).
- **Job states**: long work (LLM, image queue, installs, training) uses the shared states in `core/lifecycle.py` (`queued`,
  `running`, `cancelling`, `done`, `failed`, `cancelled`, `interrupted`).
- **Save conflicts**: JSON that several screens edit is saved with a revision; a save based on stale content is refused with
  409 (`server.save.stale`, `core/revisions.py`).
- **Unsaved changes**: editing screens register with `useUnsaved`, so closing a tab, leaving and locking ask first.
- **API**: server routes live in `routes()` of the area modules `server/atelierx/api/*_routes.py`, gathered by `app.py`.
  Shared helpers are in `api/common.py` (`ok`, `body`, `st`, `work_of`). A new or changed API gets a response type on the screen
  side (`web/src/types.ts`, image ones in `web/src/imageTypes.ts`) instead of `any`. Server-side format checks stay plain
  functions such as `clean_*`.
- **Data formats** are defined only in [docs/data-model.md](docs/data-model.md). Changing a format updates that document and
  `schema_version` and adds a conversion that reads the old format.
- **Manual**: when UI text or behavior changes, update `docs/manual/` too. Screenshots use made-up data, never personal works
  or visible keys. Link to pages, not to headings (the offline manual's heading anchors differ, so `#heading` links break).
- Platform-specific rules do not belong in the documents or the defaults. Express them as a platform preset example.

## Design documents and decisions

- Feature designs live in `docs/features/`, one document per area; see [docs/features/README.md](docs/features/README.md).
- Decisions are recorded in [docs/decisions/](docs/decisions/), one file per decision. When a published decision changes,
  add a new record that supersedes it instead of editing the old one.

## Commits and pull requests

- Commit message: `<area>: <what and why>`, one line, in English (for example `docs: add chat test design`).
- One change per commit. Do not mix refactoring with behavior changes.
- Commit and PR messages describe the change only: no tool credits, generated signatures or co-author lines.
- Do not commit runtime data (`config/`, `state/`, `data/`, `output/`), private notes or local tool settings.
- In the PR, say what changed and why, and how you checked it. Attach screenshots for UI changes.

## Branches and releases

The reasoning is in [decision 0020](docs/decisions/0020-branch-flow.md) (Korean).

- Work happens on `feat/*`, `fix/*`, `docs/*` or `ci/*` branches: one branch per change, each in its own working folder
  (`git worktree add ../atelierx-worktrees/<name> -b feat/<name> dev`). Concurrent work never shares a working folder.
- Open pull requests against `dev`. The `test` check must pass; approval is not required. Merge with squash or rebase.
- Never commit to `staging` or `main` directly. They only move forward to commits that already passed `test`:
  `git push origin <commit>:staging`, later `git push origin <commit>:main`. The maintainer decides when.
- A push to `staging` builds the Windows package and publishes a prerelease `vX.Y.Z-rc.N`. `staging` stays put while the
  candidate is verified.
- After verification, move `main` to the candidate commit and run the **Release** workflow with the candidate tag. It
  publishes the candidate's files unchanged as `vX.Y.Z`.
- Hotfix: branch `fix/*` from `main`, then bring the fix into `main`, `dev` and any open `staging` candidate. A changed
  candidate is verified again.

## Fixing only the manual

The manual site follows main (the released version). A fix to the manual alone can go out before the next release, without
pushing to main:

1. Make a `docs/*` branch from **main**, change only `docs/manual/`, and push it.
2. In GitHub **Actions → Manual on GitHub Pages → Run workflow**, keep the branch on **main** and put the branch name in `ref`.
   The site is updated. The run stops if the branch does not contain main or changes anything outside `docs/manual/`, so
   nothing unreleased reaches the site.
3. Open a pull request from the same branch into `dev`. For a documentation-only pull request, CI skips the app's tests and
   only checks the offline manual's links, so it finishes quickly. The fix ships in the app's manual with the next release.

A manual change that goes with a feature belongs in that feature's pull request and goes public with the release.

## Versions and milestones

The reasoning is in [decision 0022](docs/decisions/0022-versioning.md) (Korean).

- Before 1.0: a release with a new feature, a data format change or a changed decision raises `0.MINOR.0`; improvements,
  fixes, documentation and refactoring only raise `0.x.PATCH`.
- Only the next version gets a milestone, holding the issues planned for it. It is released when its issues are closed and
  the prerelease has been checked.
- The version is written in `pyproject.toml`, `server/atelierx/__init__.py` and `web/package.json`, with the lock files
  (`uv.lock`, `web/package-lock.json`) updated, in one commit (`build: version X.Y.Z`).

## Building the user manual

The manual is edited in `docs/manual/`; its table of contents is `docs/manual/pages.json`. Describe the real button names,
example input, the success state and any required connection.

- Web: `cd docs/manual`, `npm ci`, `npm run build`. Output goes to `dist/manual-site/` at the repository root. Preview with
  `npm run preview` in the same folder.
- Offline: `uv run python tools/build_manual.py` from the repository root renders the same Markdown into `dist/manual/`,
  which ships in the package. Open `index.html` directly from disk to search and browse.
- `manual-pages.yml` deploys manual changes on `main` to [atelierx.cftm.net](https://atelierx.cftm.net/) and only builds on
  pull requests, so manual changes merged into `dev` go public with the next release.

## License

Contributions are published under the repository's [MIT License](LICENSE).
