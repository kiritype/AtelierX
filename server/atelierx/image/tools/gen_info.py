"""How an image was made, as a table (#169): which tool made it and its generation settings, read by rules (no LLM).

The record format and the tool that made it are told apart: ComfyUI's image saver nodes write A1111-style text with
``Version: ComfyUI``, NovelAI writes a ``Comment`` JSON. The evidence is returned so the screen can show it and the user
can correct the tool. Names are matched against what this PC's image server has (file name, then the hashes Stability
Matrix keeps next to the files, then a similar name); a sampler or scheduler the image server lacks is only shown.
"""

from __future__ import annotations

import json
import re
from pathlib import Path, PureWindowsPath

GENERATORS = ('atelierx', 'comfyui', 'webui', 'novelai', 'pixai', 'unknown')

# A1111/Forge sampler and schedule names → ComfyUI's.
A1111_SAMPLERS = {
    'euler a': 'euler_ancestral',
    'euler': 'euler',
    'heun': 'heun',
    'lms': 'lms',
    'ddim': 'ddim',
    'dpm2': 'dpm_2',
    'dpm2 a': 'dpm_2_ancestral',
    'dpm++ 2m': 'dpmpp_2m',
    'dpm++ 2m sde': 'dpmpp_2m_sde',
    'dpm++ 2m sde gpu': 'dpmpp_2m_sde_gpu',
    'dpm++ 3m sde': 'dpmpp_3m_sde',
    'dpm++ sde': 'dpmpp_sde',
    'dpm++ 2s a': 'dpmpp_2s_ancestral',
    'dpm fast': 'dpm_fast',
    'dpm adaptive': 'dpm_adaptive',
    'unipc': 'uni_pc',
    'lcm': 'lcm',
    'deis': 'deis',
    'restart': 'restart',
    'er sde': 'er_sde',
    'er_sde': 'er_sde',
}
A1111_SCHEDULES = {
    'sgm uniform': 'sgm_uniform',
    'karras': 'karras',
    'exponential': 'exponential',
    'simple': 'simple',
    'normal': 'normal',
    'beta': 'beta',
    'ddim': 'ddim_uniform',
    'kl optimal': 'kl_optimal',
    'linear quadratic': 'linear_quadratic',
}
# Built-in names closest to what node packs add, offered when the image server lacks the original.
NEAREST_SAMPLER = [
    (re.compile(r'^res_'), 'er_sde'),
    (re.compile(r'sde'), 'er_sde'),
    (re.compile(r'ancestral'), 'euler_ancestral'),
]
NEAREST_SCHEDULER = [
    (re.compile(r'^beta'), 'beta'),
    (re.compile(r'bong|tangent'), 'simple'),
    (re.compile(r'karras'), 'karras'),
]
# Nodes that make the picture the way the app does; any other node in a graph is listed as not used by the app.
GRAPH_CORE = {
    'CheckpointLoaderSimple',
    'UNETLoader',
    'CLIPLoader',
    'DualCLIPLoader',
    'VAELoader',
    'LoraLoader',
    'LoraLoaderModelOnly',
    'CLIPSetLastLayer',
    'CLIPTextEncode',
    'EmptyLatentImage',
    'EmptySD3LatentImage',
    'KSampler',
    'KSamplerAdvanced',
    'SamplerCustomAdvanced',
    'KSamplerSelect',
    'BasicScheduler',
    'BetaSamplingScheduler',
    'CFGGuider',
    'RandomNoise',
    'VAEDecode',
    'VAEEncode',
    'SaveImage',
    'PreviewImage',
    'ModelSamplingAuraFlow',
    'UpscaleModelLoader',
    'ImageUpscaleWithModel',
    'ImageScale',
    'ImageScaleBy',
    'LatentUpscale',
    'LatentUpscaleBy',
}


def _json(text):
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        return None


def _number(value):
    try:
        number = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    return int(number) if number.is_integer() else number


