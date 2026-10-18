"""Resolve legacy fixture labels to canonical UUIDs without bypassing startup migration."""

from atelierx.image.uuid_migration import resolve


def image_id(subject, kind, legacy, work=None):
    paths = (
        subject.app.state.app.paths if hasattr(subject, 'app') and hasattr(subject.app, 'state') else subject
    )
    return resolve(paths, kind, legacy, work)
