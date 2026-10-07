"""LLM tasks over a work that end in a review draft, the editor actions, and the export (#90).

Each checks the request, then puts a job on the job list whose runner asks the LLM (or the built-in mock) and leaves
a draft for the review tab. The API only reads the request and returns the job. It gets what it needs, not the app.
"""

import asyncio
from copy import deepcopy

from ..image import designs as image_designs
from . import authoring, editor_tasks, exporter, guidelines, llm_tasks, review
from .drafts import Drafts, mock_compress
from .fsutil import read_json
from .i18n import AppError, Msg
from .jsx import call_text
from .relations import Relations
from .snapshots import Snapshots


class WorkJobs:
    def __init__(self, paths, llm, presets, events, jobs):
        self.paths, self.llm, self.presets, self.events, self.jobs = paths, llm, presets, events, jobs

    def mocked(self, task, override=None):
        """Whether this task's connection is the built-in mock (tests, offline checks)."""
        provider, _, _ = self.llm.resolve(task, override)
        return provider.get('type') == 'mock'

    def guideline(self, work, name):
        return guidelines.find(work, self.paths, self.presets.effective(work.doc())['linked'], name)

    def export(self, work, data):
        """Write the work to its export folder as a job, after the target and name checks."""
        blocked = exporter.blocked_target(data.get('target'), self.paths.root, work.folder)
        if blocked:
            raise AppError(blocked, 400)
        clash = exporter.name_clash(exporter.plan(work)[0])
        if clash:
            raise AppError(
                Msg(
                    'server.export.name_clash',
                    '{path} has the reserved export name. Rename it first.',
                    path=clash,
                ),
                409,
            )
        if data.get('snapshot'):
            Snapshots(work).create('export', data.get('release') or '내보내기', force=True)

        async def runner(progress):
            await progress(30)
            return await asyncio.to_thread(
                exporter.export, work, data['target'], data.get('overwrite', False), self.paths.root
            )

        return self.jobs.submit('export', f'{work.name} 내보내기', runner, work_id=work.id)

    def relations(self, work, data):
        """Find relations between the people of the work: a relations draft."""
        self.llm.require_consent(work, 'consistency', data.get('llm'))

        async def runner(progress):
            items = [
                i for i in work.index_with_bodies() if i['meta'].get('enabled', True) and i['kind'] != 'note'
            ]
            characters = [i for i in items if i['kind'] == 'character']
            model = None
            if self.mocked('consistency', data.get('llm')):
                await asyncio.sleep(0.4)
                first = characters[0]['name'] if characters else '인물'
                result = {
                    'relations': [{'from': first, 'to': '{{user}}', 'kind': '(모의) 관계', 'calls': ''}],
                    'facts': [],
                }
            else:
                await progress(10)
                doc = Relations(work).load()
                existing = [f'{r["from"]} → {r["to"]}: {r.get("kind", "")}' for r in doc['relations']]
                others = [i for i in items if i['kind'] in ('main', 'lorebook')]
                messages = llm_tasks.relations_messages(characters, others, existing)
                result, answer = await llm_tasks.ask_json(
                    self.llm,
                    'consistency',
                    messages,
                    work.id,
                    llm_tasks.relations_ok,
                    override=data.get('llm'),
                )
                model = {'provider': answer['provider'], 'name': answer['model']}
            draft = Drafts(work).create(
                'relations', {'scope': 'work'}, {}, [review.relation_rows(work, result)], model=model
            )
            self.events.publish('draft', {'work': work.id, 'id': draft['id']})
            return {'draft': draft['id']}

        return self.jobs.submit('relations', f'관계 찾기 · {work.name}', runner, work_id=work.id)

    def consistency(self, work, data):
        """Check the work (or a scope of it) for contradictions: a consistency draft."""
        self.llm.require_consent(work, 'consistency', data.get('llm'))
        bundles = review.consistency_bundles(work, data.get('scope') or None)

        async def runner(progress):
            issues, model = [], None
            if self.mocked('consistency', data.get('llm')):
                await asyncio.sleep(0.4)
                for bundle in bundles[:1]:
                    head = bundle['items'][0]
                    quote = next(
                        (
                            line
                            for line in head['body'].splitlines()
                            if line.strip() and not line.startswith('#')
                        ),
                        '',
                    )
                    issues.append(
                        {
                            'type': 'ambiguous',
                            'items': [head['id']],
                            'quote': quote.strip(),
                            'quote_item': head['id'],
                            'explain': '(모의) 검사 흐름을 보여 주는 예시 문제입니다.',
                            'suggest': None,
                        }
                    )
            else:
                guideline = self.guideline(work, 'consistency.md')
                glossary = review.glossary_lines(work)
                for n, bundle in enumerate(bundles):
                    await progress(int(100 * n / max(1, len(bundles))) + 2)
                    messages = llm_tasks.consistency_messages(
                        bundle['person'],
                        bundle['items'],
                        bundle['relations'],
                        bundle['facts'],
                        glossary,
                        guideline,
                    )
                    result, answer = await llm_tasks.ask_json(
                        self.llm,
                        'consistency',
                        messages,
                        work.id,
                        llm_tasks.consistency_ok,
                        override=data.get('llm'),
                    )
                    issues.extend(result['issues'])
                    model = {'provider': answer['provider'], 'name': answer['model']}
            draft = Drafts(work).create(
                'consistency',
                {'scope': data.get('scope') or 'work'},
                {'people': [b['person'] for b in bundles]},
                [{'issues': review.normalize_issues(work, issues)}],
                model=model,
                guidelines=['consistency.md'],
            )
            self.events.publish('draft', {'work': work.id, 'id': draft['id']})
            return {'draft': draft['id']}

        return self.jobs.submit('consistency', f'모순 검사 · {work.name}', runner, work_id=work.id)

    def jsx_prompt(self, work, item, data):
        """The response text that calls one JSX component: a jsx_prompt draft."""
        self.llm.require_consent(work, 'jsx_prompt', data.get('llm'))
        props = data.get('props') or {}
        rule = review.response_rule(self.presets.effective(work.doc()))

        async def runner(progress):
            model = None
            if self.mocked('jsx_prompt', data.get('llm')):
                await asyncio.sleep(0.4)
                text = (
                    f'## {item["name"]}\n응답 맨 끝에 아래 형식으로 {item["name"]}을(를) 한 번 출력한다.\n'
                    f'{call_text(item["name"], props, rule) or "<" + item["name"] + " />"}\n(모의 문구)'
                )
            else:
                await progress(10)
                messages = llm_tasks.jsx_prompt_messages(
                    item['name'],
                    item['body'],
                    props,
                    self.guideline(work, 'jsx.md'),
                    self.guideline(work, 'platform.md'),
                    data.get('feedback', ''),
                )
                result, answer = await llm_tasks.ask_json(
                    self.llm,
                    'jsx_prompt',
                    messages,
                    work.id,
                    llm_tasks.jsx_prompt_ok,
                    override=data.get('llm'),
                )
                text = result['text'].strip()
                model = {'provider': answer['provider'], 'name': answer['model']}
            draft = Drafts(work).create(
                'jsx_prompt',
                {'id': item['meta'].get('id'), 'path': item['path'], 'name': item['name']},
                {'props': props, 'feedback': data.get('feedback', '')},
                [{'round': 1, 'text': text, 'elements': review.elements(text, item['name'], rule)}],
                model=model,
                guidelines=['platform.md', 'jsx.md'],
            )
            self.events.publish('draft', {'work': work.id, 'id': draft['id']})
            return {'draft': draft['id']}

        return self.jobs.submit('jsx_prompt', f'JSX 문구 · {item["name"]}', runner, work_id=work.id)

    def authoring(self, work, data, scale):
        """A work's skeleton from the answers to the authoring questions: an authoring draft."""
        self.llm.require_consent(work, 'authoring', data.get('llm'))
        answers = data.get('answers', [])

        async def runner(progress):
            model = None
            if self.mocked('authoring', data.get('llm')):
                for value in (25, 60, 90):
                    await asyncio.sleep(0.4)
                    await progress(value)
                skeleton = authoring.mock_skeleton(work, scale, answers)
            else:
                await progress(10)
                messages = llm_tasks.authoring_messages(
                    answers,
                    self.guideline(work, f'authoring/{scale}.md'),
                    self.guideline(work, 'platform.md'),
                    list(work.section_titles().values()),
                    scale,
                )
                result, answer = await llm_tasks.ask_json(
                    self.llm, 'authoring', messages, work.id, llm_tasks.authoring_ok, override=data.get('llm')
                )
                skeleton = llm_tasks.authoring_skeleton(result, work)
                model = {'provider': answer['provider'], 'name': answer['model']}
            draft = Drafts(work).create(
                'authoring',
                {'scope': 'work', 'scale': scale},
                {'answers': answers},
                [skeleton],
                model=model,
                guidelines=[f'authoring/{scale}.md', 'platform.md'],
            )
            self.events.publish('draft', {'work': work.id, 'id': draft['id']})
            return {'draft': draft['id']}

        return self.jobs.submit('authoring', f'뼈대 작성 · {work.name}', runner, work_id=work.id)

    def compression(self, work, data):
        """Shorter versions of one item: a compression draft with candidates."""
        self.llm.require_consent(work, 'compression', data.get('llm'))
        item = work.get_item(data['path'])

        rounds = max(1, min(4, int(data.get('candidates', 2))))
        locked = [int(n) for n in data.get('locked', [])]
        target = data.get('target_size')
        if target is not None and (isinstance(target, bool) or not isinstance(target, int) or target <= 0):
            raise AppError(
                Msg('server.editor.bad_target', 'Target size must be a positive number of bytes.'), 400
            )
        instruction = str(data.get('instructions') or '').strip()

        async def runner(progress):
            model = None
            if self.mocked('compression', data.get('llm')):
                for value in (20, 50, 80):
                    await asyncio.sleep(0.4)
                    await progress(value)
                blocks, candidates = mock_compress(item['body'], rounds)
            else:
                blocks, messages = llm_tasks.compression_messages(
                    item['body'],
                    '\n\n'.join(filter(None, [self.guideline(work, 'compression.md'), instruction])),
                    self.guideline(work, 'platform.md'),
                    data.get('target_size'),
                    locked,
                )
                candidates = []
                for n in range(rounds):
                    await progress(int(100 * n / rounds) + 5)
                    result, answer = await llm_tasks.ask_json(
                        self.llm,
                        'compression',
                        llm_tasks.compression_round(messages, n),
                        work.id,
                        llm_tasks.compression_ok,
                        override=data.get('llm'),
                    )
                    candidates.append(llm_tasks.compression_candidate(result, blocks, locked))
                    model = {'provider': answer['provider'], 'name': answer['model']}
            draft = Drafts(work).create(
                'compression',
                {'id': item['meta'].get('id'), 'path': item['path'], 'base_hash': item['hash']},
                {'target_size': data.get('target_size'), 'keep': locked, 'feedback': []},
                candidates,
                model=model,
                guidelines=['platform.md', 'compression.md'],
                blocks=blocks,
            )
            self.events.publish('draft', {'work': work.id, 'id': draft['id']})
            return {'draft': draft['id']}

        gpu = self.llm.on_gpu('compression', data.get('llm'))
        return self.jobs.submit('compression', f'압축 · {item["name"]}', runner, gpu=gpu, work_id=work.id)

    def image_prompt(self, work, cid, data):
        """A character's appearance and outfits as image tags: an image_prompt draft (#150).

        Without ``range`` the whole text is converted (A): the answer quotes the sentences each part comes from.
        With ``range`` ({text, part: appearance | outfit, outfit?: id, name?: new outfit name, add?: bool}) only the
        chosen text is converted into that one part (E).
        """
        item = next(
            (i for i in work.index() if i['kind'] == 'character' and i['meta'].get('id') == cid), None
        )
        if item is None:
            raise AppError(Msg('server.image.no_character', 'Character {id} was not found.', id=cid), 404)
        body_text = work.get_item(item['path'])['body']
        design_path = image_designs.character_design_path(work, cid)
        old = read_json(design_path)
        base_design_revision = image_designs.revision(old)
        old = old or {}
        chosen = _image_range(data.get('range'), old, body_text)
        self.llm.require_consent(work, 'image_prompt', data.get('llm'))
        compose = (
            read_json(work.app / 'image' / 'compose.json')
            or read_json(self.paths.data / 'image' / 'compose.json')
            or {}
        )
        slots = compose.get('slots') or [{'id': 'full', 'name': '전체'}, {'id': 'top', 'name': '상의'}]
        allowed = {slot['id'] for slot in slots}
        existing = [str(o.get('name') or k) for k, o in (old.get('outfits') or {}).items()]

        def outfit_slots(got):
            return {
                k: {'prompt': llm_tasks.tags(v)}
                for k, v in (got.get('slots') or {}).items()
                if k in allowed and llm_tasks.tags(v)
            }

        def evidence(got):
            # Only sentences that really are in the text count as its source.
            quoted = [str(q) for q in got.get('evidence') or [] if isinstance(q, str)]
            return [q for q in dict.fromkeys(quoted) if image_designs.found_in(body_text, q)]

        async def whole(progress):
            model = None
            if self.mocked('image_prompt', data.get('llm')):
                await asyncio.sleep(0.6)
                await progress(60)
                lines = [
                    line.strip() for line in body_text.splitlines() if line.strip() and not line.startswith('#')
                ]
                quote = lines[:1]
                result = {
                    'appearance': {'prompt': ['1girl', 'solo', '(모의 태그)'], 'negative': [], 'evidence': quote},
                    'outfits': [
                        {'name': name, 'slots': {'top': ['(모의 태그)']}, 'negative': [], 'evidence': quote}
                        for name in existing or ['기본']
                    ],
                }
            else:
                await progress(10)
                messages = llm_tasks.image_messages(
                    body_text, existing, slots, self.guideline(work, 'image-prompt.md')
                )
                result, answer = await llm_tasks.ask_json(
                    self.llm, 'image_prompt', messages, work.id, llm_tasks.image_ok, override=data.get('llm')
                )
                model = {'provider': answer['provider'], 'name': answer['model']}
            got = result['appearance']
            design = {
                'schema_version': 1,
                'trigger': old.get('trigger') or f'{work.id.lower()}_{cid.lower()}',
                'appearance': {
                    'prompt': llm_tasks.tags(got.get('prompt')),
                    'negative': llm_tasks.tags(got.get('negative')),
                    'source': image_designs.make_source(evidence(got), 'auto'),
                },
                'outfits': {},
                'default_outfit': None,
            }
            by_name = {str(o.get('name') or k): k for k, o in (old.get('outfits') or {}).items()}
            taken = set(old.get('outfits') or {}) | set(old.get('retired_outfit_ids') or [])
            for got in result['outfits']:
                if not isinstance(got, dict) or not str(got.get('name') or '').strip():
                    continue
                name = str(got['name']).strip()[:80]
                key = by_name.get(name)
                if key is None or key in design['outfits']:
                    key = image_designs.new_outfit_id(taken | set(design['outfits']))
                design['outfits'][key] = {
                    'name': name,
                    'slots': outfit_slots(got),
                    'negative': llm_tasks.tags(got.get('negative')),
                    'source': image_designs.make_source(evidence(got), 'auto'),
                }
            return image_designs.reconcile_conversion(old, design), model, None

        async def ranged(progress):
            part, texts = chosen['part'], chosen['texts']
            model = None
            if self.mocked('image_prompt', data.get('llm')):
                await asyncio.sleep(0.4)
                await progress(60)
                result = {'prompt': ['(모의 태그)'], 'slots': {'top': ['(모의 태그)']}, 'negative': []}
            else:
                await progress(10)
                messages = llm_tasks.image_range_messages(
                    '\n\n'.join(texts), part, slots, self.guideline(work, 'image-prompt.md')
                )
                result, answer = await llm_tasks.ask_json(
                    self.llm,
                    'image_prompt',
                    messages,
                    work.id,
                    llm_tasks.image_range_ok,
                    override=data.get('llm'),
                )
                model = {'provider': answer['provider'], 'name': answer['model']}
            design = deepcopy(old) or {
                'schema_version': 1,
                'trigger': f'{work.id.lower()}_{cid.lower()}',
                'outfits': {},
                'default_outfit': None,
            }
            design.setdefault('appearance', {'prompt': [], 'negative': []})
            design.setdefault('outfits', {})
            source = {'spans': chosen['spans']}
            if part == 'appearance':
                design['appearance'] = {
                    **design['appearance'],
                    'prompt': llm_tasks.tags(result.get('prompt')),
                    'negative': llm_tasks.tags(result.get('negative')),
                    'source': source,
                }
                focus = 'appearance'
            else:
                key = chosen['outfit'] or image_designs.new_outfit_id(
                    set(design['outfits']) | set(design.get('retired_outfit_ids') or [])
                )
                before = design['outfits'].get(key) or {}
                design['outfits'][key] = {
                    **before,
                    'name': chosen['name'] or before.get('name') or key,
                    'slots': outfit_slots(result),
                    'negative': llm_tasks.tags(result.get('negative')),
                    'source': source,
                }
                if not design.get('default_outfit'):
                    design['default_outfit'] = key
                focus = f'outfit:{key}'
            image_designs.validate(design)
            return design, model, focus

        async def runner(progress):
            design, model, focus = await (ranged(progress) if chosen else whole(progress))
            draft = Drafts(work).create(
                'image_prompt',
                {
                    'id': cid,
                    'path': item['path'],
                    'base_hash': item['hash'],
                    'base_design_revision': base_design_revision,
                },
                {'parts': [focus] if focus else 'all', 'focus': focus, 'previous_design': old},
                [{'round': 1, 'design': design}],
                model=model,
                guidelines=['image-prompt.md'],
            )
            self.events.publish('draft', {'work': work.id, 'id': draft['id']})
            return {'draft': draft['id']}

        return self.jobs.submit(
            'image_prompt',
            f'이미지 프롬프트 · {item["name"]}',
            runner,
            gpu=self.llm.on_gpu('image_prompt', data.get('llm')),
            work_id=work.id,
        )

    def editor_action(self, work, action, data):
        """Editor actions (content review, consistency of chosen items, formatting): a draft."""
        action = {'content_review': 'content-review'}.get(action, action)
        if action not in ('content-review', 'format', 'consistency'):
            raise AppError(Msg('server.editor.unknown_action', 'Unknown editor action.'), 404)
        task = 'compression' if action == 'format' else 'consistency'
        self.llm.require_consent(work, task, data.get('llm'))
        mode = data.get('mode', 'tidy')
        if action == 'format' and mode not in ('tidy', 'template'):
            raise AppError(Msg('server.editor.bad_format_mode', 'Format mode must be tidy or template.'), 400)
        guideline = self.guideline(work, 'consistency.md' if task == 'consistency' else 'platform.md')
        instruction = str(data.get('instruction') or '')

        if action == 'consistency':
            paths = data.get('compare_paths')
            if not isinstance(paths, list) or len(paths) < 2 or any(not isinstance(p, str) for p in paths):
                raise AppError(
                    Msg(
                        'server.editor.compare_paths_required',
                        'Choose at least two paths to compare explicitly.',
                    ),
                    400,
                )
            if len(set(paths)) != len(paths):
                raise AppError(
                    Msg('server.editor.compare_paths_duplicate', 'Comparison paths must be unique.'), 400
                )
            items = [_markdown_item(work, path) for path in paths]
        else:
            item = _markdown_item(work, data.get('path', ''))
            items = [item]

        async def runner(progress):
            model = None
            provider, _, _ = self.llm.resolve(task, data.get('llm'))
            if provider.get('type') == 'mock':
                await progress(50)
                if action == 'format':
                    result = {'text': items[0]['body'], 'note': '모의 형식 정리 결과'}
                else:
                    result = {'issues': []}
            else:
                if action == 'content-review':
                    messages = editor_tasks.review_messages(
                        items[0]['path'], items[0]['body'], guideline, instruction
                    )
                    check = editor_tasks.issues_ok
                elif action == 'consistency':
                    messages = editor_tasks.consistency_messages(items, guideline, instruction)
                    check = editor_tasks.issues_ok
                else:
                    messages = editor_tasks.format_messages(
                        items[0]['path'],
                        items[0]['body'],
                        mode,
                        str(data.get('template') or ''),
                        str(data.get('instruction') or ''),
                        guideline,
                    )
                    check = editor_tasks.edit_ok
                result, answer = await llm_tasks.ask_json(
                    self.llm, task, messages, work.id, check, override=data.get('llm')
                )
                model = {'provider': answer['provider'], 'name': answer['model']}

            if action == 'format' and not editor_tasks.preserves_protected(items[0]['body'], result['text']):
                raise AppError(
                    Msg(
                        'server.editor.protected_syntax_changed',
                        'Formatting removed or changed a reserved placeholder or JSX tag.',
                    ),
                    422,
                )

            if action == 'content-review':
                target = {
                    'scope': 'item',
                    'id': items[0]['meta'].get('id'),
                    'path': items[0]['path'],
                    'base_hash': items[0]['hash'],
                }
                candidates = [
                    {
                        'issues': [
                            {**issue, 'path': issue.get('path') or items[0]['path']}
                            for issue in result['issues']
                        ]
                    }
                ]
                draft_kind = 'content_review'
            elif action == 'consistency':
                target = {
                    'scope': 'items',
                    'paths': paths,
                    'base_hashes': {i['path']: i['hash'] for i in items},
                }
                candidates = [{'issues': result['issues']}]
                draft_kind = 'content_review'
            else:
                target = {
                    'scope': 'item',
                    'id': items[0]['meta'].get('id'),
                    'path': items[0]['path'],
                    'base_hash': items[0]['hash'],
                }
                candidates = [{'text': result['text'], 'note': result.get('note', '')}]
                draft_kind = 'text_edit'
            draft = Drafts(work).create(
                draft_kind,
                target,
                {
                    'action': action,
                    'original': items[0]['body'] if action != 'consistency' else None,
                    'compare_paths': paths if action == 'consistency' else None,
                    'mode': data.get('mode'),
                    'template': data.get('template'),
                    'instruction': instruction,
                },
                candidates,
                model=model,
                guidelines=['consistency.md' if task == 'consistency' else 'platform.md'],
            )
            self.events.publish('draft', {'work': work.id, 'id': draft['id']})
            return {'draft': draft['id']}

        return self.jobs.submit(
            task,
            f'편집기 · {work.name}',
            runner,
            gpu=action == 'format' and self.llm.on_gpu(task, data.get('llm')),
            work_id=work.id,
        )


