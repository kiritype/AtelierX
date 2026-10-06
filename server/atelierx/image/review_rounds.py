"""VLM auto review (21-gallery: 자동 검수). A vision model checks generated images against their prompt parts.

Each queued image asked to be reviewed opens a round. When the queue has no generation left, the worker
frees the image server's memory, asks the model connection of the ``image_review`` task about every ready
image, and records the verdict next to the person's. A clear fail is regenerated with a new seed up to the
configured limit; uncertain answers and errors wait for a person. A person's pass ends the round.

The model's verdict is advice only: nothing is adopted without a person.
"""

import asyncio
import base64
import copy
import io
import logging
import secrets
import subprocess
import threading
import uuid
from urllib.parse import unquote

from PIL import Image

from ..core.i18n import AppError, Msg, message_of
from ..core.llm import parse_json
from .util import atomic_json, now, read_json, settings_file, state_file

log = logging.getLogger(__name__)

DEFAULTS = {
    'enabled': False,
    'max_auto_regenerations': 3,
    'instruction': '',
    'unload_command': [],
}
DEFAULT_INSTRUCTION = (
    'Assess this generated character image against the visible requirements below only. '
    'PASS needs clear evidence for every visible requirement; FAIL means a clear mismatch; '
    'UNCERTAIN means the evidence is not enough. Do not infer hidden details. '
    'Count each rendered person. Answer only JSON: {"verdict": "pass|fail|uncertain", "evidence": "short reason"}.'
)
CONTRADICTION = ('missing', 'absent', 'wrong', 'cannot tell', 'unclear', 'mismatch', 'not visible')
OPEN = ('waiting_generation', 'pending_review', 'reviewing')
SHOWN = (
    'waiting_generation',
    'pending_review',
    'reviewing',
    'awaiting_human',
    'needs_attention',
    'limit_reached',
)


