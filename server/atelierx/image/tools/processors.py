"""Image tool features and the ways each can run (#151).

A feature (upscale, background split, inpaint …) runs on this PC through ComfyUI or, later, on an internet
service. Each (feature, method) pair is a processor registered here, so a new way to run a feature is a new
class instead of another branch. The tool screen asks which methods each feature has and greys out the others.
"""

from ...core.i18n import Msg

METHODS = ('local', 'novelai')
# Run outside this registry but shown with the same method choice: tagging has its own queue path.
OTHER_FEATURES = {'tag': ('local',)}

_REGISTRY = {}


class Processor:
    """One feature run one way. ``check`` normalises the options; ``build`` makes what the worker sends."""

    feature = ''
    method = 'local'
    label = None
    # The result is a mask the person edits and the app applies, of this tool-mask kind, not a new image.
    mask_kind = None
    # Redraws with the model and prompt the image was made with, so it needs the image's record.
    needs_record = False
    # Reads the image's saved tool mask of this kind (frozen when the job is queued).
    mask_input = None

    def check(self, options, info):
        raise NotImplementedError

    def build(self, runtime, job, item, path, reference):
        raise NotImplementedError

    def finish(self, runtime, job, item, image):
        """The result image as stored; a processor that redraws part of the image pastes it back here."""
        return image


def register(processor):
    _REGISTRY[(processor.feature, processor.method)] = processor
    return processor


def get(feature, method='local'):
    found = _REGISTRY.get((feature, method))
    if found is not None:
        return found
    if any(f == feature for f, _ in _REGISTRY) and method in METHODS:
        raise ValueError(
            Msg(
                'server.tools.method_unsupported',
                'This tool does not run with the chosen method ({method}).',
                method=method,
            )
        )
    raise ValueError(Msg('server.postprocess.unknown_post_process', 'Unknown post-process.'))


def features():
    """``{feature: [method, …]}`` for every tool feature, in the order of ``METHODS``."""
    out = {feature: list(methods) for feature, methods in OTHER_FEATURES.items()}
    for feature, method in _REGISTRY:
        out.setdefault(feature, []).append(method)
    return {feature: sorted(methods, key=METHODS.index) for feature, methods in out.items()}
