"""Getting models (#161): Civitai addresses, queued downloads that resume and check their hash, and placing a file."""

import hashlib
import io
import json
import urllib.error
from collections import namedtuple

import pytest

from atelierx.image import model_download
from atelierx.image.model_download import ModelDownloads, kind_for, parse_address
from atelierx.image.model_info import ModelLibrary
from atelierx.image.models import ModelProfiles

BODY = b'0123456789' * 1000
DIGEST = hashlib.sha256(BODY).hexdigest()
URL = 'https://civitai.com/api/download/models/3055236?type=Model&format=SafeTensor'


def test_addresses_and_kinds():
    assert parse_address('2718862') == (2718862, None)
    assert parse_address('https://civitai.red/models/2718862/voqid?modelVersionId=3055236') == (
        2718862,
        3055236,
    )
    assert parse_address('https://civitai.com/api/download/models/3055236?fileId=1') == (None, 3055236)
    with pytest.raises(ValueError):
        parse_address('https://example.com/x')
    assert kind_for('LORA', 'Model', 'Anima') == 'loras'
    assert kind_for('Checkpoint', 'Model', 'Anima') == 'diffusion_models'
    assert kind_for('Checkpoint', 'Model', 'Illustrious') == 'checkpoints'
    assert kind_for('Checkpoint', 'Text Encoder', 'Anima') == 'text_encoders'


class _Response(io.BytesIO):
    def __init__(self, data, status=200, kind='application/octet-stream'):
        super().__init__(data)
        self.status = status
        self.headers = {'Content-Type': kind, 'Content-Length': str(len(data))}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _downloads(paths, tmp_path, monkeypatch, key='k'):
    loras = tmp_path / 'models' / 'loras'
    loras.mkdir(parents=True)
    folders = {'loras': [str(loras)], 'diffusion_models': [str(tmp_path / 'models' / 'unet')]}
    library = ModelLibrary(paths, ModelProfiles(paths), lambda: folders)
    downloads = ModelDownloads(paths, library, lambda: folders, lambda: key)
    monkeypatch.setattr(downloads, 'start', lambda: None)
    return downloads, loras


def _job(downloads, **file):
    model = {'id': 1, 'name': 'Ink', 'type': 'LORA', 'nsfw': False, 'creator': 'someone', 'license': {}}
    version = {'id': 2, 'name': 'v1', 'base_model': 'Anima', 'family': 'anima', 'trained_words': ['@ink']}
    chosen = {
        'name': 'ink.safetensors',
        'url': URL,
        'size': len(BODY),
        'sha256': DIGEST,
        'kind': 'loras',
        **file,
    }
    downloads.add({'model': model, 'version': version, 'file': chosen})
    return downloads.jobs[-1]


def test_a_download_resumes_checks_its_hash_and_remembers_civitai(paths, tmp_path, monkeypatch):
    downloads, loras = _downloads(paths, tmp_path, monkeypatch)
    job = _job(downloads)
    assert job['target'].endswith('loras\\anima\\ink.safetensors') or job['target'].endswith(
        'loras/anima/ink.safetensors'
    )
    # Half of it is already there from a broken run.
    part = loras / 'anima' / 'ink.safetensors.part'
    part.parent.mkdir(parents=True)
    part.write_bytes(BODY[:4000])
    seen = []

    def fake_open(request, timeout=0):
        seen.append(dict(request.header_items()))
        return _Response(BODY[4000:], status=206)

    monkeypatch.setattr(model_download.urllib.request, 'urlopen', fake_open)
    downloads._worker()
    assert job['status'] == 'done', job.get('error')
    assert seen[0]['Range'] == 'bytes=4000-' and seen[0]['Authorization'] == 'Bearer k'
    target = loras / 'anima' / 'ink.safetensors'
    assert target.read_bytes() == BODY and not part.exists()
    stored = json.loads((paths.data / 'image' / 'model-info.json').read_text(encoding='utf-8'))
    assert (
        stored['info'][DIGEST]['trained_words'] == ['@ink'] and stored['info'][DIGEST]['from'] == 'download'
    )
    # The same file cannot be queued again.
    with pytest.raises(ValueError):
        _job(downloads)


def test_a_wrong_file_fails_and_a_missing_key_is_named(paths, tmp_path, monkeypatch):
    downloads, loras = _downloads(paths, tmp_path, monkeypatch)
    job = _job(downloads, sha256='0' * 64)
    monkeypatch.setattr(model_download.urllib.request, 'urlopen', lambda request, timeout=0: _Response(BODY))
    downloads._worker()
    assert job['status'] == 'failed' and not (loras / 'anima' / 'ink.safetensors.part').exists()

    def refuse(request, timeout=0):
        raise urllib.error.HTTPError(URL, 401, 'Unauthorized', {}, None)

    monkeypatch.setattr(model_download.urllib.request, 'urlopen', refuse)
    downloads.act(job['id'], 'resume')
    downloads._worker()
    assert job['status'] == 'failed' and 'API' in job['error']['text']
    # A sign-in page instead of the file is the same.
    monkeypatch.setattr(
        model_download.urllib.request,
        'urlopen',
        lambda request, timeout=0: _Response(b'<html>', kind='text/html'),
    )
    downloads.act(job['id'], 'resume')
    downloads._worker()
    assert job['status'] == 'failed'


