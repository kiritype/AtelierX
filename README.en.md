# AtelierX

[Download for Windows](https://github.com/kiritype/AtelierX/releases/latest) · [User manual](https://atelierx.cftm.net/) · [Bug reports, ideas and questions](https://github.com/kiritype/AtelierX/discussions)

[한국어](README.md) | English

A Windows desktop tool for making role-play chatbots. It keeps each work's main prompt, opening scenes, lorebook,
characters and JSX components together, lets an LLM agent write and refine them, and tests the result in a chat. Character
image generation, review, post-processing and LoRA training live in the same program.

![Editing a work](docs/manual/screenshots/work-main.webp)

> **Status: pre-1.0 releases (0.x).** The app updates itself from inside. Before 1.0, features and data formats can still
> change; when a format changes, a conversion ships with it. What has and has not been checked is listed in the manual's
> [verification scope](https://atelierx.cftm.net/guide/release-status.html) page (Korean).

## Highlights

**Writing**
- **Your files, as they are.** A work is a plain folder of Markdown and JSX files that you organize freely. What you see
  in the file tree is what is on disk and what gets exported.
- Each file has a kind (main, opening scene, lorebook, character, JSX, note) and an ID; lorebook keywords and priority
  are set in a form above the editor.
- **Platform presets.** Size limits, lorebook activation and JSX rules differ between chatbot platforms. They live in
  editable presets that a work links to — nothing platform-specific is hard-coded.
- Rule checks, a relationship map and glossary, bulk rename and a JSX preview.

**LLM**
- **An agent panel that never overwrites silently.** Pick a mode (writing, compression, JSX wording …) and hand over a
  task; the result arrives as a whole-file proposal you review and adopt block by block.
- **▶ Test** (`F5`) opens the chat test screen: opening scenes, personas and test sets to compare before and after edits.
- Local OpenAI-compatible servers, plus connection presets for Ollama Cloud, Gemini API, Vertex AI, OpenRouter and DeepSeek.

**Character images**
- Preview and generate character × outfit × expression combinations in bulk, composed from a prompt library
  (expressions, compositions, common prompts) and style presets (model, settings and artist tags).
- Generation services: ComfyUI on this PC, or the online services NovelAI and PixAI (your own account and API key;
  billed by each service).
- Review in the gallery (pass, fail, adopt) and find missing combinations on the completion board.
- Image tools: upscale, detailer, censor, background removal, inpaint, tagging, WebP conversion, prompt format conversion.
- Build a LoRA dataset from adopted images, train it and register it.

**Keeping and protecting your work**
- Snapshots, diff, restore, release marks and a trash.
- Work packages (ZIP) to move works to another PC or back everything up.
- A master password locks the app; credentials such as API keys are encrypted in a vault (work files stay plain text).
- Portable: program, settings, data and output live in one app folder.

## Requirements

Windows x64, Microsoft Edge WebView2 Runtime and .NET Framework 4.8. Unzip the download and run `AtelierX.exe`; see
[packaging/PORTABLE_README.txt](packaging/PORTABLE_README.txt).

Writing and cloud LLMs need nothing else. The image server (ComfyUI), local LLM servers and the LoRA trainer are optional
and not bundled; install only what you need yourself or from the app's **Settings → Install**.

## External components

The image features use the following, downloaded separately. The app fetches pinned versions from their own sources
in Settings → Install and does not redistribute them. Versions, licenses and sources are listed in the manual's
[external components](https://atelierx.cftm.net/guide/external.html) page (Korean).

- Image server: [ComfyUI](https://github.com/comfyanonymous/ComfyUI)
- Custom nodes: [WD14 Tagger](https://github.com/pythongosssss/ComfyUI-WD14-Tagger),
  [ComfyUI_essentials](https://github.com/cubiq/ComfyUI_essentials), [Impact Pack](https://github.com/ltdrdata/ComfyUI-Impact-Pack),
  [Impact Subpack](https://github.com/ltdrdata/ComfyUI-Impact-Subpack)
- Models: [Anima](https://huggingface.co/circlestone-labs/Anima) (non-commercial license), [adetailer](https://huggingface.co/Bingsu/adetailer),
  [Segment Anything](https://github.com/facebookresearch/segment-anything), [2x-AnimeSharpV4](https://huggingface.co/Kim2091/2x-AnimeSharpV4) and [UltraSharp](https://huggingface.co/Kim2091/UltraSharp) (non-commercial)
- LoRA training: [anima_lora](https://github.com/sorryhyun/anima_lora), [anime_tools](https://github.com/sorryhyun/anime_tools)
- Helper tools: [uv](https://github.com/astral-sh/uv), [Git for Windows](https://github.com/git-for-windows/git) (MinGit)

The online image services [NovelAI](https://novelai.net/) and [PixAI](https://pixai.art/) are not installed: they are paid
services used with your own account. You register the API key yourself; their terms and prices apply.

## Repository layout

| Folder | Contents |
|---|---|
| [server/](server/) | Python server (Starlette): works, LLM, images, installs, packages |
| [web/](web/) | User interface (React + TypeScript + Vite) |
| [tests/](tests/) | Server tests (pytest); UI tests live in `web/` (vitest) |
| [docs/](docs/README.md) | Design documents (Korean): overview, data model, architecture, platform presets, feature designs, decision records |
| [docs/manual/](docs/manual/index.md) | User manual source (Korean; web and offline) |
| [defaults/](defaults/README.md) | Default guidelines, image library and model download list copied on first run |
| [samples/](samples/README.md) | Three sample works shipped with the app |
| [comfy_nodes/](comfy_nodes/) | The node pack the app installs into ComfyUI |
| [trainer/](trainer/) | Patches applied to the LoRA trainer |
| [packaging/](packaging/), [tools/](tools/) | Windows package build and development tools |

## Feedback

Bug reports, feature requests and questions go to [Discussions](https://github.com/kiritype/AtelierX/discussions) (also
reachable from the app's **Help** menu). Issues are the maintainers' task list. Report security vulnerabilities privately
as described in the [security policy](SECURITY.md).

## Contributing

Development setup, checks, code rules, branches and releases, and manual builds: [CONTRIBUTING.en.md](CONTRIBUTING.en.md).

## License

[MIT](LICENSE)
