import sys
import time

from test_image import FakeComfy

FAKE_TASKS = 'import sys\nprint("preprocess", sys.argv[1:])\n'
# Writes one epoch checkpoint, the final file and a progress line, like anima_lora's train.py.
FAKE_TRAIN = """import json, sys
from pathlib import Path
args = dict(zip(sys.argv[1::2], sys.argv[2::2]))
name = args['--output_name']
ckpt = Path('output/ckpt')
(ckpt / name).mkdir(parents=True, exist_ok=True)
(ckpt / name / f'{name}-000002.safetensors').write_bytes(b'epoch2')
(ckpt / f'{name}.safetensors').write_bytes(b'final')
Path(args['--progress_jsonl']).write_text(json.dumps({'ev': 'step', 'global_step': 8, 'epoch': 4, 'loss/average': 0.1}) + '\\n')
"""


class LoraComfy(FakeComfy):
    def catalog(self):
        return {**super().catalog(), 'loras': ['anima\\W001_C001_R001-e04.safetensors']}


def make_trainer(tmp_path):
    trainer = tmp_path / 'anima_lora'
    (trainer / 'scripts' / 'tasks').mkdir(parents=True)
    (trainer / 'train.py').write_text(FAKE_TRAIN, encoding='utf-8')
    (trainer / 'tasks.py').write_text(FAKE_TASKS, encoding='utf-8')
    (trainer / 'scripts' / 'tasks' / 'preprocess.py').write_text('# atelierx patch\n', encoding='utf-8')
    models = tmp_path / 'models'
    models.mkdir()
    files = {}
    for key in ('dit', 'text_encoder', 'vae'):
        (models / f'{key}.safetensors').write_bytes(b'x')
        files[key] = str(models / f'{key}.safetensors')
    lora_dir = tmp_path / 'loras'
    lora_dir.mkdir()
    return {
        'trainer_dir': str(trainer),
        'trainer_python': sys.executable,
        'lora_dir': str(lora_dir),
        'bases': {'official': files},
    }


def test_dataset_training_register_and_auto_apply(unlocked, tmp_path):
    c = unlocked
    wid = c.post('/api/samples/single/install').json()['id']
    runtime = c.app.state.app.image
    runtime.comfy = LoraComfy()
    runtime.set_paused(True)
    runtime.gpu.admit = lambda kind: None
    base = f'/api/works/{wid}/image/lora/C001'

    target = {'character_id': 'C001', 'outfit_id': 'o01', 'expression_id': 'smile'}
    c.post(f'/api/works/{wid}/image/jobs', json={'targets': [target], 'count': 2})
    for job in list(runtime.jobs):
        job['status'] = 'running'
        runtime.run_job(job)
    candidates = c.get(f'{base}/candidates', params={'outfits': 'o01'}).json()
    assert len(candidates) == 2 and not any(x['adopted'] for x in candidates)
    assert c.post(f'{base}/datasets', json={'outfits': ['o01']}).status_code == 400  # nothing adopted yet
    c.post('/api/image/gallery/review', json={'verdict': 'pass', 'items': [candidates[0]['path']]})

    dataset = c.post(f'{base}/datasets', json={'outfits': ['o01']}).json()
    assert dataset['id'] == 'D001' and len(dataset['items']) == 1
    (item,) = dataset['items']
    assert item['caption'].startswith('safe, 1girl, w001_c001, w001_c001_o01') and 'smile' in item['caption']
    path = item['image']['path']
    edited = c.post(f'{base}/datasets/D001/captions', json={'items': {path: 'safe, 1girl, my edit'}}).json()
    assert edited['items'][0]['edited']
    rebuilt = c.post(f'{base}/datasets', json={'id': 'D001', 'paths': [x['path'] for x in candidates]}).json()
    assert len(rebuilt['items']) == 2 and rebuilt['items'][0]['caption'] == 'safe, 1girl, my edit'

    status = c.get('/api/image/training/status').json()
    assert not status['trainer_found'] and status['bases'] == []
    assert c.post(f'{base}/runs', json={'dataset_id': 'D001'}).status_code == 400
    c.put('/api/image/settings/training', json=make_trainer(tmp_path))
    status = c.get('/api/image/training/status').json()
    assert status['trainer_found'] and status['patched'] and status['bases'][0]['id'] == 'official'

    run = c.post(f'{base}/runs', json={'dataset_id': 'D001', 'params': {'epochs': 4, 'save_every': 2}}).json()
    assert run['id'] == 'R001' and run['output_name'] == f'{wid}_C001_R001'
    assert c.post(f'{base}/runs', json={'dataset_id': 'D001'}).status_code == 400  # one at a time
    for _ in range(200):
        runs = c.get(base).json()['runs']
        if runs[0]['status'] not in ('waiting_gpu', 'preprocessing', 'training'):
            break
        time.sleep(0.05)
    (done,) = runs
    assert done['status'] == 'done', done.get('error')
    assert [o['epoch'] for o in done['outputs']] == [2, 4] and done['progress']['step'] == 8
    assert (tmp_path / 'loras' / f'{wid}_C001_R001-e04.safetensors').read_bytes() == b'final'
    assert not runtime.gpu.holder
    assert '$ ' in c.get(f'{base}/runs/R001/log').json()['text']
    exported = tmp_path / 'anima_lora' / 'image_dataset' / f'{wid}_C001_R001'
    assert len(list(exported.glob('*.txt'))) == 2

    registered = c.post(f'{base}/models', json={'run_id': 'R001', 'epoch': 4, 'auto_apply': True}).json()[
        'models'
    ]
    (entry,) = registered
    assert entry['file'] == 'anima\\W001_C001_R001-e04.safetensors' and entry['outfit_id'] == 'o01'
    c.post(f'{base}/models', json={'file': 'anima\\other.safetensors', 'name': 'other'})
    turned = c.put(
        f'{base}/models/other', json={'auto_apply': True, 'apply_to': 'outfit', 'outfit_id': 'o01'}
    ).json()
    # Only one automatic LoRA per target: the newer one turns the other off.
    assert [m['auto_apply'] for m in turned['models']] == [True, True]
    c.put(f'{base}/models/other', json={'auto_apply': False})

    c.post(f'/api/works/{wid}/image/jobs', json={'targets': [target]})
    job = runtime.jobs[-1]
    assert job['snapshot']['settings']['loras'][0]['name'] == entry['file']
    assert 'w001_c001' in job['snapshot']['positive']  # the trigger joins once the character has a LoRA
    assert c.delete(f'{base}/models/{entry["id"]}').json()['models'][0]['id'] == 'other'
