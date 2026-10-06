"""Adopting a review draft into the work (07-review: 채택), by the draft's kind (#90).

Text edits are adopted by the editor's own route; content reviews are read-only. Every adoption that changes files
takes a snapshot first.
"""

from ..image import designs as image_designs
from . import authoring, review
from .drafts import Drafts
from .fsutil import read_json, write_json
from .i18n import AppError, Msg
from .snapshots import Snapshots


def apply(work, did, data):
    drafts = Drafts(work)
    doc = drafts.get(did)
    if doc['kind'] == 'content_review':
        raise AppError(Msg('server.editor.review_read_only', 'Review drafts are read-only.'))
    if doc['kind'] == 'image_prompt':
        if doc.get('status') != 'pending':
            raise AppError(Msg('server.drafts.not_pending', 'This draft has already been handled.'), 409)
        cid = doc['target']['id']
        design_path = image_designs.character_design_path(work, cid)
        current = read_json(design_path)
        expected = doc['target'].get('base_design_revision')
        if image_designs.revision(current) != expected:
            raise AppError(
                Msg(
                    'server.image.design.stale',
                    'The character design changed after this conversion draft was created.',
                ),
                409,
            )
        submitted = data.get('design', doc['candidates'][0]['design'])
        image_designs.validate(submitted)
        merged = image_designs.reconcile_conversion(current, submitted)
        Snapshots(work).create('before_llm', 'LLM 결과 채택 전', force=True)
        write_json(design_path, merged)
        doc['applied_design'] = merged
        drafts.save(did, doc)
        drafts.set_status(did, 'applied')
        return {'path': design_path.relative_to(work.folder).as_posix(), 'design': merged}
    Snapshots(work).create('before_llm', 'LLM 결과 채택 전', force=True)
    if doc['kind'] == 'relations':
        result = review.apply_relation_rows(
            work, data.get('rows', []), doc['candidates'][0].get('people', [])
        )
        drafts.set_status(did, 'applied')
        return result
    if doc['kind'] == 'jsx_prompt':
        result = review.insert_text(
            work,
            data.get('text') or doc['candidates'][0]['text'],
            path=data.get('path'),
            new_path=data.get('new_path'),
            position=data.get('position', 'end'),
            heading=data.get('heading'),
        )
        drafts.set_status(did, 'applied')
        return result
    if doc['kind'] == 'authoring':
        result = authoring.create_files(work, data.get('files', []), data.get('relations', []))
        drafts.set_status(did, 'applied')
        return result
    return drafts.apply_text(
        did,
        data['text'],
        data.get('mode', 'overwrite'),
        data.get('new_name'),
        data.get('enable', 'new'),
    )
