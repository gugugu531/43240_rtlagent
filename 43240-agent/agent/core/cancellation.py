"""Cooperative cancellation for in-process actions."""
from threading import Event


class Cancelled(RuntimeError):
    pass


class CancellationToken:
    def __init__(self):
        self._event = Event()
        self.reason = None

    def cancel(self, reason: str):
        self.reason = reason
        self._event.set()

    def raise_if_cancelled(self):
        if self._event.is_set():
            raise Cancelled(self.reason or 'cancelled')
