"""HTTP routes of LoRA datasets, training runs and a character's LoRAs (22-datasets, 23-lora-training)."""

from pathlib import PureWindowsPath

from starlette.routing import Route

from ..image import settings as image_settings
from ..image.lora import datasets, link, models, setup
from .image_routes import _body, _runtime, call


def _work(request):
    runtime = _runtime(request)
    return runtime, runtime.works.get(request.path_params['wid']), request.path_params['cid']


async def overview(request):
    runtime, work, cid = _work(request)

    def build():
        return {
            'datasets': datasets.store.datasets(work, cid),
            'models': models.public(work, cid)['models'],
            **runtime.trainer.list(work, cid),
        }

    return await call(build)


async def candidates(request):
    runtime, work, cid = _work(request)
    outfits = [o for o in request.query_params.get('outfits', '').split(',') if o]
    return await call(datasets.candidates, runtime, work, cid, outfits)


async def dataset_save(request):
    runtime, work, cid = _work(request)
    return await call(datasets.save, runtime, work, cid, await _body(request))


async def dataset_captions(request):
    runtime, work, cid = _work(request)
    body = {**(await _body(request)), 'id': request.path_params['did']}
    return await call(datasets.edit_captions, runtime, work, cid, body)


async def dataset_delete(request):
    _, work, cid = _work(request)
    return await call(datasets.delete, work, cid, request.path_params['did'])


async def run_start(request):
    runtime, work, cid = _work(request)
    return await call(runtime.trainer.start, work, cid, await _body(request))


async def run_cancel(request):
    runtime, work, cid = _work(request)
    return await call(runtime.trainer.cancel, work, cid, request.path_params['rid'])


async def run_log(request):
    runtime, work, cid = _work(request)
    return await call(runtime.trainer.log_tail, work, cid, request.path_params['rid'])


async def model_add(request):
    """An epoch of a finished run (``run_id``, ``epoch``) or a LoRA file the image server has (``file``)."""
    runtime, work, cid = _work(request)
    body = await _body(request)
    if body.get('run_id'):
        return await call(runtime.trainer.register, work, cid, body)
    entry = {
        'id': body.get('id') or PureWindowsPath(str(body.get('file', ''))).stem,
        'name': body.get('name'),
        'file': body.get('file'),
        'strength': body.get('strength', 1.0),
        'model_family': body.get('model_family', 'anima'),
        'source': {'external': True},
    }
    return await call(models.add, work, cid, entry)


async def model_update(request):
    _, work, cid = _work(request)
    return await call(models.update, work, cid, request.path_params['mid'], await _body(request))


async def model_delete(request):
    _, work, cid = _work(request)
    return await call(models.remove, work, cid, request.path_params['mid'])


async def training_status(request):
    return await call(setup.status, _runtime(request).paths)


def _link_args(runtime):
    return (
        runtime.paths,
        image_settings.get(runtime.paths, 'training'),
        runtime.installs.model_folders(),
        image_settings.get(runtime.paths, 'models').get('models_dir'),
    )


async def lora_link_status(request):
    runtime = _runtime(request)
    return await call(lambda: link.status(*_link_args(runtime)))


async def lora_link_connect(request):
    runtime = _runtime(request)
    return await call(lambda: link.connect(*_link_args(runtime)))


async def lora_link_move(request):
    """Move the LoRAs of an older ComfyUI LoRA folder setting into the app, then link it (#160)."""
    runtime = _runtime(request)

    def move():
        values = image_settings.get(runtime.paths, 'training')
        works = runtime.works.all()
        moved = link.move_into_app(
            runtime.paths, values, lambda old, new: models.rename_file(works, old, new)
        )
        image_settings.save(runtime.paths, 'training', {'lora_dir': ''})
        return {'moved': moved, 'link': link.connect(*_link_args(runtime))}

    return await call(move)


def routes():
    p = '/api/works/{wid}/image/lora/{cid}'
    return [
        Route('/api/image/training/status', training_status),
        Route('/api/image/training/lora-link', lora_link_status),
        Route('/api/image/training/lora-link', lora_link_connect, methods=['POST']),
        Route('/api/image/training/lora-link/move', lora_link_move, methods=['POST']),
        Route(p, overview),
        Route(f'{p}/candidates', candidates),
        Route(f'{p}/datasets', dataset_save, methods=['POST']),
        Route(f'{p}/datasets/{{did}}/captions', dataset_captions, methods=['POST']),
        Route(f'{p}/datasets/{{did}}', dataset_delete, methods=['DELETE']),
        Route(f'{p}/runs', run_start, methods=['POST']),
        Route(f'{p}/runs/{{rid}}/cancel', run_cancel, methods=['POST']),
        Route(f'{p}/runs/{{rid}}/log', run_log),
        Route(f'{p}/models', model_add, methods=['POST']),
        Route(f'{p}/models/{{mid}}', model_update, methods=['PUT']),
        Route(f'{p}/models/{{mid}}', model_delete, methods=['DELETE']),
    ]