def parse_parameters(text):
    """A1111/Forge ``parameters``: prompt, ``Negative prompt:`` and the ``Key: value, …`` line (values may be quoted
    or JSON, like ``Civitai resources: [...]``)."""
    lines = text.strip().split('\n')
    index = next((i for i in range(len(lines) - 1, -1, -1) if re.match(r'^\s*Steps:', lines[i])), None)
    settings_line = '\n'.join(lines[index:]) if index is not None else ''
    body = '\n'.join(lines[:index] if index is not None else lines)
    positive, _, negative = body.partition('Negative prompt:')
    values = {}
    rest = settings_line
    while rest:
        found = re.match(r'\s*([\w .\-/()]+?):\s*', rest)
        if not found:
            break
        key, rest = found.group(1).strip(), rest[found.end() :]
        if rest.startswith('['):
            depth, end = 0, len(rest)
            for i, ch in enumerate(rest):
                depth += ch == '['
                depth -= ch == ']'
                if depth == 0:
                    end = i + 1
                    break
            value, rest = rest[:end], rest[end:]
        elif rest.startswith('"'):
            end = rest.find('"', 1)
            value, rest = rest[1:end], rest[end + 1 :]
        else:
            end = rest.find(',')
            value, rest = (rest, '') if end < 0 else (rest[:end], rest[end:])
        values[key] = value.strip()
        rest = rest.lstrip(', \n')
    return {'positive': positive.strip(), 'negative': negative.strip(), 'values': values}


def _from_parameters(parsed, samplers=()):
    v = parsed['values']
    out = {}
    sampler = v.get('Sampler', '')
    lowered = sampler.lower()
    schedule = v.get('Schedule type', '')
    # Old A1111 names carried the schedule ("DPM++ 2M Karras").
    if lowered.endswith(' karras') and lowered[:-7] in A1111_SAMPLERS:
        lowered, schedule = lowered[:-7], schedule or 'Karras'
    if lowered in A1111_SAMPLERS:
        out['sampler'] = A1111_SAMPLERS[lowered]
    elif sampler:
        # ComfyUI savers join sampler and scheduler ("er_sde_beta1_1").
        prefix = max((s for s in samplers if lowered.startswith(s + '_')), key=len, default='')
        out['sampler'], out['scheduler'] = (prefix, lowered[len(prefix) + 1 :]) if prefix else (lowered, '')
    if schedule and schedule.lower() != 'automatic':
        out['scheduler'] = A1111_SCHEDULES.get(schedule.lower(), schedule.lower().replace(' ', '_'))
    for key, name in (
        ('Steps', 'steps'),
        ('CFG scale', 'cfg'),
        ('Seed', 'seed'),
        ('Shift', 'shift'),
        ('Clip skip', 'clip_skip'),
    ):
        if _number(v.get(key)) is not None:
            out[name] = _number(v[key])
    if re.match(r'^\d+x\d+$', v.get('Size', '')):
        out['width'], out['height'] = (int(x) for x in v['Size'].split('x'))
    if v.get('Model'):
        out['model'] = {'name': v['Model'], 'hash': v.get('Model hash', '')}
    modules = [v[k] for k in sorted(v) if k.startswith('Module ')]
    encoders = [m for m in modules if not re.search(r'vae', m, re.IGNORECASE)]
    if encoders:
        out['text_encoder'] = {'name': encoders[0]}
    loras = []
    for name, strength in re.findall(r'<lora:([^:>]+):([-\d.]+)[^>]*>', parsed['positive']):
        loras.append({'name': name, 'strength': _number(strength)})
    resources = _json(v.get('Civitai resources')) or []
    for res in resources if isinstance(resources, list) else []:
        air = str(res.get('air', ''))
        version = re.search(r'@(\d+)$', air)
        entry = {
            'name': res.get('modelName', ''),
            'version': res.get('versionName', ''),
            'version_id': version.group(1) if version else '',
        }
        if ':lora:' in air:
            loras.append({**entry, 'strength': res.get('weight', 1)})
        elif ':checkpoint:' in air and isinstance(out.get('model'), dict):
            out['model'].update(
                version_id=entry['version_id'], title=f'{entry["name"]} {entry["version"]}'.strip()
            )
    if loras:
        out['loras'] = loras
    if v.get('Hires upscale') or v.get('Denoising strength') and v.get('Hires upscaler'):
        out['upscale'] = {
            'scale': _number(v.get('Hires upscale')) or 2,
            'steps': _number(v.get('Hires steps')) or out.get('steps'),
            'denoise': _number(v.get('Denoising strength')),
            'model': v.get('Hires upscaler', ''),
            'cfg': _number(v.get('Hires CFG Scale')),
        }
    return out


