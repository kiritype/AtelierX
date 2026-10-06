"""What the internet image services share: the HTTP client, the wait between requests and refusals worth retrying.

Requests to a paid service are never repeated on the app's own: a request that got no answer may have been charged,
so it fails and the queue pauses until a person decides. Only a refusal the service itself says it did not run (rate
limit, busy) is tried again after a wait.
"""

import threading
import time

import httpx

from ...core.i18n import Msg
from ..services import GenerationService

RETRIES_WHEN_BUSY = 3
BUSY_WAIT = 10.0


class InternetService(GenerationService):
    """A service reached over HTTPS with a key from the vault. Subclasses send and read the requests."""

    local_gpu = False
    # A request sent cannot be called back; when its image arrives after a cancel it is kept (it is paid for).
    keep_on_cancel = True
    timeout = 180.0

    def __init__(self, config, stop):
        self.config = config  # ServiceConfig: key and wait between requests
        self.stop = stop  # the runtime's stop event, so waits end with the app
        self.transport = None  # tests answer HTTP calls with httpx.MockTransport
        self._last = 0.0
        self._lock = threading.Lock()

    def key(self):
        key = self.config.key(self.id)
        if not key:
            raise RuntimeError(
                Msg(
                    'server.image.services.no_key',
                    'No key for {service}. Add it in Settings → Image → Image services on the internet.',
                    service=self.name,
                )
            )
        return key

    def client(self):
        return httpx.Client(timeout=self.timeout, transport=self.transport, follow_redirects=True)

    def pace(self):
        """Wait until the set time has passed since the last request to this service."""
        with self._lock:
            wait = self._last + self.config.interval(self.id) - time.monotonic()
        if wait > 0 and self.stop.wait(wait):
            raise RuntimeError(Msg('server.worker.interrupted', 'Interrupted'))
        with self._lock:
            self._last = time.monotonic()

    def send(self, request):
        """Run ``request(client)`` (one HTTP call) with pacing; retry only refusals that were not run."""
        for attempt in range(RETRIES_WHEN_BUSY + 1):
            self.pace()
            try:
                with self.client() as client:
                    response = request(client)
            except httpx.TimeoutException as error:
                raise RuntimeError(self.no_answer()) from error
            except httpx.HTTPError as error:
                # Could not connect: nothing reached the service, but say so rather than guess and resend.
                raise RuntimeError(
                    Msg(
                        'server.image.services.unreachable',
                        'Could not reach {service}: {error}',
                        service=self.name,
                        error=str(error)[:300],
                    )
                ) from error
            if response.status_code == 429 and attempt < RETRIES_WHEN_BUSY:
                if self.stop.wait(BUSY_WAIT * (attempt + 1)):
                    raise RuntimeError(Msg('server.worker.interrupted', 'Interrupted'))
                continue
            return response
        return response

    def no_answer(self):
        return Msg(
            'server.image.services.no_answer',
            '{service} did not answer in time. The image may have been made and charged; check your account before '
            'retrying.',
            service=self.name,
        )

    def refused(self, response):
        """The error for a response that is not a success."""
        status = response.status_code
        detail = ''
        try:
            body = response.json()
            detail = str(body.get('message') or body.get('error') or body)[:500]
        except ValueError:
            detail = response.text[:500]
        if status == 401:
            return Msg(
                'server.image.services.bad_key',
                '{service} did not accept the key. Check it in Settings → Image.',
                service=self.name,
            )
        if status == 402:
            return Msg(
                'server.image.services.no_credit',
                '{service}: not enough credit for this image. {detail}',
                service=self.name,
                detail=detail,
            )
        if status == 429:
            return Msg(
                'server.image.services.busy',
                '{service} kept refusing for now (too many requests). Try again later.',
                service=self.name,
            )
        return Msg(
            'server.image.services.error',
            '{service} answered {status}: {detail}',
            service=self.name,
            status=status,
            detail=detail,
        )


def choice(value, allowed, default):
    return value if value in allowed else default


def whole(value, low, high, default):
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise ValueError(
            Msg('server.image.services.range', 'Use a whole number from {low} to {high}.', low=low, high=high)
        )
    return value


def number(value, low, high, default):
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not low <= value <= high:
        raise ValueError(
            Msg('server.image.services.range', 'Use a number from {low} to {high}.', low=low, high=high)
        )
    return float(value)
