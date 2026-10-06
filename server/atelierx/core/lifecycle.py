"""One life cycle for every long-running job (#89): LLM work, image jobs, installs, LoRA training and conversions.

A job is ``queued`` until it starts, ``running`` while it works (``phase`` says which step, e.g. ``waiting_gpu`` or
``training``), ``cancelling`` from a cancel until it has really stopped, and then ``done``, ``failed`` or ``cancelled``.
A job cut off by the app closing is ``interrupted`` when the app starts again and can be retried; only work the
service keeps (an internet image task) carries on by itself. How each kind runs (a thread, asyncio) stays its own.
"""

QUEUED = 'queued'
RUNNING = 'running'
CANCELLING = 'cancelling'
DONE = 'done'
FAILED = 'failed'
CANCELLED = 'cancelled'
INTERRUPTED = 'interrupted'

STATES = (QUEUED, RUNNING, CANCELLING, DONE, FAILED, CANCELLED, INTERRUPTED)
ACTIVE = frozenset({RUNNING, CANCELLING})
UNFINISHED = frozenset({QUEUED, RUNNING, CANCELLING})
FINISHED = frozenset({DONE, FAILED, CANCELLED, INTERRUPTED})
RETRYABLE = frozenset({FAILED, CANCELLED, INTERRUPTED})

# Names used before #89, as stored in older files: status -> (status, phase).
LEGACY = {
    'completed': (DONE, None),
    'waiting_gpu': (QUEUED, 'waiting_gpu'),
    'preprocessing': (RUNNING, 'preprocessing'),
    'training': (RUNNING, 'training'),
}


def normalize(record):
    """Bring a stored job or run up to the current names in place; returns it."""
    old = record.get('status')
    if old in LEGACY:
        status, phase = LEGACY[old]
        record['status'] = status
        if phase and not record.get('phase'):
            record['phase'] = phase
    return record
