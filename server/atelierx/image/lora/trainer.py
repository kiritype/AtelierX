"""LoRA training runs (23-lora-training: 학습 실행). One run at a time, with the external trainer (anima_lora).

A run waits for the GPU (generation finishes the image it is making; queued images wait), frees the image server's
memory, exports the dataset to the trainer, preprocesses, trains, then copies every saved epoch into the LoRA
folder. The log and progress file are kept in the output root next to the character's images.
"""

import hashlib
import json
import logging
import os
import shutil
import subprocess
import threading
import time
from pathlib import Path, PurePosixPath, PureWindowsPath

from PIL import Image

from ...core.i18n import Msg, message_of
from ...core.lifecycle import UNFINISHED
from ...core.proc import NO_WINDOW, stop_tree
from ..util import code, now
from . import models, setup, store

log = logging.getLogger(__name__)

DEFAULT_PARAMS = {
    'epochs': 40,
    'save_every': 10,
    'learning_rate': '1e-4',
    'method': 'atelierx_tlora',
    'base': 'official',
}
WAIT_POLL_SECONDS = 2
INTERRUPTED = Msg(
    'server.trainer.the_server_stopped_and_lost_track',
    "The server stopped and lost track of this training. Check the trainer's log and output files.",
)


def last_progress(path):
    """Latest step / end event of the trainer's progress.jsonl."""
    path = Path(path)
    if not path.is_file():
        return {}
    with path.open('rb') as stream:
        stream.seek(max(0, path.stat().st_size - 65536))
        lines = stream.read().decode('utf-8', 'replace').splitlines()
    result = {}
    for line in lines:
        try:
            event = json.loads(line)
        except ValueError:
            continue
        kind = event.get('ev')
        if kind == 'run_start':
            result.update(total_steps=event.get('total_steps'), total_epochs=event.get('total_epochs'))
        elif kind == 'step':
            # The loss key differs between trainer versions.
            loss = event.get('loss/average', event.get('loss/epoch_average'))
            result.update(step=event.get('global_step'), epoch=event.get('epoch'), loss=loss)
        elif kind == 'run_end':
            result.update(finished=event.get('status'), error=event.get('error'))
    return result


