"""MOSS contracts, frozen queue inputs and native graphs, without model execution."""

import copy
import json

import pytest

from atelierx.image import library, moss_layout
from atelierx.image.models import family_from_header
from atelierx.image.workflow import build_ui_workflow, build_workflow, validate_settings
from test_image import FakeComfy


class MossComfy(FakeComfy):
    def catalog(self):
        return {
            **super().catalog(),
            'models': ['moss/moss_image_sft_bf16.safetensors'],
            'text_encoders': ['qwen3.5_9b_bf16.safetensors'],
            'vaes': ['flux2-vae.safetensors'],
            'samplers': ['euler'],
            'clip_types': ['moss_image'],
            'nodes': {'moss': True, 'moss_slg': True},
            'loras': ['moss/anime.safetensors'],
        }


def layout(binding=False):
    return {
        'schema_version': 1,
        'mode': 'layout',
        'width': 1024,
        'height': 1024,
        'scene': 'A cafe #1\nsoft light',
        'items': [
            {
                'id': 'person',
                'label': 'character',
                'name': 'Person',
                'caption': 'sitting',
                'binding': 'target' if binding else 'manual',
                'rect': [0.1, 0.2, 0.3, 0.5],
            },
            {
                'id': 'sign',
                'label': 'text',
                'name': 'Sign',
                'caption': 'white lettering',
                'text': '# 오늘 "영업"\nOPEN',
                'binding': 'manual',
                'rect': [0, 0, 1, 0.1],
            },
        ],
    }


def test_compile_encloses_fractional_edges_and_preserves_text_and_metadata_boundary():
    doc, prompt = moss_layout.prepare(layout(), {'width': 1536, 'height': 1024})
    parsed = json.loads(prompt)
    assert parsed['items'][0]['bbox'] == [-308, -615, 205, -153]
    assert parsed['items'][1]['text'] == '# 오늘 "영업"\nOPEN'
    assert parsed['summary']['caption'] == 'A cafe #1\nsoft light'
    assert parsed['bbox_format'] == 'yxyx' and parsed['bbox_coord_space'] == 'abs_centralized'
    assert not {'id', 'name', 'binding', 'rect', 'resolved'} & parsed['items'][0].keys()
    assert 'width' not in parsed and doc['width'] == 1536
    assert layout()['width'] == 1024


@pytest.mark.parametrize(
    'rect',
    [[-0.1, 0, 0.2, 0.2], [0, 0, 0, 0.5], [0, 0, 2, 0.5], [0, 0, True, 0.5], [0, float('nan'), 0.2, 0.2]],
)
def test_invalid_rectangles_are_rejected(rect):
    doc = layout()
    doc['items'][0]['rect'] = rect
    with pytest.raises(ValueError):
        moss_layout.compile_layout(doc)


def test_unresolved_target_and_blank_text_are_rejected_only_at_generation():
    doc = layout(True)
    assert moss_layout.clean(doc)['items'][0]['binding'] == 'target'
    with pytest.raises(ValueError):
        moss_layout.compile_layout(doc)
    doc = layout()
    doc['items'][1]['text'] = ''
    with pytest.raises(ValueError):
        moss_layout.compile_layout(doc)
    doc = layout()
    doc['items'][1]['id'] = 'person'
    with pytest.raises(ValueError):
        moss_layout.clean(doc)


def test_native_graph_and_editor_export_use_moss_latent_encoder_shift_and_slg():
    settings = validate_settings({'family': 'moss'}, MossComfy().catalog())
    graph = build_workflow(settings, 'cafe', '', 42)
    nodes = {n['class_type']: n['inputs'] for n in graph.values()}
    assert nodes['CLIPLoader']['type'] == 'moss_image'
    assert nodes['EmptyFlux2LatentImage'] == {'width': 1024, 'height': 1024, 'batch_size': 1}
    assert 'EmptyLatentImage' not in nodes and 'ModelSamplingSD3' not in nodes
    assert nodes['SkipLayerGuidanceDiTSimple']['single_layers'] == '22'
    assert nodes['ModelSamplingAuraFlow']['shift'] == 5
    assert nodes['KSampler']['cfg'] == 3 and nodes['KSampler']['steps'] == 50
    exported = build_ui_workflow(settings, 'cafe', '', 42)
    assert any(n['type'] == 'EmptyFlux2LatentImage' for n in exported['nodes'])
    fast = validate_settings(
        {'family': 'moss', 'steps': 4, 'cfg': 1, 'moss_slg': False}, MossComfy().catalog()
    )
    assert all(
        n['class_type'] != 'SkipLayerGuidanceDiTSimple' for n in build_workflow(fast, 'cafe', '', 42).values()
    )
    assert (
        family_from_header({'shared_block_modulation.weight': {}, 'layers.0.proj.ffn_up_gate.weight': {}})
        == 'moss'
    )