def _image_range(value, design, body):
    """A range conversion request checked against the design and the saved text:
    ``{part, outfit, name, texts, spans}``, or None for a whole-text conversion."""
    if value is None:
        return None
    if not isinstance(value, dict) or value.get('part') not in ('appearance', 'outfit'):
        raise AppError(
            Msg('server.image.range.invalid', 'Choose the appearance or an outfit for the range.'), 400
        )
    text = str(value.get('text') or '').strip()
    if not text:
        raise AppError(Msg('server.image.range.empty', 'Select the text to convert first.'), 400)
    if len(text) > image_designs.MAX_SPAN:
        raise AppError(Msg('server.image.range.too_long', 'The selected text is too long.'), 400)
    if not image_designs.found_in(body, text):
        raise AppError(
            Msg(
                'server.image.range.not_in_text',
                'The selected text is not in the saved text. Save the character first.',
            ),
            400,
        )
    outfit, name = None, None
    if value['part'] == 'outfit':
        outfit = value.get('outfit') or None
        if outfit is not None and outfit not in (design.get('outfits') or {}):
            raise AppError(
                Msg('server.image.range.no_outfit', 'The outfit {id} was not found.', id=str(outfit)), 404
            )
        if outfit is None:
            name = str(value.get('name') or '').strip()[:80]
            if not name:
                raise AppError(Msg('server.image.range.name', 'Give the new outfit a name.'), 400)
    if value['part'] == 'appearance':
        current = design.get('appearance')
    else:
        current = (design.get('outfits') or {}).get(outfit)
    spans = []
    if value.get('add') and current:
        # Adding a range keeps the part's other pieces still in the text, and converts them all together.
        spans = [s for s in image_designs.spans_of(current) if image_designs.found_in(body, s['text'])]
    if not any(image_designs.found_in(s['text'], text) and image_designs.found_in(text, s['text']) for s in spans):
        spans.append({'text': text, 'by': 'pick'})
    spans = spans[: image_designs.MAX_SPANS]
    return {
        'part': value['part'],
        'outfit': outfit,
        'name': name,
        'texts': [s['text'] for s in spans],
        'spans': spans,
    }


def _markdown_item(work, path):
    item = work.get_item(path)
    if item['meta_error']:
        raise AppError(
            Msg('server.editor.invalid_metadata', 'Fix the item metadata before using this action.'), 400
        )
    if not path.lower().endswith('.md'):
        raise AppError(Msg('server.editor.markdown_only', 'This action supports Markdown content only.'), 400)
    return item
