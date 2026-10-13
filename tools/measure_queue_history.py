"""Measure synthetic queue history and incremental bulk receipts without reading application data (#229)."""

import argparse
import copy
import json
import sqlite3
import statistics
import sys
import tempfile
import threading
import time
import tracemalloc
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server'))

from atelierx.image.job_queue import JobQueue


def timed(fn, repeats=3):
    durations = []
    for _ in range(repeats):
        start = time.perf_counter()
        fn()
        durations.append(time.perf_counter() - start)
    return round(statistics.median(durations), 6)


def measure(folder, count):
    queue = JobQueue(folder / f'queue-{count}.json', threading.RLock())
    template = {
        'status': 'done',
        'kind': 'generate',
        'work_id': 'demo',
        'created_at': '2026-10-14T00:00:00Z',
        'snapshot': {
            'prompt': 'demo prompt, ' * 200,
            'negative': 'demo negative, ' * 100,
            'settings': {'steps': 28, 'width': 1024, 'height': 1024, 'seed': 42},
        },
        'workflow': {'demo': {'inputs': {'text': 'sample, ' * 150}}},
        'outputs': ['demo/sample.png'],
    }
    queue.jobs = [{**copy.deepcopy(template), 'id': f'demo-{i}'} for i in range(count)]
    write = timed(queue.persist)
    restore = JobQueue(queue.path, threading.RLock())
    load = timed(restore.load)
    tracemalloc.start()
    restore.load()
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    db_path = folder / f'receipts-{count}.sqlite3'
    db = sqlite3.connect(db_path)
    db.execute('PRAGMA journal_mode=WAL')
    db.execute('PRAGMA synchronous=FULL')
    db.execute('CREATE TABLE items(id INTEGER PRIMARY KEY, source TEXT, status TEXT, result TEXT)')
    start = time.perf_counter()
    with db:
        db.executemany(
            'INSERT INTO items VALUES (?, ?, ?, ?)',
            [
                (i, json.dumps({'id': f'demo-{i}', 'mtime_ns': 123, 'size': 123456}), 'pending', None)
                for i in range(count)
            ],
        )
    receipt = time.perf_counter() - start

    updates = 0

    def update():
        nonlocal updates
        updates += 1
        with db:
            db.execute(
                "UPDATE items SET status='done', result=? WHERE id=0",
                (json.dumps({**template, 'measurement_update': updates}),),
            )

    update_time = timed(update)
    restore_time = timed(lambda: list(db.execute("SELECT id FROM items WHERE status='pending' LIMIT 32")))
    db.execute('PRAGMA wal_checkpoint(TRUNCATE)')
    result = {
        'count': count,
        'queue_bytes': queue.path.stat().st_size,
        'queue_save_median_s': write,
        'queue_restore_median_s': load,
        'queue_restore_peak_bytes': peak,
        'receipt_bytes': db_path.stat().st_size,
        'receipt_accept_s': round(receipt, 6),
        'receipt_update_median_s': update_time,
        'receipt_restore_32_median_s': restore_time,
    }
    db.close()
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    # Each run creates a fresh synthetic directory; no live app paths are accepted.
    with tempfile.TemporaryDirectory(prefix='queue-history-', dir=args.output.parent) as temporary:
        rows = [measure(Path(temporary), count) for count in (1000, 5000, 20000)]
    args.output.write_text(json.dumps(rows, indent=2), encoding='utf-8')
    print(json.dumps(rows, indent=2))


if __name__ == '__main__':
    main()