def _node(graph, ref):
    return graph.get(str(ref[0])) if isinstance(ref, list) and ref else None


def _from_graph(graph):
    """Structured settings from an API-format ComfyUI graph (best effort: links into subgraphs are not followed)."""
    out, loras, others = {}, [], set()
    for node in graph.values():
        if not isinstance(node, dict):
            continue
        kind, inputs = node.get('class_type', ''), node.get('inputs') or {}
        if kind not in GRAPH_CORE:
            others.add(kind)
        if kind in ('UNETLoader', 'CheckpointLoaderSimple') and isinstance(
            inputs.get('unet_name', inputs.get('ckpt_name')), str
        ):
            out.setdefault('model', {'name': inputs.get('unet_name', inputs.get('ckpt_name'))})
        elif kind in ('CLIPLoader',) and isinstance(inputs.get('clip_name'), str):
            out.setdefault('text_encoder', {'name': inputs['clip_name']})
        elif kind in ('LoraLoader', 'LoraLoaderModelOnly') and isinstance(inputs.get('lora_name'), str):
            loras.append({'name': inputs['lora_name'], 'strength': inputs.get('strength_model', 1)})
        elif kind == 'ModelSamplingAuraFlow' and _number(inputs.get('shift')) is not None:
            out['shift'] = _number(inputs['shift'])
        elif kind in ('EmptyLatentImage', 'EmptySD3LatentImage'):
            for key in ('width', 'height'):
                if _number(inputs.get(key)) is not None:
                    out.setdefault(key, _number(inputs[key]))
        elif kind in ('KSampler', 'KSamplerAdvanced') and 'sampler' not in out:
            for key, name in (
                ('sampler_name', 'sampler'),
                ('scheduler', 'scheduler'),
                ('steps', 'steps'),
                ('cfg', 'cfg'),
                ('seed', 'seed'),
                ('noise_seed', 'seed'),
            ):
                if key in inputs and not isinstance(inputs[key], list):
                    out[name] = inputs[key]
        elif kind == 'SamplerCustomAdvanced' and 'sampler' not in out:
            select, sigmas = _node(graph, inputs.get('sampler')), _node(graph, inputs.get('sigmas'))
            guider, noise = _node(graph, inputs.get('guider')), _node(graph, inputs.get('noise'))
            if select:
                out['sampler'] = (select.get('inputs') or {}).get('sampler_name')
            if sigmas:
                si = sigmas.get('inputs') or {}
                out['scheduler'] = si.get('scheduler') or (
                    'beta' if sigmas.get('class_type') == 'BetaSamplingScheduler' else ''
                )
                if _number(si.get('steps')) is not None:
                    out['steps'] = _number(si['steps'])
            if guider and _number((guider.get('inputs') or {}).get('cfg')) is not None:
                out['cfg'] = _number(guider['inputs']['cfg'])
            if noise and _number((noise.get('inputs') or {}).get('noise_seed')) is not None:
                out['seed'] = _number(noise['inputs']['noise_seed'])
    _by_shape(graph, out, loras)
    if loras:
        out['loras'] = loras
    out = {k: v for k, v in out.items() if v not in (None, '')}
    return out, sorted(others)


def _by_shape(graph, out, loras):
    """Node packs keep the same settings under other node names: find them by the shape of their inputs."""
    nodes = [
        n
        for _, n in sorted(graph.items(), key=lambda kv: int(kv[0]) if str(kv[0]).isdigit() else 0)
        if isinstance(n, dict)
    ]
    for node in nodes:
        inputs = node.get('inputs') or {}
        if (
            'sampler' not in out
            and isinstance(inputs.get('sampler_name'), str)
            and ('steps' in inputs or 'steps_total' in inputs)
        ):
            out['sampler'] = inputs['sampler_name']
            for key, name in (
                ('scheduler', 'scheduler'),
                ('steps', 'steps'),
                ('steps_total', 'steps'),
                ('cfg', 'cfg'),
            ):
                if key in inputs and not isinstance(inputs[key], list):
                    out.setdefault(name, inputs[key])
        if (
            'seed' not in out
            and 'seed' in str(node.get('class_type', '')).lower()
            and _number(inputs.get('seed')) is not None
        ):
            out['seed'] = _number(inputs['seed'])
        if not any(x.get('from') == 'pack' for x in loras):
            for value in inputs.values():
                if isinstance(value, dict) and isinstance(value.get('lora'), str) and value.get('on', True):
                    loras.append(
                        {'name': value['lora'], 'strength': value.get('strength', 1), 'from': 'pack'}
                    )
    for lora in loras:
        lora.pop('from', None)


