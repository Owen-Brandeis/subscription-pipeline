"""In-memory progress store and SSE subscription for case processing."""

import asyncio
import time
from dataclasses import dataclass
from typing import AsyncIterator

# Steps: upload, parse, extract, validate, fill, deliver, done, error


@dataclass
class ProgressEvent:
    case_id: str
    step: str
    step_percent: int  # 0-100 within the step
    overall_percent: int  # 0-100 overall
    message: str
    ts: float = 0.0

    def __post_init__(self) -> None:
        if self.ts == 0.0:
            self.ts = time.time()

    def to_dict(self) -> dict:
        return {
            "case_id": self.case_id,
            "step": self.step,
            "step_percent": min(100, max(0, self.step_percent)),
            "overall_percent": min(100, max(0, self.overall_percent)),
            "message": self.message,
            "ts": self.ts,
        }


# In-memory: latest event per case + queue per case for streaming (single process; no Redis)
_progress_by_case: dict[str, ProgressEvent] = {}
_queues_by_case: dict[str, asyncio.Queue[ProgressEvent | None]] = {}


def init_case(case_id: str) -> None:
    """Initialize progress state for a case. Idempotent."""
    if case_id not in _queues_by_case:
        _queues_by_case[case_id] = asyncio.Queue()
    _progress_by_case[case_id] = ProgressEvent(
        case_id=case_id,
        step="upload",
        step_percent=0,
        overall_percent=0,
        message="Starting…",
    )


def emit(case_id: str, event: ProgressEvent) -> None:
    """Emit a progress event; store as latest and put on case queue for subscribers."""
    event.overall_percent = min(100, max(0, event.overall_percent))
    event.step_percent = min(100, max(0, event.step_percent))
    _progress_by_case[case_id] = event
    q = _queues_by_case.get(case_id)
    if q is not None:
        try:
            q.put_nowait(event)
        except asyncio.QueueFull:
            pass


def get_latest(case_id: str) -> ProgressEvent | None:
    """Return the latest progress event for the case, or None."""
    return _progress_by_case.get(case_id)


async def subscribe(case_id: str) -> AsyncIterator[ProgressEvent]:
    """Async generator yielding progress events for the case. Stops after step in ('done', 'error')."""
    init_case(case_id)
    q = _queues_by_case[case_id]
    latest = get_latest(case_id)
    if latest is not None:
        yield latest
    while True:
        try:
            event = await asyncio.wait_for(q.get(), timeout=300.0)
        except asyncio.TimeoutError:
            break
        if event is None:
            break
        yield event
        if event.step in ("done", "error"):
            break


def finish_subscription(case_id: str) -> None:
    """Signal subscribers to stop (sends None so subscriber loop exits)."""
    q = _queues_by_case.get(case_id)
    if q is not None:
        try:
            q.put_nowait(None)
        except asyncio.QueueFull:
            pass
