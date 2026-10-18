"""Recovery must work after an uncaught interruption, before any active writes."""

import json
from pathlib import Path

import pytest

from atelierx.image import uuid_migration as migration
from test_uuid_migration import fixture


class PowerLoss(BaseException):
    pass


def active_bytes(paths):
    return {
        path.relative_to(paths.root).as_posix(): path.read_bytes()
        for folder in (paths.data, paths.output)
        for path in folder.rglob('*')
        if path.is_file()
    }


def interrupt(paths, monkeypatch, phase):
    replace = migration.os.replace
    unlink = Path.unlink

    def stopped_replace(source, target):
        replace(source, target)
        if str(source).endswith('.uuid-write') and (
            phase == 'first_write' or (phase == 'mapping_write' and Path(target).name == migration.MAP_NAME)
        ):
            raise PowerLoss()

    def stopped_unlink(path, *args, **kwargs):
        unlink(path, *args, **kwargs)
        if phase == 'old_preset_removal' and path.name == 'soft.json':
            raise PowerLoss()

    with monkeypatch.context() as patch:
        patch.setattr(migration.os, 'replace', stopped_replace)
        patch.setattr(Path, 'unlink', stopped_unlink)
        with pytest.raises(PowerLoss):
            migration.migrate(paths)
    journal = paths.state / 'image/uuid-migration/journal.json'
    assert journal.is_file(), 'Interruption must leave the on-disk recovery journal'
    return journal


@pytest.mark.parametrize('phase', ['first_write', 'old_preset_removal', 'mapping_write'])
def test_uncaught_interruption_restores_exact_active_bytes_before_retry(paths, monkeypatch, phase):
    fixture(paths)
    before = active_bytes(paths)
    journal = interrupt(paths, monkeypatch, phase)
    assert active_bytes(paths) != before
    migration.recover(paths)
    assert active_bytes(paths) == before
    assert not journal.exists()
    migrated = migration.migrate(paths)
    after = active_bytes(paths)
    assert migration.migrate(paths) == migrated
    assert active_bytes(paths) == after


@pytest.mark.parametrize('damage', ['missing', 'modified'])
def test_damaged_backup_is_rejected_before_any_restore_write(paths, monkeypatch, damage):
    fixture(paths)
    journal = interrupt(paths, monkeypatch, 'mapping_write')
    doc = json.loads(journal.read_text(encoding='utf-8'))
    entry = next(item for item in reversed(doc['files']) if item['existed'])
    backup = journal.parent / doc['backup'] / entry['path']
    if damage == 'missing':
        backup.unlink()
    else:
        backup.write_bytes(b'corrupted backup')
    before = active_bytes(paths)
    with pytest.raises(ValueError, match='backup'):
        migration.recover(paths)
    assert active_bytes(paths) == before
    assert journal.exists()


def test_unsafe_journal_is_rejected_before_valid_earlier_entries_are_restored(paths, monkeypatch):
    fixture(paths)
    journal = interrupt(paths, monkeypatch, 'mapping_write')
    doc = json.loads(journal.read_text(encoding='utf-8'))
    doc['files'].append({'path': '../outside.txt', 'existed': False})
    journal.write_text(json.dumps(doc), encoding='utf-8')
    before = active_bytes(paths)
    with pytest.raises(ValueError, match='unsafe'):
        migration.recover(paths)
    assert active_bytes(paths) == before
    assert journal.exists()


@pytest.mark.parametrize('bad', ['not-a-uuid', 7, None])
def test_invalid_mapping_value_preserves_all_active_data(paths, bad):
    fixture(paths)
    path = paths.data / 'image' / migration.MAP_NAME
    path.write_text(
        json.dumps({'schema_version': 1, 'library': {'expressions/global/smile': bad}, 'presets': {}}),
        encoding='utf-8',
    )
    before = active_bytes(paths)
    with pytest.raises(ValueError):
        migration.migrate(paths)
    assert active_bytes(paths) == before
