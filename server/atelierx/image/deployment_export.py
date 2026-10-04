"""Deployment ZIP path planning for adopted gallery images."""

from pathlib import PurePosixPath


def export_path(item, source_path, *, one_work):
    """Keep the deployment layout and name each adopted image from its expression metadata."""
    combo = [item.get(k) for k in ('work_id', 'character_id', 'outfit_id', 'expression_id')]
    if not all(isinstance(part, str) and part for part in combo):
        raise ValueError('Adopted image is missing combination metadata.')
    if any(part in ('.', '..') or '/' in part or '\\' in part or ':' in part for part in combo):
        raise ValueError('Adopted image has invalid combination metadata.')
    source = PurePosixPath(source_path.replace('\\', '/'))
    folders = combo[1:3] if one_work else combo[:3]
    return '/'.join((*folders, f'{combo[3]}{source.suffix.lower()}'))


def plan_paths(items, *, one_work):
    """Return source -> deployment paths and any colliding destinations."""
    mapping = {}
    owners = {}
    collisions = set()
    for item in items:
        source = item['path']
        destination = export_path(item, source, one_work=one_work)
        if destination in owners and owners[destination] != source:
            collisions.add(destination)
        owners[destination] = source
        mapping[source] = destination
    return mapping, sorted(collisions)
