"""Server -> UI event stream (SSE): job progress, notifications, lock."""

import asyncio
import json


class Events:
    def __init__(self):
        self._queues = set()

    def subscribe(self):
        queue = asyncio.Queue(maxsize=500)
        self._queues.add(queue)
        return queue

    def unsubscribe(self, queue):
        self._queues.discard(queue)

    def publish(self, kind, data=None):
        message = json.dumps({'type': kind, 'data': data or {}}, ensure_ascii=False)
        for queue in list(self._queues):
            try:
                queue.put_nowait(message)
            except asyncio.QueueFull:
                pass
