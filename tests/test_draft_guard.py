from pathlib import Path

import pytest

from atelierx.core.drafts import Drafts
from atelierx.core.fsutil import sha256_text
from atelierx.core.i18n import AppError


class FakeWork:
    def __init__(self, root: Path):
        self.app = root / '.atelierx'
        self.app.mkdir()
        self.item = {
            'path': 'main.md',
            'kind': 'main',
            'meta': {'id': 'M001', 'enabled': True},
            'body': 'updated on disk',
            'hash': sha256_text('updated on disk'),
        }
        self.created = []
        self.saves = []

    def get_item(self, rel):
        assert rel == self.item['path']
        return self.item

    def save_item(self, rel, meta_changes, body, base_hash):
        self.saves.append((rel, meta_changes, body, base_hash))
        return {'path': rel}

    def resolve(self, rel):
        return self.app.parent / rel

    def create_file(self, rel, kind):
        self.created.append((rel, kind))
        return {'path': rel}

    def suggest_id(self, kind):
        return 'M002'


def make_draft(work, status='pending'):
    drafts = Drafts(work)
    draft = drafts.create(
        'compress',
        {'path': 'main.md', 'base_hash': sha256_text('original queued text')},
        {'original': 'original queued text'},
        [{'text': 'compressed text'}],
    )
    if status != 'pending':
        drafts.set_status(draft['id'], status)
    return drafts, draft


@pytest.mark.parametrize('status', ['applied', 'rejected'])
def test_handled_draft_cannot_be_applied_again(tmp_path, status):
    work = FakeWork(tmp_path)
    drafts, draft = make_draft(work, status)

    with pytest.raises(AppError) as error:
        drafts.apply_text(draft['id'], 'must not be written')

    assert error.value.status == 409
    assert error.value.msg.key == 'server.drafts.not_pending'
    assert work.saves == []
    assert work.created == []


def test_stale_draft_cannot_overwrite_but_can_be_saved_as_new_file(tmp_path):
    work = FakeWork(tmp_path)
    drafts, draft = make_draft(work)

    with pytest.raises(AppError) as error:
        drafts.apply_text(draft['id'], 'compressed text', mode='overwrite')

    assert error.value.status == 409
    assert error.value.msg.key == 'server.drafts.stale'
    assert work.saves == []

    result = drafts.apply_text(draft['id'], 'compressed text', mode='new_file')

    assert result['path'] == 'main (압축).md'
    assert work.created == [('main (압축).md', 'main')]
    assert work.saves == [
        ('main (압축).md', {'id': 'M002', 'enabled': True}, 'compressed text', None),
        ('main.md', {'enabled': False}, None, None),
    ]
    assert drafts.get(draft['id'])['status'] == 'applied'
