import io
import json
import time
import zipfile

from PIL import Image, PngImagePlugin

from test_image import FakeComfy


class ToolComfy(FakeComfy):
    """FakeComfy plus the node list, uploads and the tagger / upscale outputs the tools read."""

    def __init__(self):
        super().__init__()
        self.uploads = []

    def upload(self, name, raw, subfolder='atelierx'):
        self.uploads.append(name)
        return {'name': name, 'subfolder': subfolder}

    def request(self, path, body=None, raw=False, timeout=15):
        if path == '/object_info':
            return {
                'AtelierXUpscale': {},
                'RemBGSession+': {},
                'UpscaleModelLoader': {'input': {'required': {'model_name': [['2x-Anime.pth']]}}},
            }
        if path.startswith('/object_info/WD14Tagger'):
            return {'WD14Tagger|pysssss': {'input': {'required': {'model': [['wd-eva02-large-tagger-v3']]}}}}
        if path == '/prompt':
            self.prompts.append(body['prompt'])
            return {'prompt_id': 'p1'}
        if path.startswith('/history/') and 'WD14Tagger|pysssss' in json.dumps(self.prompts[-1]):
            return {
                'p1': {
                    'status': {'status_str': 'success'},
                    'outputs': {'2': {'tags': ['1girl, smile, long hair']}},
                }
            }
        return super().request(path, body, raw, timeout)


def png(color=(10, 120, 200), size=(40, 30), text=None):
    out = io.BytesIO()
    info = PngImagePlugin.PngInfo()
    for key, value in (text or {}).items():
        info.add_text(key, value)
    Image.new('RGB', size, color).save(out, format='PNG', pnginfo=info)
    return out.getvalue()


def upload(c, name, raw):
    return c.post('/api/image/tools/upload', content=raw, headers={'X-File-Name': name}).json()


def test_workspace_convert_mask_and_cpu_tools(unlocked):
    c = unlocked
    params = 'masterpiece, 1girl\nNegative prompt: lowres\nSteps: 20, Sampler: Euler a, CFG scale: 5, Seed: 7'
    added = upload(c, 'a.png', png(text={'parameters': params}))['added']
    (item,) = added
    assert (item['width'], item['height'], item['source']) == (40, 30, 'upload')
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, 'w') as z:
        z.writestr('x/b.png', png((200, 0, 0)))
        z.writestr('notes.txt', 'hi')
    result = upload(c, 'pack.zip', archive.getvalue())
    assert len(result['added']) == 1 and result['skipped'][0]['name'] == 'notes.txt'
    assert (
        c.post(
            '/api/image/tools/upload', content=b'not an image', headers={'X-File-Name': 'z.png'}
        ).status_code
        == 400
    )

    info = c.get('/api/image/tools/analyze', params={'id': item['id']}).json()
    assert info['prompt']['source'] == 'parameters' and info['prompt']['negative'] == 'lowres'
    assert (
        c.get('/api/image/tools/thumbnail', params={'id': item['id']}).headers['content-type'] == 'image/webp'
    )

    task = c.post(
        '/api/image/tools/convert', json={'ids': [item['id']], 'quality': 90, 'long_side': 20}
    ).json()['task']
    for _ in range(100):
        task = c.get('/api/image/tools/convert/task', params={'id': task['id']}).json()
        if task['status'] == 'completed':
            break
        time.sleep(0.05)
    (converted,) = task['results']
    assert (converted['width'], converted['height']) == (20, 15) and converted['relative_path'].startswith(
        '_tools/'
    )
    assert c.get(converted['url']).status_code == 200

    # A mask the size of the image: the left half is covered.
    mask = Image.new('L', (40, 30), 0)
    mask.paste(255, (0, 0, 20, 30))
    out = io.BytesIO()
    mask.save(out, 'PNG')
    assert (
        c.put('/api/image/tools/mask', params={'id': item['id']}, content=out.getvalue()).status_code == 200
    )
    wrong = Image.new('L', (10, 10))
    out2 = io.BytesIO()
    wrong.save(out2, 'PNG')
    assert (
        c.put('/api/image/tools/mask', params={'id': item['id']}, content=out2.getvalue()).status_code == 400
    )
    assert c.get('/api/image/tools/mask', params={'id': item['id']}).status_code == 200
    censored = c.post(
        '/api/image/tools/censor', json={'id': item['id'], 'treatment': 'color', 'color': '#000000'}
    ).json()
    pixels = Image.open(io.BytesIO(c.get(censored['url']).content)).convert('RGB')
    assert pixels.getpixel((5, 5)) == (0, 0, 0) and pixels.getpixel((35, 5)) == (10, 120, 200)

    c.put('/api/image/tools/mask', params={'id': item['id'], 'kind': 'alpha'}, content=out.getvalue())
    cut = c.post('/api/image/tools/alpha', json={'id': item['id']}).json()
    alpha = Image.open(io.BytesIO(c.get(cut['url']).content))
    assert alpha.mode == 'RGBA' and alpha.getpixel((35, 5))[3] == 0 and alpha.getpixel((5, 5))[3] == 255

    listed = c.get('/api/image/tools/items').json()['items']
    assert {i['op'] for i in listed if i.get('parent') == item['id']} == {'censor', 'alpha'}
    zipped = c.get('/api/image/tools/zip', params={'ids': item['id']})
    assert zipfile.ZipFile(io.BytesIO(zipped.content)).namelist() == ['a.png']
    assert c.post('/api/image/tools/remove', json={'ids': [item['id']]}).json()['removed'] == 1


def test_tag_and_upscale_jobs_run_through_the_queue(unlocked):
    c = unlocked
    runtime = c.app.state.app.image
    runtime.comfy = ToolComfy()
    runtime.set_paused(True)
    (item,) = upload(c, 'a.png', png())['added']
    c.put('/api/image/settings/tags', json={'exclude': ['smile']})

    jobs = c.post('/api/image/tools/tag', json={'ids': [item['id']]}).json()['jobs']
    job = next(j for j in runtime.jobs if j['id'] == jobs[0]['id'])
    job['status'] = 'running'
    runtime.run_job(job)
    assert job['status'] == 'completed', job.get('error')
    tagged = c.get('/api/image/tools/items').json()['items'][0]
    assert tagged['tags']['tags'] == ['1girl', 'smile', 'long hair']
    exported = c.get('/api/image/tools/tags/export', params={'ids': item['id'], 'format': 'json'}).json()
    assert exported[0]['tags'] == ['1girl', 'long hair']

    bad = c.post(
        '/api/image/tools/postprocess',
        json={'ids': [item['id']], 'op': 'upscale', 'options': {'model': 'x.pth'}},
    )
    assert bad.status_code == 400
    c.post(
        '/api/image/tools/postprocess', json={'ids': [item['id']], 'op': 'upscale', 'options': {'scale': 2}}
    )
    job = runtime.jobs[-1]
    job['status'] = 'running'
    runtime.run_job(job)
    assert job['status'] == 'completed', job.get('error')
    graph = runtime.comfy.prompts[-1]
    assert (
        graph['2']['class_type'] == 'AtelierXUpscale'
        and graph['2']['inputs']['upscale_model'] == '2x-Anime.pth'
    )
    assert '/_tools/' in job['image_url']
    record = json.loads(Image.open(io.BytesIO(c.get(job['image_url']).content)).text['atelierx'])
    assert record['op'] == 'upscale' and record['source']['tool_item'] == item['id']