def _graph_prompts(graph):
    """Prompt text from node packs: prompt-studio field lists, else plain ``positive``/``negative`` text inputs."""
    positive, negative = [], []
    nodes = [
        n
        for _, n in sorted(graph.items(), key=lambda kv: int(kv[0]) if str(kv[0]).isdigit() else 0)
        if isinstance(n, dict)
    ]
    for node in nodes:
        fields = _json((node.get('inputs') or {}).get('advanced_fields'))
        if isinstance(fields, list):
            for field in fields:
                if (
                    isinstance(field, dict)
                    and field.get('enabled', True)
                    and str(field.get('text', '')).strip()
                ):
                    (negative if field.get('pane') == 'negative' else positive).append(field['text'].strip())
    if positive or negative:
        return ', '.join(positive), ', '.join(negative)
    for node in nodes:
        inputs = node.get('inputs') or {}
        for key, bucket in (('positive', positive), ('negative', negative)):
            if isinstance(inputs.get(key), str) and inputs[key].strip():
                bucket.append(inputs[key].strip())
    return ', '.join(positive), ', '.join(negative)


def _novelai(text):
    comment = _json(text.get('Comment')) or {}
    out = {'model': {'name': text.get('Source', '')}} if text.get('Source') else {}
    for key, name in (
        ('steps', 'steps'),
        ('scale', 'scale'),
        ('seed', 'seed'),
        ('width', 'width'),
        ('height', 'height'),
    ):
        if _number(comment.get(key)) is not None:
            out[name] = _number(comment[key])
    for key in ('sampler', 'noise_schedule'):
        if comment.get(key):
            out[key] = comment[key]
    v4 = comment.get('v4_prompt') or {}
    positive = (
        comment.get('prompt')
        or ((v4.get('caption') or {}).get('base_caption'))
        or text.get('Description', '')
    )
    v4n = comment.get('v4_negative_prompt') or {}
    negative = comment.get('uc') or ((v4n.get('caption') or {}).get('base_caption')) or ''
    return positive, negative, out


def unwrap(text):
    """Some sites keep ComfyUI's ``prompt``/``workflow`` as one JSON text under ``parameters``: lift them out."""
    outer = (
        _json(text.get('parameters', ''))
        if str(text.get('parameters', '')).lstrip().startswith('{')
        else None
    )
    if not isinstance(outer, dict):
        return text, False
    lifted = {k: v for k, v in text.items() if k != 'parameters'}
    for key in ('prompt', 'workflow'):
        value = outer.get(key)
        if isinstance(value, (dict, list)):
            value = json.dumps(value, ensure_ascii=False)
        if isinstance(value, str):
            lifted.setdefault(key, value)
    return lifted, True


def identify(text, exif, studio):
    """``(generator, record format, evidence)`` from what the file carries."""
    evidence = []
    software = str(text.get('Software', '') or exif.get('Software', ''))
    parameters = text.get('parameters', '')
    version = (re.search(r'Version:\s*([^,\n]+)', parameters) or [None, ''])[1].strip() if parameters else ''
    if isinstance(studio, dict) and studio.get('positive'):
        return 'atelierx', 'atelierx', ['AtelierX 생성 기록(사이드카·PNG atelierx)']
    if 'novelai' in software.lower() or (
        'Comment' in text
        and isinstance(_json(text.get('Comment')), dict)
        and 'uc' in (_json(text['Comment']) or {})
    ):
        evidence.append(f'Software: {software}' if software else 'Comment JSON(uc)')
        return 'novelai', 'novelai', evidence
    blob = ' '.join([software, parameters[:2000], str(exif.get('ImageDescription', ''))]).lower()
    if 'pixai' in blob:
        return 'pixai', 'a1111' if parameters else 'unknown', ['PixAI 표기']
    if text.get('prompt') and _json(text.get('prompt')):
        evidence.append('ComfyUI 그래프(prompt)')
        if text.get('workflow'):
            evidence.append('편집용 워크플로(workflow)')
        if version:
            evidence.append(f'Version: {version}')
        return 'comfyui', 'comfy-graph', evidence
    if parameters:
        if version.lower().startswith('comfyui'):
            return 'comfyui', 'a1111', [f'parameters의 Version: {version}']
        if version:
            label = (
                'Forge Neo'
                if version.startswith('neo')
                else 'Forge'
                if version.startswith('f')
                else 'A1111'
                if version.startswith('v')
                else version
            )
            return 'webui', 'a1111', [f'parameters의 Version: {version} ({label})']
        return 'webui', 'a1111', ['parameters 텍스트(판 표기 없음)']
    return 'unknown', 'unknown', []


