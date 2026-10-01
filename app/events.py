"""In-memory fan-out of job events to whoever is watching (the SSE endpoint).

Events are hints that something changed; the database stays the source of truth, so a
subscriber that connects late or misses an event loses nothing it cannot re-read.
"""
from __future__ import annotations

import asyncio
from typing import Any

_END = object()


class Subscription:
    """An async iterator over one job's events. Ends when the job's channel closes or on cancel()."""

    def __init__(self, hub: EventHub, job_id: str) -> None:
        self._hub = hub
        self._job_id = job_id
        self._queue: asyncio.Queue[Any] = asyncio.Queue()

    def __aiter__(self) -> Subscription:
        return self

    async def __anext__(self) -> dict[str, Any]:
        event = await self._queue.get()
        if event is _END:
            self._hub._forget(self._job_id, self)
            raise StopAsyncIteration
        return event

    def cancel(self) -> None:
        self._hub._forget(self._job_id, self)
        self._queue.put_nowait(_END)


class EventHub:
    def __init__(self) -> None:
        self._subscriptions: dict[str, set[Subscription]] = {}

    def subscribe(self, job_id: str) -> Subscription:
        # Registered immediately (not on first iteration), so nothing published after this call is missed.
        subscription = Subscription(self, job_id)
        self._subscriptions.setdefault(job_id, set()).add(subscription)
        return subscription

    def publish(self, job_id: str, event: dict[str, Any]) -> None:
        # Unbounded queues: a slow subscriber never blocks the job that is publishing.
        for subscription in self._subscriptions.get(job_id, ()):
            subscription._queue.put_nowait(event)

    def close(self, job_id: str) -> None:
        for subscription in self._subscriptions.pop(job_id, set()):
            subscription._queue.put_nowait(_END)

    def subscriber_count(self, job_id: str) -> int:
        return len(self._subscriptions.get(job_id, ()))

    def _forget(self, job_id: str, subscription: Subscription) -> None:
        subscribers = self._subscriptions.get(job_id)
        if subscribers is not None:
            subscribers.discard(subscription)
            if not subscribers:
                del self._subscriptions[job_id]
