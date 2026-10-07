"""A character's image design (20-image-design): read, save and convert."""

from starlette.routing import Route

from ..core.fsutil import read_json, write_json
from ..core.i18n import AppError, Msg
from ..core.snapshots import Snapshots
from ..image import designs as image_designs
from .common import body, ok, st, work_of


async def image_design(request):
    work = work_of(request)
    cid = request.path_params['cid']
    item = next((i for i in work.index() if i['kind'] == 'character' and i['meta'].get('id') == cid), None)
    if item is None:
        raise AppError(Msg('server.image.no_character', 'Character {id} was not found.', id=cid), 404)
    design = read_json(image_designs.character_design_path(work, cid))
    status = {}
    if design and item:
        body_text = work.get_item(item['path'])['body']
        parts = {'appearance': design.get('appearance', {})}
        parts.update({f'outfit:{k}': v for k, v in (design.get('outfits') or {}).items()})
        for key, part in parts.items():
            status[key] = image_designs.part_status(work, body_text, part)
    return ok({'design': design, 'status': status, 'revision': image_designs.revision(design)})


async def image_design_update(request):
    work = work_of(request)
    cid = request.path_params['cid']
    item = next((i for i in work.index() if i['kind'] == 'character' and i['meta'].get('id') == cid), None)
    if item is None:
        raise AppError(Msg('server.image.no_character', 'Character {id} was not found.', id=cid), 404)
    data = await body(request)
    design_path = image_designs.character_design_path(work, cid)
    previous = read_json(design_path)
    if data.get('base_revision') != image_designs.revision(previous):
        raise AppError(
            Msg('server.image.design.stale', 'The character design changed after it was loaded.'), 409
        )
    merged = image_designs.prepare_update(previous, data.get('design'))
    Snapshots(work).create('before_edit', '이미지 디자인 수정 전', force=True)
    write_json(design_path, merged)
    return ok({'design': merged, 'revision': image_designs.revision(merged)})


async def image_convert(request):
    work = work_of(request)
    return ok(st(request).work_jobs.image_prompt(work, request.path_params['cid'], await body(request)))


def routes():
    w = '/api/works/{wid}'
    return [
        Route(f'{w}/image/characters/{{cid}}', image_design),
        Route(f'{w}/image/characters/{{cid}}', image_design_update, methods=['PUT']),
        Route(f'{w}/image/characters/{{cid}}/convert', image_convert, methods=['POST']),
    ]
