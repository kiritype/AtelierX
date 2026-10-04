# AtelierX

[Download for Windows](https://github.com/kiritype/AtelierX/releases/latest) · [User manual](https://kiritype.github.io/AtelierX/)

English | [한국어](README.ko.md)

A desktop tool for making role-play chatbots. It keeps each work's main prompt, lorebook, characters and JSX
components together, and provides writing, compression and test-chat tools. It also includes image prompt and
image workflow features that can connect to separately installed services.

> **Status: staging build.** The Windows x64 portable package has been exercised on the development PC with fresh
> app data, and the native window was opened and closed. An Ollama Cloud connection was checked for its model list,
> a synthetic response and streaming. This is same-PC validation, not a clean-machine release qualification;
> Vertex AI, image generation and complete model/trainer workflows have not been validated.

## Highlights

- **Your files, as they are.** A work is a plain folder of Markdown and JSX files that you organize freely. What you
  see in the file tree is what is on disk and what gets exported.
- **Platform presets.** Size limits, lorebook activation rules and JSX rules differ between chatbot platforms.
  They live in editable presets that a work links to by tag — nothing platform-specific is hard-coded.
- **LLM help that never overwrites silently.** Compression candidates, image prompts, skeletons and consistency
  checks land in a review queue; you pick what to adopt, block by block.
- **LLM connections.** Configure local OpenAI-compatible servers or external providers, with presets for Ollama Cloud,
  Gemini API, Vertex AI, OpenRouter and DeepSeek. A connection check reads a provider response and tests streaming. Credentials are encrypted in
  the app vault; Vertex AI access tokens expire and currently need to be renewed manually.
- **History you can trust.** Built-in snapshots, diff, restore, release marks and a trash with permanent delete.
- **Portable Windows package.** Program, settings, data and output live in one app folder. The ZIP requires Windows
  x64, Microsoft Edge WebView2 Runtime and .NET Framework 4.8; see [packaging/PORTABLE_README.txt](packaging/PORTABLE_README.txt).
The package is currently staged and tested on the same PC, not qualified across clean Windows installations.

ComfyUI, image models, LoRA training tools and local LLM servers are optional external components. They are not
bundled with AtelierX and must be installed and configured separately. The Ollama Cloud check exercised one model
catalog and synthetic response/streaming session; Vertex AI and live image generation remain unverified.

## Repository layout

| Folder | Contents |
|---|---|
| [docs/](docs/README.md) | Design documents (Korean): overview, data model, architecture, platform presets, feature designs, decision records |
| [docs/manual/](docs/manual/index.md) | Korean user manual (Markdown source) |
| [defaults/](defaults/README.md) | Default guidelines and image library copied on first run |
| [samples/](samples/README.md) | Three sample works shipped with the app |

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

[MIT](LICENSE)

## User manual

Read the [Korean manual source](docs/manual/index.md) for installation, editing, testing, images, LoRA and exports.
Build the GitHub Pages site with `npm ci` and `npm run build` in `docs/manual`.
After installing web app dependencies, run `python tools/build_manual.py` for the offline edition and open `dist/manual/index.html`.
See [CONTRIBUTING](CONTRIBUTING.md) for builds and Pages deployment.
