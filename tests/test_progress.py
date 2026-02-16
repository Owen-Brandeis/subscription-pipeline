"""Tests for progress store and SSE endpoint."""

import asyncio
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_progress_emit_subscribe_yields_in_order():
    """Progress store: emit events; subscribe yields events (latest first, then queue in order)."""
    from app.progress import ProgressEvent, emit, get_latest, init_case, subscribe

    case_id = "test_emit_sub_1"
    init_case(case_id)
    messages = ["A", "B", "C", "D"]
    for i, msg in enumerate(messages):
        emit(case_id, ProgressEvent(
            case_id=case_id, step="test",
            step_percent=(i + 1) * 25, overall_percent=(i + 1) * 25,
            message=msg,
        ))

    assert get_latest(case_id) is not None
    assert get_latest(case_id).message == "D"

    async def collect():
        out = []
        async for e in subscribe(case_id):
            out.append(e.message)
            if len(out) >= 5:  # latest + A,B,C,D
                break
        return out

    received = asyncio.run(collect())
    # Subscribe yields latest first, then queue. So we get D then A,B,C,D (queue order = emit order).
    assert "D" in received
    assert "A" in received
    # Queue portion (after first) should be in emit order
    idx_first = next(i for i, m in enumerate(received) if m == "A")
    queue_part = received[idx_first:]
    assert queue_part == ["A", "B", "C", "D"]


def test_events_returns_event_stream():
    """GET /events/{case_id} returns content-type text/event-stream."""
    from fastapi.testclient import TestClient

    from app.web import app
    from app.progress import init_case, emit, ProgressEvent

    case_id = "test_sse_case"
    init_case(case_id)
    # step=done so the SSE stream closes after sending this event
    emit(case_id, ProgressEvent(case_id, "done", 100, 100, "Done", 0.0))

    client = TestClient(app)
    r = client.get(f"/events/{case_id}")
    assert r.status_code == 200
    assert "text/event-stream" in (r.headers.get("content-type") or "")
    body = r.text
    assert "data:" in body