@pytest.mark.parametrize(
    'patch',
    [
        {'clip_type': 'stable_diffusion'},
        {'clip_skip': 2},
        {'upscale': {'scale': 2}},
        {'detailer': {'stages': {'face': 0.3}}},
        {'moss_slg': 'yes'},
        {'unsupported_option': True},
        {'loras': [{'name': 'moss/anime.safetensors', 'strength_clip': 1}]},
    ],
)
def test_unsupported_moss_settings_fail_explicitly(patch):
    with pytest.raises(ValueError):
        validate_settings({'family': 'moss', **patch}, MossComfy().catalog())


def test_missing_native_nodes_and_components_fail_before_queueing():
    for patch in ({'nodes': {}}, {'nodes': {'moss': True}}, {'text_encoders': []}, {'vaes': []}):
        with pytest.raises(ValueError):
            validate_settings({'family': 'moss'}, {**MossComfy().catalog(), **patch})


def setup(client, sample=False):
    wid = client.post('/api/samples/single/install').json()['id'] if sample else None
    runtime = client.app.state.app.image
    runtime.set_paused(True)
    runtime.comfy = MossComfy()
    runtime.gpu.admit = lambda kind: None
    return wid, runtime


def test_single_draft_result_restore_cancel_retry_and_queue_reload(unlocked):
    client = unlocked
    _, runtime = setup(client)
    draft = {
        'schema_version': 4,
        'positive': 'General input stays',
        'negative': '',
        'service': 'comfyui',
        'preset': '',
        'sources': [],
        'settings': {'comfyui': {'family': 'moss'}, 'novelai': {}, 'pixai': {}},
        'moss_layout': layout(),
    }
    revision = client.get('/api/image/single/draft').json()['revision']
    response = client.put('/api/image/single/draft', json={'draft': draft, 'revision': revision})
    assert response.status_code == 200, response.text
    assert client.get('/api/image/single/draft').json()['draft'] == draft
    response = client.post(
        '/api/image/single',
        json={
            'positive': '',
            'negative': '# no blur',
            'prompt_sources': [{'kind': 'direct', 'id': '', 'name': '', 'positive': '', 'negative': ''}],
            'settings': {'family': 'moss', 'seed': 42},
            'moss_layout': layout(),
        },
    )
    assert response.status_code == 200, response.text
    job = runtime.queue.get(response.json()['job_id'])
    assert job['snapshot']['negative'] == '# no blur'
    original = copy.deepcopy(job['snapshot'])
    runtime.cancel(job['id'])
    retry_id = runtime.retry(job['id'])['job_id']
    assert runtime.queue.get(retry_id)['snapshot'] == original
    runtime.load_queue()
    retry = runtime.queue.get(retry_id)
    assert retry['snapshot'] == original
    retry['status'] = 'running'
    runtime.run_job(retry)
    assert retry['status'] == 'done', retry.get('error')
    runs = client.get('/api/image/single/runs').json()['runs']
    saved = next(r for r in runs if r['id'] == retry_id)
    assert saved['actual']['moss_layout'] == layout()
    assert saved['actual']['positive'] == original['positive']
    metadata = runtime.gallery.metadata(saved['path'])
    assert metadata['schema_version'] == 5
    runtime.remove_finished(retry_id)
    assert (
        next(r for r in client.get('/api/image/single/runs').json()['runs'] if r['id'] == retry_id)['actual'][
            'moss_layout'
        ]
        == layout()
    )


