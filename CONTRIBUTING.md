# Contributing

English | [한국어](CONTRIBUTING.ko.md)

AtelierX is in staging. The Windows x64 portable package has been exercised on the development PC, including one
Ollama Cloud model-list and synthetic response/streaming check. It has not been qualified on clean Windows installs,
with Vertex AI, or with live image generation. Issues and discussion are welcome.
The design documents in [docs/](docs/README.md) are written in Korean.

## Design documents

- Data formats are defined only in [docs/data-model.md](docs/data-model.md). Feature documents link to it.
- Decisions are recorded in [docs/decisions/](docs/decisions/), one file per decision. When a published decision
  changes, add a new record that supersedes it instead of editing the old one.
- Platform-specific rules do not belong in the documents or the defaults. Express them as a platform preset example.

## Commits and pull requests

- Commit message: `<area>: <what and why>`, one line, in English (for example `docs: add chat test design`).
- One change per commit. Do not mix refactoring with behavior changes.
- Commit and pull request messages describe the change only. Do not add tool credits, generated-by signatures or
  co-author lines.
- Do not commit run data (`config/`, `state/`, `data/`, `output/`), personal notes or local tool settings.
- A pull request explains what changed, why, and how it was checked. Add screenshots when the UI changes.

Follow the existing code conventions and run the relevant checks for code changes. Do not report external provider,
ComfyUI, model or trainer validation unless those services were actually exercised.

## License

By contributing you agree that your contributions are licensed under the [MIT License](LICENSE).

## Manual builds

Edit `docs/manual/index.md` and `docs/manual/guide/*.md`. Document actual UI labels, prerequisites,
input examples, and expected results. Screenshots must not expose personal work or credentials.

- Web: run `npm ci` and `npm run build` in `docs/manual`; output is `dist/manual-site/` at repository root.
- Preview: run `npm run preview` in that folder.
- Offline: install web app dependencies, then run `python tools/build_manual.py` at repository root.
  The same Markdown becomes `dist/manual/`, with navigation and search available directly from `index.html`.
- Public-file check: `python tools/audit_public.py` checks selected credential patterns and history filenames;
  it is not a complete secret scan.

The `manual-pages.yml` workflow builds and deploys documentation changes on main; pull requests only build.
Set repository Settings → Pages → Source to GitHub Actions. The workflow derives the base path from the repository
name, or `/` for user sites. For a custom domain, set the repository variable `DOCS_BASE` to `/`.
Local subpath checks can set `DOCS_BASE=/repository-name/`. Remote deployment is not verified until Actions runs.