def _sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as source:
        for chunk in iter(lambda: source.read(4 * 1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _child_env(extra):
    # The app's own virtual environment must not leak into the trainer's Python.
    env = {**os.environ, 'PYTHONIOENCODING': 'utf-8', **(extra or {})}
    env.pop('VIRTUAL_ENV', None)
    return env


class Cancelled(Exception):
    pass


class LoraTrainer:
    def __init__(self, runtime):
        self.rt = runtime
        self.lock = threading.RLock()
        self.process = None
        self.active = None  # (work_id, character_id, run_id)
        self.cancel_requested = False
        self._recover()

    # --- records ------------------------------------------------------------------------------------------------
    def _logs(self, run):
        return Path(self.rt.paths.output) / run['work_id'] / run['character_id'] / 'lora' / run['id'] / 'logs'

    def _write(self, work, run):
        with self.lock:
            run['updated_at'] = now()
            store.write(store.run_file(work, run['character_id'], run['id']), run)

    def _recover(self):
        """A run that was active when the server stopped cannot be followed any more."""
        try:
            works = self.rt.works.all()
        except Exception:  # the works list is not readable yet (locked vault); nothing to recover
            return
        for work in works:
            folder = work.app / 'image' / 'characters'
            for path in sorted(folder.glob('*/lora/runs/*.json')) if folder.is_dir() else []:
                run = store.read(path)
                if run.get('status') in UNFINISHED:
                    run.update(status='interrupted', error=INTERRUPTED, updated_at=now())
                    store.write(path, run)

    def _public(self, run):
        logs = self._logs(run)
        return {
            **run,
            'progress': last_progress(logs / 'progress.jsonl'),
            'active': self.active == (run['work_id'], run['character_id'], run['id']),
        }

    def list(self, work, character_id):
        return {
            'runs': [self._public(r) for r in reversed(store.runs(work, code(character_id)))],
            'busy': self.active is not None,
        }

    def log_tail(self, work, character_id, run_id, lines=200):
        run = store.read(store.run_file(work, code(character_id), run_id))
        path = self._logs(run) / 'train.log'
        if not path.is_file():
            return {'text': ''}
        with path.open('rb') as stream:
            stream.seek(max(0, path.stat().st_size - 65536))
            text = stream.read().decode('utf-8', 'replace')
        return {'text': '\n'.join(text.splitlines()[-lines:])}

    # --- start / cancel -----------------------------------------------------------------------------------------
    def _params(self, given):
        params = {**DEFAULT_PARAMS, **{k: v for k, v in (given or {}).items() if v not in (None, '')}}
        for key in ('epochs', 'save_every'):
            if isinstance(params[key], bool) or not str(params[key]).isdigit() or int(params[key]) < 1:
                raise ValueError(
                    Msg(
                        'server.trainer.must_be_a_whole_number_of',
                        '{key} must be a whole number of 1 or more.',
                        key=key,
                    )
                )
            params[key] = int(params[key])
        try:
            if float(params['learning_rate']) <= 0:
                raise ValueError
        except ValueError as error:
            raise ValueError(
                Msg('server.trainer.learning_rate', 'The learning rate must be a positive number.')
            ) from error
        params['learning_rate'] = str(params['learning_rate'])
        if params['method'] not in setup.METHODS:
            raise ValueError(
                Msg(
                    'server.trainer.choose_a_training_method_from_the',
                    'Choose a training method from the list.',
                )
            )
        return params

    def start(self, work, character_id, body):
        character_id = code(character_id)
        dataset = store.read(store.dataset_file(work, character_id, body.get('dataset_id')))
        if not dataset.get('items'):
            raise ValueError(Msg('server.trainer.the_dataset_has_no_images', 'The dataset has no images.'))
        params = self._params(body.get('params'))
        values, bases = setup.prepare(self.rt.paths)
        if not values.get('lora_dir') or not Path(values['lora_dir']).is_dir():
            raise ValueError(
                Msg(
                    'server.trainer.set_the_lora_output_folder_in',
                    'Set the LoRA output folder in Settings → Image → LoRA training.',
                )
            )
        if params['base'] not in bases:
            raise ValueError(
                Msg('server.trainer.choose_a_base_model_from_the', 'Choose a base model from the list.')
            )
        base = bases[params['base']]
        with self.lock:
            if self.active:
                raise ValueError(
                    Msg(
                        'server.trainer.another_lora_is_training_start_after',
                        'Another LoRA is training. Start after it finishes.',
                    )
                )
            run_id = store.next_id(store.runs(work, character_id), 'R')
            run = {
                'id': run_id,
                'schema_version': 1,
                'work_id': work.id,
                'character_id': character_id,
                'dataset': dataset['id'],
                'dataset_name': dataset.get('name'),
                'dataset_hash': hashlib.sha256(
                    '\n'.join(i['image']['sha256'] + i['caption'] for i in dataset['items']).encode()
                ).hexdigest(),
                'outfits': dataset.get('outfits', []),
                'triggers': dataset.get('triggers', {}),
                'output_name': f'{work.id}_{character_id}_{run_id}',
                'base_model': base['base_model'],
                'settings': {**params, 'preset': base['preset']},
                'status': 'queued',
                'phase': 'waiting_gpu',
                'created_at': now(),
                'outputs': [],
                'log': {'root': 'output', 'path': f'{work.id}/{character_id}/lora/{run_id}/logs/train.log'},
            }
            self._write(work, run)
            self.active = (work.id, character_id, run_id)
            self.cancel_requested = False
        threading.Thread(
            target=self._execute, args=(work, run, dataset, values, base), daemon=True, name='lora-training'
        ).start()
        return self._public(run)

    def cancel(self, work, character_id, run_id):
        with self.lock:
            if self.active != (work.id, code(character_id), run_id):
                raise ValueError(
                    Msg('server.trainer.this_training_is_not_running', 'This training is not running.')
                )
            self.cancel_requested = True
            work_run = store.run_file(work, code(character_id), run_id)
            current = store.read(work_run)
            if current.get('status') in UNFINISHED:
                store.write(work_run, {**current, 'status': 'cancelling', 'updated_at': now()})
            # The trainer starts worker processes of its own; stop the whole tree.
            stop_tree(self.process)
        return {'ok': True}

    def shutdown(self, timeout=10):
        """The app is closing: a training run stops with it and is recorded as interrupted (it can be run again)."""
        with self.lock:
            if self.active is None:
                return
            self.closing = True
            self.cancel_requested = True
            process = self.process
        stop_tree(process)
        deadline = time.monotonic() + timeout
        while self.active is not None and time.monotonic() < deadline:
            time.sleep(0.1)

    # --- the run itself -----------------------------------------------------------------------------------------
    def _check_cancel(self):
        if self.cancel_requested:
            raise Cancelled

    def _wait_for_gpu(self, run):
        """Take the GPU once no image is being generated. Queued jobs then wait for the training."""
        gpu = self.rt.gpu
        while True:
            self._check_cancel()
            if gpu.generation_allowed() and gpu.admit('training'):
                time.sleep(WAIT_POLL_SECONDS)
                continue
            # Checked and taken under the queue's lock, so no job starts in between.
            with self.rt.queue.lock:
                if not self.rt.queue.any_active(self.rt.on_gpu) and gpu.acquire(
                    'training', 'preparing', run['output_name']
                ):
                    return
            time.sleep(WAIT_POLL_SECONDS)

    def _export(self, run, dataset, values, base):
        trainer = Path(values['trainer_dir'])
        name = run['output_name']
        # Captions and images of an earlier run with the same name would survive in the trainer's caches.
        for stale in (
            trainer / 'image_dataset' / name,
            trainer / 'post_image_dataset' / 'resized' / name,
            trainer / base['cache_dir'] / name,
        ):
            if stale.exists():
                shutil.rmtree(stale)
        target = trainer / 'image_dataset' / name
        target.mkdir(parents=True)
        for item in dataset['items']:
            relative = item['image']['path']
            if self.rt.reviews.sha256(relative, fresh=True) != item['image']['sha256']:
                raise ValueError(
                    Msg(
                        'server.trainer.image_changed_after_the_dataset_was',
                        'Image changed after the dataset was made: {path}',
                        path=relative,
                    )
                )
            parts = PurePosixPath(relative).parts
            stem = '_'.join([*parts[-3:-1], PurePosixPath(relative).stem])
            with Image.open(self.rt.gallery.safe_path(relative)) as image:
                image.convert('RGB').save(target / f'{stem}.png')
            (target / f'{stem}.txt').write_text(item['caption'], encoding='utf-8')

    def _call(self, values, arguments, log_path, env=None):
        python = Path(values['trainer_dir']) / values['trainer_python']
        with open(log_path, 'a', encoding='utf-8') as stream:
            stream.write(f'\n$ {" ".join(map(str, arguments))}\n')
            stream.flush()
            with self.lock:
                self._check_cancel()
                self.process = subprocess.Popen(
                    [str(python), *map(str, arguments)],
                    cwd=values['trainer_dir'],
                    stdout=stream,
                    stderr=subprocess.STDOUT,
                    env=_child_env(env),
                    creationflags=NO_WINDOW,
                )
            exit_code = self.process.wait()
        self._check_cancel()
        if exit_code:
            raise RuntimeError(
                Msg(
                    'server.trainer.the_trainer_failed_exit_code_check',
                    'The trainer failed (exit code {exit_code}). Check {log_path}.',
                    exit_code=exit_code,
                    log_path=str(log_path),
                )
            )

    def _execute(self, work, run, dataset, values, base):
        gpu = self.rt.gpu
        try:
            self._wait_for_gpu(run)
            logs = self._logs(run)
            logs.mkdir(parents=True, exist_ok=True)
            try:
                self.rt.comfy.request('/free', {'unload_models': True, 'free_memory': True})
            except Exception:  # the image server may be off; training does not need it
                log.info('The image server did not answer /free before training; continuing.')
            self._export(run, dataset, values, base)
            name, params = run['output_name'], run['settings']
            gpu.update('training', 'preprocessing')
            run.update(status='running', phase='preprocessing', started_at=now())
            self._write(work, run)
            env = {
                'METHOD': params['method'],
                'PRESET': params['preset'],
                'PREPROCESS_PATH_PATTERN': f'{name}/*',
            }
            self._call(values, ['tasks.py', 'preprocess'], logs / 'train.log', env)
            gpu.update('training', 'training')
            run['phase'] = 'training'
            self._write(work, run)
            self._call(
                values,
                [
                    'train.py',
                    '--method', params['method'],
                    '--preset', params['preset'],
                    '--output_name', name,
                    '--path_pattern', f'{name}/*',
                    '--learning_rate', params['learning_rate'],
                    '--max_train_epochs', params['epochs'],
                    '--save_every_n_epochs', params['save_every'],
                    '--checkpointing_epochs', params['save_every'],
                    '--progress_jsonl', logs / 'progress.jsonl',
                ],
                logs / 'train.log',
            )  # fmt: skip
            outputs = self._collect_outputs(run, values)
            # Give the GPU back before reporting "done", so a finished run never blocks generation.
            gpu.release('training')
            run.update(status='done', phase=None, finished_at=now(), outputs=outputs)
            self._write(work, run)
        except Cancelled:
            closing = getattr(self, 'closing', False)
            run.update(
                status='interrupted' if closing else 'cancelled',
                phase=None,
                finished_at=now(),
                **({'error': INTERRUPTED} if closing else {}),
            )
            self._write(work, run)
        except Exception as error:  # every failure is reported on the run
            log.exception('LoRA training failed: %s', run['output_name'])
            run.update(status='failed', phase=None, finished_at=now(), error=message_of(error))
            self._write(work, run)
        finally:
            with self.lock:
                self.process = None
                self.active = None
            gpu.release('training')

    def _collect_outputs(self, run, values):
        name = run['output_name']
        checkpoints = Path(values['trainer_dir']) / 'output' / 'ckpt'
        found = [
            (int(path.stem.rsplit('-', 1)[1]), path)
            for path in sorted((checkpoints / name).glob(f'{name}-*.safetensors'))
            if path.stem.rsplit('-', 1)[1].isdigit()
        ]
        final = checkpoints / f'{name}.safetensors'
        if not final.is_file():
            raise RuntimeError(
                Msg(
                    'server.trainer.training_finished_but_is_missing',
                    'Training finished but {final} is missing.',
                    final=str(final),
                )
            )
        found.append((int(run['settings']['epochs']), final))
        outputs = []
        for epoch, source in sorted(set(found)):
            destination = Path(values['lora_dir']) / f'{name}-e{epoch:02d}.safetensors'
            shutil.copy2(source, destination)
            outputs.append(
                {
                    'epoch': epoch,
                    'file': {
                        'root': 'lora',
                        'path': destination.name,
                        'sha256': _sha256(destination),
                        'size': destination.stat().st_size,
                    },
                }
            )
        return outputs

    # --- registering an epoch -----------------------------------------------------------------------------------
    def register(self, work, character_id, body):
        """Add one epoch of a finished run to the character's LoRAs."""
        character_id = code(character_id)
        run = store.read(store.run_file(work, character_id, body.get('run_id')))
        output = next((o for o in run.get('outputs', []) if o['epoch'] == body.get('epoch')), None)
        if run.get('status') != 'done' or output is None:
            raise ValueError(
                Msg('server.trainer.choose_an_epoch_of_a_finished', 'Choose an epoch of a finished training.')
            )
        filename = output['file']['path']
        # The image server names files in sub-folders with the folder (``anima\\name.safetensors``).
        catalog = self.rt.comfy.catalog().get('loras', [])
        comfy_name = next((n for n in catalog if PureWindowsPath(n).name == filename), filename)
        outfits = run.get('outfits') or []
        entry = {
            'id': PurePosixPath(filename).stem,
            'name': body.get('name') or f'{run.get("dataset_name") or run["dataset"]} · e{output["epoch"]}',
            'file': comfy_name,
            'strength': body.get('strength', 1.0),
            'auto_apply': bool(body.get('auto_apply', False)),
            'apply_to': body.get('apply_to', 'character'),
            'outfit_id': body.get('outfit_id') or (outfits[0] if len(outfits) == 1 else None),
            'model_family': 'anima',
            'source': {'run': run['id'], 'epoch': output['epoch'], 'dataset': run['dataset']},
            'triggers': run.get('triggers', {}),
            'base_model': run.get('base_model'),
            'sha256': output['file']['sha256'],
        }
        return models.add(work, character_id, entry)