class ReviewRounds:
    def __init__(self, runtime):
        self.rt = runtime
        self.lock = threading.RLock()
        self.settings_path = settings_file(runtime.paths, 'review.json')
        self.path = state_file(runtime.paths, 'review_rounds.json')
        self.settings = {**DEFAULTS, **(read_json(self.settings_path) or {})}
        self.rounds = (read_json(self.path) or {}).get('rounds') or []
        for round_ in self.rounds:
            # A review cut off by a restart is looked at again rather than silently redone.
            if round_['status'] == 'reviewing':
                round_.update(status='pending_review')

    def persist(self):
        atomic_json(self.path, {'schema_version': 1, 'rounds': self.rounds})

    # --- settings ---------------------------------------------------------------------------------------------------
    def public_settings(self):
        provider = None
        try:
            found, model, _ = self.rt.llm.resolve('image_review')
            provider = {
                'id': found['id'],
                'name': found.get('name'),
                'model': model,
                'local': self.rt.llm.is_local(found),
            }
        except AppError as error:
            provider = {'error': error.msg}
        return {**self.settings, 'default_instruction': DEFAULT_INSTRUCTION, 'connection': provider}

    def save_settings(self, body):
        if not isinstance(body, dict):
            raise ValueError(Msg('server.review.invalid_settings', 'Invalid review settings.'))
        merged = {**self.settings, **{k: body[k] for k in DEFAULTS if k in body}}
        limit = merged['max_auto_regenerations']
        if isinstance(limit, bool) or not isinstance(limit, int) or not 0 <= limit <= 20:
            raise ValueError(
                Msg('server.review.limit', 'Automatic regenerations must be a whole number from 0 to 20.')
            )
        command = merged['unload_command']
        if isinstance(command, str):
            command = command.split()
        if not isinstance(command, list) or not all(
            isinstance(x, str) and 0 < len(x) < 1000 for x in command
        ):
            raise ValueError(Msg('server.review.invalid_settings', 'Invalid review settings.'))
        if not isinstance(merged['instruction'], str) or len(merged['instruction']) > 6000:
            raise ValueError(Msg('server.review.invalid_settings', 'Invalid review settings.'))
        merged.update(unload_command=command, enabled=bool(merged['enabled']))
        if merged['enabled']:
            self.rt.llm.resolve('image_review')  # no usable connection: say so now, not at review time
        if self.rt.gpu.held_by('validation'):
            raise ValueError(
                Msg(
                    'server.pipeline.vlm_review_is_using_the_gpu',
                    'VLM review is using the GPU. Change this after it finishes.',
                )
            )
        self.settings = merged
        atomic_json(self.settings_path, merged)
        return self.public_settings()

    # --- rounds -----------------------------------------------------------------------------------------------------
    @staticmethod
    def combo(job):
        return [str(job.get(k) or '') for k in ('work_id', 'character_id', 'outfit_id', 'expression_id')]

    def _new_round(self, job, source_path='', manual=False):
        combo = self.combo(job)
        return {
            'id': uuid.uuid4().hex,
            'status': 'waiting_generation',
            'created_at': now(),
            'combo': combo,
            'expression_name': job.get('expression_name'),
            'outfit_name': job.get('outfit_name'),
            'source_path': source_path,
            'current_job_id': job['id'],
            'manual': manual,
            'llm': copy.deepcopy(job.get('review_llm')),
            'regenerations': 0,
            'max_auto_regenerations': self.settings['max_auto_regenerations'],
            'baseline_revision': self.rt.reviews.acceptance_revision(tuple(combo)) or 0,
            'errors': 0,
            'attempts': [],
        }

    def register(self, jobs):
        with self.lock:
            changed = False
            for job in jobs:
                if job.get('review_requested') and not job.get('review_round_id'):
                    round_ = self._new_round(job)
                    job['review_round_id'] = round_['id']
                    self.rounds.append(round_)
                    changed = True
            if changed:
                self.persist()
                self.rt.queue.persist()

    def attach_retry(self, old, new):
        """A retried generation keeps its round."""
        with self.lock:
            round_ = next((r for r in self.rounds if r['current_job_id'] == old['id']), None)
            if round_ is None or round_['status'] == 'human_accepted':
                return
            new['review_round_id'] = round_['id']
            round_.update(current_job_id=new['id'], status='waiting_generation')
            round_.pop('error', None)
            self.persist()

    def _accepted(self, round_):
        revision = self.rt.reviews.acceptance_revision(tuple(round_['combo']))
        return bool(revision and revision > round_.get('baseline_revision', 0))

    def human_changed(self):
        """A person passed an image of a round's combination: the round is done and its pending work cancelled."""
        # The queue's lock first, as everywhere both are held.
        with self.rt.queue.lock, self.lock:
            accepted = []
            for round_ in self.rounds:
                if round_['status'] in SHOWN and self._accepted(round_):
                    round_['status'] = 'human_accepted'
                    accepted.append(round_['current_job_id'])
            if accepted:
                self.persist()
                self.rt.queue.cancel_waiting(accepted)

    def reconcile(self):
        with self.rt.queue.lock, self.lock:
            jobs = self.rt.queue.by_id()
            changed = False
            for round_ in self.rounds:
                if round_['status'] != 'waiting_generation':
                    continue
                job = jobs.get(round_['current_job_id'])
                if job and job['status'] == 'completed' and job.get('image_url'):
                    # The image path is kept so clearing the queue history does not orphan the round.
                    round_['image_path'] = unquote(job['image_url'].removeprefix('/api/image/files/'))
                    round_['status'] = 'pending_review'
                elif job is None or job['status'] in ('failed', 'cancelled', 'interrupted'):
                    round_['status'] = 'needs_attention'
                    round_['error'] = Msg(
                        'server.pipeline.generation_did_not_finish_check_it',
                        'Generation did not finish. Check it, then use Retry in the queue.',
                    )
                else:
                    continue
                changed = True
            if changed:
                self.persist()

    def public(self):
        with self.rt.queue.lock, self.lock:
            jobs = self.rt.queue.by_id()
            rounds = []
            for round_ in self.rounds:
                if round_['status'] == 'dismissed':
                    continue
                job = jobs.get(round_['current_job_id'])
                rounds.append({**copy.deepcopy(round_), 'job_status': job['status'] if job else None})
            return {'rounds': rounds[-500:], 'enabled': self.settings['enabled']}

    def dismiss(self):
        """Put away rounds with nothing left to do; they stay in the file."""
        with self.lock:
            count = 0
            for round_ in self.rounds:
                if round_['status'] not in OPEN and round_['status'] != 'dismissed':
                    round_.update(dismissed_from=round_['status'], status='dismissed')
                    count += 1
            if count:
                self.persist()
            return {'dismissed': count}

    def retry(self, round_ids):
        """Review existing images again (after an error or an uncertain answer), never regenerate."""
        with self.lock:
            count = 0
            for round_ in self.rounds:
                if (
                    round_['id'] in (round_ids or [])
                    and round_['status'] in ('needs_attention', 'limit_reached')
                    and round_.get('image_path')
                ):
                    round_.update(status='pending_review', errors=0)
                    round_.pop('error', None)
                    count += 1
            self.persist()
            return {'count': count}

    # --- regenerating -----------------------------------------------------------------------------------------------
    def source_job(self, relative):
        """A queue job rebuilt from an image's record, ready to run again with a new seed."""
        meta = self.rt.gallery.metadata(relative)
        if not isinstance(meta.get('settings'), dict) or not meta.get('positive'):
            raise ValueError(
                Msg('server.gallery.no_snapshot', 'This image has no generation settings to repeat.')
            )
        snapshot = {
            k: v
            for k, v in meta.items()
            if k
            not in ('workflow', 'created_at', 'job_id', 'prompt_id', 'image_size', 'postprocessing', 'seed')
        }
        job = {
            k: meta.get(k)
            for k in (
                'work_id',
                'character_id',
                'outfit_id',
                'outfit_name',
                'expression_id',
                'expression_name',
                'rating',
            )
        }
        job['snapshot'] = snapshot
        job['source_path'] = relative
        job['postprocessed'] = bool((meta.get('postprocessing') or {}).get('applied'))
        if meta.get('kind') == 'lab':
            job.update(kind='lab', lab_group=meta.get('lab_group') or uuid.uuid4().hex, lab_index=1)
        return job

    @staticmethod
    def fresh_job(source, regeneration=0, round_id=None):
        job = copy.deepcopy(source)
        old = (job['snapshot'].get('settings') or {}).get('seed')
        seed = secrets.randbits(32)
        if seed == old:
            seed = (seed + 1) % (2**32)
        job.update(
            id=uuid.uuid4().hex, status='queued', created_at=now(), seed=seed, regeneration=regeneration
        )
        job['snapshot']['settings'] = {**job['snapshot']['settings'], 'seed': seed}
        job['snapshot']['source_path'] = source.get('source_path')
        job.pop('postprocessed', None)
        if round_id:
            job['review_round_id'] = round_id
        return job

    def regenerate(self, items, review=None):
        """Queue each image again with a new seed; with review, each opens a round."""
        if not isinstance(items, list) or not 1 <= len(items) <= 200:
            raise ValueError(Msg('server.gallery.select_1_to_200', 'Select 1 to 200 images.'))
        reviewing = self.settings['enabled'] if review is None else bool(review)
        prepared, postprocessed = [], False
        for entry in items:
            relative = entry.get('path') if isinstance(entry, dict) else entry
            source = self.source_job(relative)
            postprocessed = postprocessed or source['postprocessed']
            job = self.fresh_job(source)
            round_ = None
            if reviewing and job.get('kind') != 'lab':
                round_ = self._new_round(job, relative, manual=True)
                job['review_round_id'] = round_['id']
            prepared.append((round_, job))
        with self.rt.queue.lock, self.lock:
            self.rt.queue.add([j for _, j in prepared])
            rounds = [r for r, _ in prepared if r]
            self.rounds.extend(rounds)
            if rounds:
                self.persist()
        return {
            'count': len(prepared),
            'reviewing': bool(rounds),
            'warning': Msg(
                'server.pipeline.post_processed_images_are_regenerated_from',
                'Post-processed images are regenerated from their original settings; later corrections are not reproduced.',
            )
            if postprocessed
            else None,
        }

    # --- reviewing (worker thread) ----------------------------------------------------------------------------------
    def _criteria(self, snapshot):
        parts = snapshot.get('parts') or {}
        lines = [
            f'{k}: {parts[k]}' for k in ('appearance', 'outfit', 'expression', 'composition') if parts.get(k)
        ]
        return '\n'.join(lines) or str(snapshot.get('positive') or '')

    def review_one(self, path, snapshot, work, override=None):
        with Image.open(path) as image:
            image.thumbnail((768, 768))
            buffer = io.BytesIO()
            image.convert('RGB').save(buffer, format='JPEG', quality=85)
        criteria = self._criteria(snapshot)
        if len(criteria) > 12000:
            return {'verdict': 'uncertain', 'evidence': 'The prompt is too long for automatic review.'}
        instruction = self.settings['instruction'] or DEFAULT_INSTRUCTION
        messages = [
            {'role': 'system', 'content': 'Review one image independently. Return only JSON.'},
            {
                'role': 'user',
                'content': [
                    {'type': 'text', 'text': instruction + '\n\n' + criteria},
                    {
                        'type': 'image_url',
                        'image_url': {
                            'url': 'data:image/jpeg;base64,' + base64.b64encode(buffer.getvalue()).decode()
                        },
                    },
                ],
            },
        ]
        self.rt.llm.require_consent(work, 'image_review', override)
        answer = asyncio.run(
            self.rt.llm.complete('image_review', messages, work.id, override=override, json_mode=True)
        )
        data = parse_json(answer['text']) or {}
        verdict, evidence = str(data.get('verdict') or '').lower(), str(data.get('evidence') or '').strip()
        if verdict not in ('pass', 'fail', 'uncertain') or not evidence:
            return {
                'verdict': 'error',
                'evidence': 'The model did not answer with a verdict.',
                'model': answer['model'],
            }
        # A pass that names a problem is held for a person.
        if verdict == 'pass' and any(word in evidence.lower() for word in CONTRADICTION):
            verdict, evidence = 'uncertain', 'Contradictory answer: ' + evidence[:300]
        return {'verdict': verdict, 'evidence': evidence[:1000], 'model': answer['model']}

    def process_ready(self):
        """Review every ready image once generation is idle. Returns True when something was reviewed."""
        self.reconcile()
        rt = self.rt
        with rt.queue.lock, self.lock:
            if (
                rt.queue.paused
                or not self.settings['enabled']
                or not rt.gpu.generation_allowed()
                or rt.queue.any_queued()
                or rt.queue.any_active()
            ):
                return False
            ready = [r for r in self.rounds if r['status'] == 'pending_review']
            if not ready or not rt.gpu.acquire('validation', 'waiting_comfy_idle'):
                return False
        reviewed = False
        try:
            try:
                queue = rt.comfy.request('/queue')
                if queue.get('queue_running') or queue.get('queue_pending'):
                    return False
                rt.gpu.update('validation', 'freeing_comfy')
                rt.comfy.request('/free', {'unload_models': True, 'free_memory': True})
            except RuntimeError:
                pass  # The image server is off; nothing to free.
            if rt.gpu.admit('vlm'):
                return False
            rt.gpu.update('validation', 'reviewing')
            reviewed = True
            for round_ in ready:
                self._review_round(round_)
            self._regenerate_failed(ready)
            return True
        finally:
            if reviewed:
                # Hand the GPU back to image generation only after the model is told to leave it.
                rt.gpu.update('validation', 'unloading_vlm')
                self._unload()
            rt.gpu.release('validation')

    def _review_round(self, round_):
        rt = self.rt
        with rt.queue.lock, self.lock:
            if round_['status'] != 'pending_review' or rt.queue.paused:
                return
            relative = round_.get('image_path')
            if not relative:
                round_.update(
                    status='needs_attention',
                    error=Msg('server.review.job_missing', 'The finished image of this round was not found.'),
                )
                self.persist()
                return
            round_['status'] = 'reviewing'
            self.persist()
        try:
            work = rt.works.get(round_['combo'][0])
            snapshot = rt.gallery.metadata(relative)
            result = self.review_one(rt.gallery.safe_path(relative), snapshot, work, round_.get('llm'))
        except AppError as error:
            result = {'verdict': 'error', 'evidence': error.msg, 'fatal': error.status == 428}
        except Exception as error:  # any failure becomes an 'error' verdict for a person
            log.exception('VLM review failed')
            result = {'verdict': 'error', 'evidence': message_of(error)}
        with rt.queue.lock, self.lock:
            round_['attempts'].append(
                {
                    'job_id': round_['current_job_id'],
                    'path': relative,
                    'verdict': result['verdict'],
                    'evidence': result['evidence'],
                    'model': result.get('model'),
                    'at': now(),
                    'regeneration': round_['regenerations'],
                }
            )
            try:
                reason = (
                    result['evidence']
                    if isinstance(result['evidence'], str)
                    else message_of(result['evidence'])
                )
                rt.reviews.record_auto(relative, result['verdict'], str(reason), {'round_id': round_['id']})
            except (OSError, ValueError):
                log.warning('Could not record the automatic verdict for %s', relative)
            if round_['status'] == 'human_accepted' or self._accepted(round_):
                round_['status'] = 'human_accepted'
            elif result['verdict'] == 'error':
                round_['errors'] += 1
                done = round_['errors'] >= 3 or result.get('fatal')
                round_['status'] = 'needs_attention' if done else 'pending_review'
                if done:
                    round_['error'] = result['evidence']
            elif result['verdict'] == 'pass':
                round_['status'] = 'awaiting_human'
            elif result['verdict'] == 'uncertain':
                round_['status'] = 'needs_attention'
            else:
                round_['status'] = 'failed_review'
            self.persist()

    def _regenerate_failed(self, ready):
        rt = self.rt
        with rt.queue.editing() as jobs, self.lock:
            for round_ in ready:
                if round_['status'] != 'failed_review':
                    continue
                if round_['regenerations'] >= round_['max_auto_regenerations']:
                    round_['status'] = 'limit_reached'
                    continue
                try:
                    source = self.source_job(round_['attempts'][-1]['path'])
                except ValueError as error:
                    round_.update(status='needs_attention', error=message_of(error))
                    continue
                fresh = self.fresh_job(source, round_['regenerations'] + 1, round_['id'])
                jobs.append(fresh)
                round_.update(current_job_id=fresh['id'], status='waiting_generation')
                round_['regenerations'] += 1
            self.persist()

    def _unload(self):
        command = self.settings.get('unload_command') or []
        if not command:
            return
        try:
            subprocess.run(
                command,
                capture_output=True,
                timeout=120,
                check=False,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
            )
        except (OSError, subprocess.SubprocessError):
            log.warning('The VLM unload command failed')
