"""Chat test sets (#50): a start situation, a persona and a list of inputs saved under a name, run again later and
compared answer by answer. There is no scoring (decision 0017): a person reads the answers side by side.

``.atelierx/tests/sets.json`` holds the sets; every run is ``.atelierx/tests/runs/<time>-<set id>.json`` with the model it
used and the snapshot of the work it ran against, so two runs say what changed between them.
"""

import re
import secrets
from datetime import datetime

from . import revisions
from .fsutil import read_json, write_json
from .i18n import AppError, Msg
from .snapshots import Snapshots
from .works import now_iso

SET_ID = re.compile(r'^[a-z0-9]{8}$')
RUN_ID = re.compile(r'^\d{8}T\d{6}\d{3}-[a-z0-9]{8}$')
MAX_INPUTS = 50
MAX_INPUT = 8000
MAX_RUNS_PER_SET = 50
STATUSES = ('running', 'done', 'stopped', 'error')


class TestSets:
    __test__ = False  # not a pytest class

    def __init__(self, work):
        self.work = work
        self.folder = work.app / 'tests'
        self.sets_file = self.folder / 'sets.json'
        self.runs = self.folder / 'runs'

    # --- sets -------------------------------------------------------------------------------------------------------
    def load(self):
        doc = read_json(self.sets_file) or {'schema_version': 1, 'sets': []}
        sets = doc.get('sets') or []
        return {'sets': sets, 'revision': revisions.of(sets)}

    def save(self, data):
        """Replace the list. ``base_revision`` must match the list the screen started from."""
        if not isinstance(data, dict) or not isinstance(data.get('sets'), list):
            raise AppError(Msg('server.tests.invalid', 'A list of test sets is required.'), 400)
        current = self.load()
        if data.get('base_revision') != current['revision']:
            raise AppError(
                Msg('server.tests.stale', 'The test sets changed in another window. Reopen them.'), 409
            )
        out, seen = [], set()
        for entry in data['sets']:
            if not isinstance(entry, dict):
                raise AppError(Msg('server.tests.invalid', 'A list of test sets is required.'), 400)
            set_id = str(entry.get('id') or '')
            if not SET_ID.match(set_id) or set_id in seen:
                set_id = secrets.token_hex(4)
            seen.add(set_id)
            name = str(entry.get('name') or '').strip()[:100]
            inputs = [str(x)[:MAX_INPUT] for x in entry.get('inputs') or [] if str(x).strip()][:MAX_INPUTS]
            if not name or not inputs:
                raise AppError(
                    Msg('server.tests.empty', 'A test set needs a name and at least one input.'), 400
                )
            start = entry.get('start')
            if start is not None:
                start = self.work.rel(self.work.resolve(str(start)))
            persona = entry.get('persona') if isinstance(entry.get('persona'), dict) else None
            if persona:
                persona = {
                    'name': str(persona.get('name') or '')[:100],
                    'description': str(persona.get('description') or '')[:4000],
                }
            out.append(
                {
                    'id': set_id,
                    'name': name,
                    'start': start,
                    'persona': persona,
                    'inputs': inputs,
                    'updated_at': now_iso(),
                }
            )
        write_json(self.sets_file, {'schema_version': 1, 'sets': out})
        return self.load()

    def get_set(self, set_id):
        found = next((s for s in self.load()['sets'] if s['id'] == set_id), None)
        if found is None:
            raise AppError(Msg('server.tests.no_set', 'This test set does not exist.'), 404)
        return found

    # --- runs -------------------------------------------------------------------------------------------------------
    def start_run(self, set_id, model):
        """A new run record: the set as it is now, the model, and the work's snapshot (made when anything changed)."""
        test_set = self.get_set(set_id)
        snaps = Snapshots(self.work)
        snaps.create('test')
        latest = snaps.list()
        snapshot = latest[0] if latest else None
        now = datetime.now().astimezone()
        run_id = f'{now:%Y%m%dT%H%M%S}{now.microsecond // 1000:03d}-{set_id}'
        doc = {
            'schema_version': 1,
            'id': run_id,
            'set': {k: test_set[k] for k in ('id', 'name', 'start', 'persona', 'inputs')},
            'model': model,
            'snapshot': {
                'id': snapshot['id'],
                'created_at': snapshot.get('created_at'),
                'label': snapshot.get('label'),
            }
            if snapshot
            else None,
            'started_at': now_iso(),
            'finished_at': None,
            'status': 'running',
            'turns': [],
        }
        self.runs.mkdir(parents=True, exist_ok=True)
        write_json(self.runs / f'{run_id}.json', doc)
        self._prune(set_id)
        return doc

    def _path(self, run_id):
        if not RUN_ID.match(str(run_id or '')):
            raise AppError(Msg('server.tests.no_run', 'This run does not exist.'), 404)
        path = self.runs / f'{run_id}.json'
        if not path.is_file():
            raise AppError(Msg('server.tests.no_run', 'This run does not exist.'), 404)
        return path

    def record(self, run_id, data):
        """Write the turns so far (the screen sends them after every answer) and, at the end, the status."""
        path = self._path(run_id)
        doc = read_json(path)
        turns = []
        for turn in (data or {}).get('turns') or []:
            if isinstance(turn, dict):
                turns.append(
                    {
                        'input': str(turn.get('input') or '')[:MAX_INPUT],
                        'reply': str(turn.get('reply') or ''),
                        'error': str(turn.get('error'))[:2000] if turn.get('error') else None,
                    }
                )
        doc['turns'] = turns[:MAX_INPUTS]
        status = (data or {}).get('status')
        if status in STATUSES:
            doc['status'] = status
            if status != 'running':
                doc['finished_at'] = now_iso()
        write_json(path, doc)
        return doc

    def run(self, run_id):
        return read_json(self._path(run_id))

    def list_runs(self, set_id=None):
        out = []
        if self.runs.is_dir():
            for path in sorted(self.runs.glob('*.json'), reverse=True):
                doc = read_json(path) or {}
                if set_id and (doc.get('set') or {}).get('id') != set_id:
                    continue
                out.append(
                    {
                        'id': doc.get('id', path.stem),
                        'set': {k: (doc.get('set') or {}).get(k) for k in ('id', 'name')},
                        'model': doc.get('model'),
                        'snapshot': doc.get('snapshot'),
                        'started_at': doc.get('started_at'),
                        'status': doc.get('status'),
                        'turns': len(doc.get('turns') or []),
                        'inputs': len((doc.get('set') or {}).get('inputs') or []),
                    }
                )
        return out

    def delete_run(self, run_id):
        self._path(run_id).unlink()
        return self.list_runs()

    def _prune(self, set_id):
        mine = sorted(self.runs.glob(f'*-{set_id}.json'), reverse=True)
        for old in mine[MAX_RUNS_PER_SET:]:
            old.unlink(missing_ok=True)