def test_not_enough_disk_space_stops_before_downloading(paths, tmp_path, monkeypatch):
    downloads, _ = _downloads(paths, tmp_path, monkeypatch)
    job = _job(downloads)
    usage = namedtuple('usage', 'total used free')
    monkeypatch.setattr(model_download.shutil, 'disk_usage', lambda path: usage(1, 1, 10))
    monkeypatch.setattr(model_download.urllib.request, 'urlopen', lambda *a, **k: pytest.fail('downloaded'))
    downloads._worker()
    assert job['status'] == 'failed' and job['error']['key'] == 'server.models.no_space'


def test_a_file_the_person_downloaded_is_looked_up_and_placed(paths, tmp_path, monkeypatch):
    downloads, loras = _downloads(paths, tmp_path, monkeypatch)
    inbox = tmp_path / 'Downloads'
    inbox.mkdir()
    (inbox / 'ink.safetensors').write_bytes(BODY)
    (inbox / 'notes.txt').write_text('x')
    listed = downloads.candidates(str(inbox))
    assert [f['name'] for f in listed['files']] == ['ink.safetensors']

    def fake_json(url):
        if url.endswith(f'/by-hash/{DIGEST}'):
            return {
                'id': 2,
                'modelId': 1,
                'name': 'v1',
                'baseModel': 'Anima',
                'trainedWords': ['@ink'],
                'model': {'name': 'Ink'},
                'files': [{'type': 'Model', 'hashes': {'SHA256': DIGEST.upper()}}],
            }
        return {'name': 'Ink', 'type': 'LORA'}

    monkeypatch.setattr(downloads, '_json', fake_json)
    found = downloads.inspect(str(inbox / 'ink.safetensors'))
    assert (found['kind'], found['family'], found['sha256']) == ('loras', 'anima', DIGEST)
    placed = downloads.place(
        {
            'path': found['path'],
            'kind': 'loras',
            'subfolder': 'anima',
            'sha256': DIGEST,
            'info': found['info'],
        }
    )
    assert (loras / 'anima' / 'ink.safetensors').read_bytes() == BODY and not (
        inbox / 'ink.safetensors'
    ).exists()
    assert placed['target'].endswith('ink.safetensors')
    with pytest.raises(ValueError):
        downloads.place({'path': str(inbox / 'notes.txt'), 'kind': 'loras'})


def test_the_civitai_key_is_kept_as_a_vault_reference(unlocked):
    c = unlocked
    refused = c.put('/api/image/settings/downloads', json={'civitai_key': 'plain-key'})
    assert refused.status_code == 400
    saved = c.put('/api/image/settings/downloads', json={'civitai_key': 'secret:civitai', 'nsfw': True})
    assert saved.status_code == 200
    assert c.get('/api/image/settings/downloads').json() == {'civitai_key': 'secret:civitai', 'nsfw': True}


def test_search_leaves_out_adult_models_and_images_unless_asked(paths, tmp_path, monkeypatch):
    downloads, _ = _downloads(paths, tmp_path, monkeypatch)
    asked = []
    page = {
        'items': [
            {
                'id': 1,
                'name': 'Ink',
                'type': 'LORA',
                'nsfw': False,
                'creator': {'username': 'a'},
                'stats': {'downloadCount': 5},
                'modelVersions': [
                    {
                        'id': 11,
                        'name': 'v1',
                        'baseModel': 'Anima',
                        'images': [
                            {'url': 'https://img/adult.jpg', 'nsfwLevel': 8},
                            {'url': 'https://img/safe.jpg', 'nsfwLevel': 1},
                        ],
                    }
                ],
            },
            {
                'id': 2,
                'name': 'Adult',
                'type': 'LORA',
                'nsfw': True,
                'modelVersions': [{'id': 21, 'images': []}],
            },
        ],
        'metadata': {'nextCursor': 'abc|1'},
    }

    def fake_json(url):
        asked.append(url)
        return page

    monkeypatch.setattr(downloads, '_json', fake_json)
    found = downloads.search('ink', 'LORA', 'Anima', 'Newest', False, '')
    assert [i['name'] for i in found['items']] == ['Ink'] and found['next'] == 'abc|1'
    assert found['items'][0]['image'] == 'https://img/safe.jpg'
    assert found['items'][0]['url'].endswith('/models/1?modelVersionId=11')
    assert 'nsfw=false' in asked[0] and 'types=LORA' in asked[0] and 'baseModels=Anima' in asked[0]
    every = downloads.search('', 'bogus', 'bogus', 'bogus', True, 'bad cursor!')
    assert [i['name'] for i in every['items']] == ['Ink', 'Adult'] and every['items'][0][
        'image'
    ] == 'https://img/adult.jpg'
    assert 'types=' not in asked[1] and 'cursor=' not in asked[1] and 'nsfw=true' in asked[1]
