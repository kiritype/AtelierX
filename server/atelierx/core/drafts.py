"""Drafts: LLM results waiting for review (data-model: 임시 항목), and the block splitter used by compression."""

import re
import secrets
from datetime import datetime

from .fsutil import read_json, sha256_text, write_json
from .i18n import AppError, Msg
from .works import now_iso


def split_blocks(body):
    """Blocks are chunks separated by blank lines; a heading line is always its own block."""
    blocks, current, start, pos = [], [], 0, 0
    for line in body.splitlines(keepends=True):
        if line.strip() == '' or line.startswith('#'):
            if current:
                blocks.append((start, ''.join(current)))
                current = []
            if line.startswith('#'):
                blocks.append((pos, line))
        else:
            if not current:
                start = pos
            current.append(line)
        pos += len(line)
    if current:
        blocks.append((start, ''.join(current)))
    return [
        {'n': i + 1, 'start': s, 'end': s + len(t), 'text': t.rstrip('\n'), 'hash': sha256_text(t)}
        for i, (s, t) in enumerate(blocks)
    ]


class Drafts:
    def __init__(self, work):
        self.work = work
        self.root = work.app / 'drafts'

    def create(self, kind, target, request, candidates, model=None, guidelines=None, blocks=None):
        draft_id = f'{datetime.now().astimezone().strftime("%Y%m%dT%H%M%S")}-{kind}-{secrets.token_hex(2)}'
        doc = {
            'schema_version': 1,
            'kind': kind,
            'target': target,
            'guidelines': guidelines or [],
            'model': model or {'provider': 'mock', 'name': 'mock'},
            'request': request,
            'blocks': blocks,
            'candidates': candidates,
            'composition': None,
            'status': 'pending',
            'cost': None,
            'created_at': now_iso(),
        }
        write_json(self.root / f'{draft_id}.json', doc)
        return {'id': draft_id, **doc}

    def list(self, status=None):
        out = []
        if self.root.is_dir():
            for path in sorted(self.root.glob('*.json'), reverse=True):
                doc = read_json(path)
                if status and doc.get('status') != status:
                    continue
                out.append(
                    {
                        'id': path.stem,
                        'kind': doc['kind'],
                        'target': doc['target'],
                        'status': doc['status'],
                        'created_at': doc['created_at'],
                    }
                )
        return out

    def get(self, draft_id):
        doc = read_json(self.root / f'{draft_id}.json')
        if doc is None:
            raise AppError(Msg('server.drafts.missing', 'This draft does not exist.'), 404)
        return {'id': draft_id, **doc}

    def save(self, draft_id, doc):
        doc = {k: v for k, v in doc.items() if k != 'id'}
        write_json(self.root / f'{draft_id}.json', doc)

    def set_status(self, draft_id, status):
        doc = self.get(draft_id)
        doc['status'] = status
        self.save(draft_id, doc)
        return doc

    def apply_text(self, draft_id, text, mode='overwrite', new_name=None, enable='new'):
        """Write an adopted body. ``mode`` is 'overwrite' or 'new_file'."""
        doc = self.get(draft_id)
        rel = doc['target']['path']
        item = self.work.get_item(rel)
        if doc['status'] != 'pending':
            raise AppError(Msg('server.drafts.not_pending', 'This draft has already been handled.'), 409)
        if mode == 'overwrite' and doc['target'].get('base_hash') != item['hash']:
            raise AppError(Msg('server.drafts.stale', 'The source changed after this draft was created. Review a new result or save as a new file.'), 409)
        if mode == 'overwrite':
            self.work.save_item(rel, {}, text, item['hash'])
            result_path = rel
        else:
            path = self.work.resolve(rel)
            new_name = new_name or f'{path.stem} (압축){path.suffix}'
            new_rel = f'{rel.rsplit("/", 1)[0]}/{new_name}' if '/' in rel else new_name
            created = self.work.create_file(new_rel, item['kind'])
            meta = {k: v for k, v in item['meta'].items() if k != 'id'}
            meta['id'] = self.work.suggest_id(item['kind'])
            meta['enabled'] = enable == 'new'
            self.work.save_item(created['path'], meta, text, None)
            if enable == 'new':
                self.work.save_item(rel, {'enabled': False}, None, None)
            result_path = created['path']
        self.set_status(draft_id, 'applied')
        return {'path': result_path}


def mock_compress(body, rounds=2):
    """Stand-in for the LLM until 2단계: shortens each block mechanically so the review flow can be tried."""
    blocks = split_blocks(body)
    candidates = []
    for level in range(1, rounds + 1):
        results = []
        for block in blocks:
            text = block['text']
            if text.startswith('#'):
                results.append({'from': block['n'], 'to': block['n'], 'text': text})
                continue
            sentences = re.split(r'(?<=[.!?。])\s+', text)
            keep = sentences[: max(1, len(sentences) - level)]
            short = ' '.join(keep)
            if level > 1:
                short = re.sub(r'\s*\([^)]*\)', '', short)
            results.append({'from': block['n'], 'to': block['n'], 'text': short})
        size = sum(len(r['text'].encode('utf-8')) for r in results)
        candidates.append(
            {'round': 1, 'note': f'모의 후보 {level}', 'size': size, 'blocks': results, 'checks': {}}
        )
    return blocks, candidates