def analyze(text, exif, studio, size, samplers=()):
    """``{generator, format, evidence, positive, negative, settings, other_nodes, notes}`` for one image."""
    text, wrapped = unwrap(text)
    generator, form, evidence = identify(text, exif, studio)
    if wrapped:
        evidence.append('parameters 칸의 JSON(prompt·workflow)')
    positive = negative = ''
    settings = {}
    other_nodes = []
    if generator == 'atelierx':
        positive, negative = studio.get('positive', ''), studio.get('negative', '')
        s = studio.get('settings') or {}
        settings = {
            k: s[k]
            for k in ('sampler', 'scheduler', 'steps', 'cfg', 'seed', 'width', 'height', 'shift')
            if s.get(k) not in (None, '')
        }
        if s.get('model'):
            settings['model'] = {'name': s['model']}
        if s.get('text_encoder'):
            settings['text_encoder'] = {'name': s['text_encoder']}
        if s.get('loras'):
            settings['loras'] = [
                {'name': x['name'], 'strength': x.get('strength_model', 1)} for x in s['loras']
            ]
        if s.get('upscale'):
            settings['upscale'] = s['upscale']
    elif generator == 'novelai':
        positive, negative, settings = _novelai(text)
    else:
        parsed = parse_parameters(text['parameters']) if text.get('parameters') else None
        if parsed:
            positive, negative = parsed['positive'], parsed['negative']
            settings = _from_parameters(parsed, samplers)
        graph = _json(text.get('prompt'))
        if isinstance(graph, dict):
            from_graph, other_nodes = _from_graph(graph)
            # The A1111-style text is what the saver says was used; the graph fills what it leaves out.
            for key, value in from_graph.items():
                settings.setdefault(key, value)
            if not positive:
                from .metadata import parse_comfy

                found = parse_comfy(graph) or {}
                positive, negative = found.get('positive', ''), found.get('negative', '')
                if not positive:
                    positive, negative = _graph_prompts(graph)
    if 'width' not in settings and size:
        settings['width'], settings['height'] = size
    return {
        'generator': generator,
        'format': form,
        'evidence': evidence,
        'positive': positive,
        'negative': negative,
        'settings': settings,
        'other_nodes': other_nodes,
        'notes': [],
    }


# --- matching names against this PC ---------------------------------------------------------------------------------
def _stem(name):
    return _plain(name).lower()


# Words too common in model file names to tell two files apart.
COMMON_WORDS = {
    'anima',
    'base',
    'txt',
    'text',
    'encoder',
    'model',
    'safetensors',
    'fp16',
    'bf16',
    'fp8',
    'v1',
    'v10',
    'lora',
}


def _tokens(name):
    """Words of a file or display name: split at separators, case changes and between letters and digits."""
    raw = _plain(name)
    raw = re.sub(r'([a-z])([A-Z])', r'\1 \2', raw)
    raw = re.sub(r'(?<=[A-Za-z])(?=\d)|(?<=\d)(?=[A-Za-z])', ' ', raw)
    return {t for t in re.split(r'[^a-z0-9]+', raw.lower()) if len(t) > 1 and t not in COMMON_WORDS}


def _plain(name):
    """A file or display name without its folder and model-file extension (display names may contain dots)."""
    raw = PureWindowsPath(str(name or '')).name
    return re.sub(r'\.(safetensors|ckpt|pt|pth|bin|gguf)$', '', raw, flags=re.IGNORECASE)


def _similarity(wanted, candidate):
    """Share of the wanted name's words found inside the candidate's name (letters and digits only)."""
    words = _tokens(wanted)
    joined = re.sub(r'[^a-z0-9]', '', _plain(candidate).lower())
    return sum(1 for w in words if w in joined) / len(words) if words else 0