def test_general_moss_sources_strip_comments_only_once(unlocked):
    _, runtime = setup(unlocked)
    doc = layout()
    doc['mode'] = 'general'
    response = unlocked.post(
        '/api/image/single',
        json={
            'positive': r'Cafe \#1',
            'negative': r'\#literal',
            'settings': {'family': 'moss'},
            'moss_layout': doc,
            'prompt_sources': [
                {'kind': 'direct', 'id': '', 'name': '', 'positive': 'Cafe #1', 'negative': '#literal'}
            ],
        },
    )
    assert response.status_code == 200, response.text
    snapshot = runtime.queue.get(response.json()['job_id'])['snapshot']
    assert snapshot['positive'] == 'Cafe #1'
    assert snapshot['negative'] == '#literal'


def test_batch_preview_and_frozen_queue_match_without_mixing_expressions(unlocked):
    c = unlocked
    wid, runtime = setup(c, True)
    work = runtime.works.get(wid)
    library.save_item(
        runtime.paths,
        work,
        'expressions',
        'work',
        'moss-angry',
        {'name': 'Angry', 'prompt': ['scowling'], 'targets': ['moss']},
    )
    body = {
        'service': 'comfyui',
        'settings': {'family': 'moss', 'width': 1536, 'height': 1024, 'seed': 7},
        'common_ids': [],
        'artist': {'positive': 'watercolor'},
        'count': 1,
        'moss_layout': layout(True),
        'targets': [
            {'character_id': 'C001', 'outfit_id': 'o01', 'expression_id': 'smile'},
            {'character_id': 'C001', 'outfit_id': 'o01', 'expression_id': 'moss-angry'},
        ],
    }
    response = c.post(f'/api/works/{wid}/image/compose', json=body)
    assert response.status_code == 200, response.text
    preview = response.json()
    assert 'scowling' not in preview[0]['positive'] and 'scowling' in preview[1]['positive']
    assert 'watercolor' in json.loads(preview[0]['positive'])['summary']['caption']
    assert body['moss_layout']['items'][0].get('resolved') is None
    response = c.post(f'/api/works/{wid}/image/jobs', json=body)
    assert response.status_code == 200, response.text
    frozen = copy.deepcopy([j['snapshot'] for j in runtime.jobs])
    for index, job in enumerate(runtime.jobs):
        assert job['snapshot']['positive'] == preview[index]['positive']
        assert job['snapshot']['moss_layout'] == preview[index]['moss_layout']
    library.save_item(
        runtime.paths, work, 'expressions', 'work', 'moss-angry', {'name': 'Changed', 'prompt': ['laughing']}
    )
    assert [j['snapshot'] for j in runtime.jobs] == frozen


def test_template_round_trip_strips_specific_target_and_checks_revision(unlocked):
    c = unlocked
    _, runtime = setup(c)
    doc = layout(True)
    doc['items'][0]['resolved'] = {
        'caption': 'a specific person',
        'negative': '',
        'character_id': 'C001',
        'outfit_id': 'o01',
        'expression_id': 'smile',
        'name': 'Example',
    }
    item = {'name': 'Cafe layout', 'moss_layout': doc}
    response = c.put(
        '/api/image/library/compositions/cafe', json={'scope': 'global', 'revision': None, 'item': item}
    )
    assert response.status_code == 200, response.text
    stored = next(i for i in response.json().values() if i['name'] == 'Cafe layout')
    assert 'resolved' not in stored['moss_layout']['items'][0]
    assert stored['targets'] == ['moss']
    c.put('/api/image/library/rules/targets', json={'targets': [{'id': 'sdxl', 'name': 'SDXL'}]})
    reread = c.get('/api/image/library/compositions').json()[stored['id']]
    assert reread['targets'] == ['moss']
    assert not library.fits(reread, 'sdxl')
    assert (
        c.put(
            '/api/image/library/compositions/' + stored['id'],
            json={'scope': 'global', 'revision': None, 'item': item},
        ).status_code
        == 409
    )
    assert (
        json.loads((runtime.paths.data / 'image' / 'compositions.json').read_text(encoding='utf-8'))[
            'schema_version'
        ]
        == 3
    )