def file_index(folders):
    """``{kind: [{name, sha256, version_id}]}`` from Stability Matrix's ``.cm-info.json`` next to model files."""
    index = {}
    for kind, roots in (folders or {}).items():
        for root in roots:
            root = Path(root)
            if not root.is_dir():
                continue
            for info in root.rglob('*.cm-info.json'):
                try:
                    doc = json.loads(info.read_text(encoding='utf-8'))
                except (OSError, ValueError):
                    continue
                file = info.with_name(info.name.removesuffix('.cm-info.json') + '.safetensors')
                if not file.is_file():
                    continue
                index.setdefault(kind, []).append(
                    {
                        'name': str(PureWindowsPath(file.relative_to(root))),
                        'sha256': str((doc.get('Hashes') or {}).get('SHA256') or '').lower(),
                        'version_id': str(doc.get('VersionId') or doc.get('ModelVersionId') or ''),
                        'model_id': str(doc.get('ModelId') or ''),
                    }
                )
    return index


def match(wanted, choices, index_entries=()):
    """Find ``wanted`` ({name, hash?, version_id?}) among ``choices`` (the image server's names).

    Returns ``{found, by, similar}``: ``found`` only for the same file name, hash or Civitai version (from
    ``.cm-info.json``); a file with a similar name is only offered in ``similar`` for the person to judge.
    """
    name = wanted.get('name', '')
    plain = {c: c.removeprefix('checkpoint::') for c in choices}
    for choice, path in plain.items():
        if _stem(path) == _stem(name):
            return {'found': choice, 'by': 'name', 'similar': None}
    digest, version = str(wanted.get('hash') or '').lower(), str(wanted.get('version_id') or '')
    for entry in index_entries:
        hit = (digest and entry['sha256'].startswith(digest)) or (version and entry['version_id'] == version)
        if hit:
            found = next((c for c, p in plain.items() if _stem(p) == _stem(entry['name'])), None)
            if found:
                return {
                    'found': found,
                    'by': 'hash' if digest and entry['sha256'].startswith(digest) else 'version',
                    'similar': None,
                }
    scored = sorted(((_similarity(name, p), c) for c, p in plain.items()), reverse=True)
    similar = scored[0][1] if scored and scored[0][0] >= 0.5 else None
    return {'found': None, 'by': None, 'similar': similar}


def match_settings(settings, catalog, index):
    """Add ``found``/``by`` to the model, text encoder and LoRAs of ``settings`` (in place) and return it."""
    if isinstance(settings.get('model'), dict):
        entries = index.get('diffusion_models', []) + index.get('checkpoints', []) + index.get('unet', [])
        settings['model'].update(match(settings['model'], catalog.get('models') or [], entries))
    if isinstance(settings.get('text_encoder'), dict):
        entries = index.get('text_encoders', []) + index.get('clip', [])
        settings['text_encoder'].update(
            match(settings['text_encoder'], catalog.get('text_encoders') or [], entries)
        )
    for lora in settings.get('loras') or []:
        lora.update(match(lora, catalog.get('loras') or [], index.get('loras', [])))
    upscale = settings.get('upscale')
    if isinstance(upscale, dict) and upscale.get('model'):
        found = match({'name': upscale['model']}, catalog.get('upscale_models') or [])
        upscale['model_found'] = found['found']
    return settings


def enrich(generation, catalog, index):
    """Check one image's settings against this PC: which files it has and which names the image server lacks."""
    if generation['generator'] in ('novelai', 'pixai') or not catalog.get('connected'):
        return generation
    settings = generation['settings']
    match_settings(settings, catalog, index)
    notes = []
    samplers, schedulers = catalog.get('samplers') or [], catalog.get('schedulers') or []
    if settings.get('sampler') and samplers and settings['sampler'] not in samplers:
        near = next((n for p, n in NEAREST_SAMPLER if p.search(settings['sampler'])), 'er_sde')
        notes.append({'kind': 'sampler', 'name': settings['sampler'], 'nearest': near})
    if settings.get('scheduler') and schedulers and settings['scheduler'] not in schedulers:
        near = next((n for p, n in NEAREST_SCHEDULER if p.search(settings['scheduler'])), 'simple')
        notes.append({'kind': 'scheduler', 'name': settings['scheduler'], 'nearest': near})
    generation['notes'] = notes
    return generation
