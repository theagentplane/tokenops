"""A background writer that sends ledger events without blocking the agent path.

Events are queued and sent in order, in batches, from one daemon thread. The plane does not
deduplicate events (control-plane ADR 0007), so the retry rule is the one in ADR 0003:

- a batch is retried **only** when the request provably never reached the plane (a failed
  or timed-out *connect*), with a short backoff and a bounded number of attempts;
- an unknown outcome (a read timeout, a reset after the request was sent, a ``5xx``) is
  **never** retried: the batch is dropped and counted, because applying it twice would
  overstate spend;
- a full queue drops the new events and counts them, so the agent never blocks on the plane.

Nothing here raises into the caller. ``stats`` says what was sent and what was lost.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass

import httpx

from tokenops.repositories.control_plane_client import ControlPlaneClient
from tokenops.repositories.control_plane_errors import ControlPlaneUnavailable
from tokenops.repositories.control_plane_types import LedgerEvent

logger = logging.getLogger("tokenops.ledger_writer")

_NEVER_REACHED = (httpx.ConnectError, httpx.ConnectTimeout)


@dataclass
class WriterStats:
    """Counters for events, not batches."""

    queued: int = 0
    sent: int = 0
    dropped_queue_full: int = 0
    dropped_unreachable: int = 0
    dropped_unknown_outcome: int = 0
    dropped_rejected: int = 0

    @property
    def dropped(self) -> int:
        return (
            self.dropped_queue_full
            + self.dropped_unreachable
            + self.dropped_unknown_outcome
            + self.dropped_rejected
        )


class LedgerEventWriter:
    """Queue ledger events and send them from a background thread."""

    def __init__(
        self,
        client: ControlPlaneClient,
        *,
        batch_size: int = 50,
        flush_interval_s: float = 0.25,
        max_queue: int = 10_000,
        connect_retries: int = 2,
        retry_backoff_s: float = 0.2,
        on_drop: Callable[[int, str], None] | None = None,
    ) -> None:
        self._client = client
        self._batch_size = max(1, batch_size)
        self._interval = flush_interval_s
        self._retries = max(0, connect_retries)
        self._backoff = retry_backoff_s
        self._on_drop = on_drop
        self._queue: queue.Queue[LedgerEvent] = queue.Queue(maxsize=max_queue)
        self._lock = threading.Lock()
        self._idle = threading.Condition(self._lock)
        self._in_flight = 0
        self._closed = False
        self.stats = WriterStats()
        self._thread = threading.Thread(
            target=self._run, name="tokenops-ledger-writer", daemon=True
        )
        self._thread.start()

    # ---- producer side (never blocks, never raises) ------------------------ #

    def submit(self, events: Sequence[LedgerEvent]) -> int:
        """Queue ``events``; return how many were accepted (the rest were dropped)."""
        accepted = 0
        for event in events:
            if self._closed:
                self._drop(1, "queue_full", "writer is closed")
                continue
            try:
                self._queue.put_nowait(event)
            except queue.Full:
                self._drop(1, "queue_full", "queue full")
                continue
            with self._lock:
                self._in_flight += 1
                self.stats.queued += 1
            accepted += 1
        return accepted

    def flush(self, timeout: float = 5.0) -> bool:
        """Wait until everything queued so far has been sent or dropped."""
        deadline = time.monotonic() + timeout
        with self._idle:
            while self._in_flight > 0:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._idle.wait(remaining)
        return True

    def close(self, timeout: float = 5.0) -> bool:
        """Flush, then stop the thread. Events submitted afterwards are dropped."""
        done = self.flush(timeout)
        self._closed = True
        return done

    # ---- worker ------------------------------------------------------------ #

    def _run(self) -> None:
        while True:
            try:
                first = self._queue.get(timeout=self._interval)
            except queue.Empty:
                if self._closed:
                    return
                continue
            batch = [first]
            while len(batch) < self._batch_size:
                try:
                    batch.append(self._queue.get_nowait())
                except queue.Empty:
                    break
            try:
                self._send(batch)
            finally:
                with self._idle:
                    self._in_flight -= len(batch)
                    self._idle.notify_all()

    def _send(self, batch: list[LedgerEvent]) -> None:
        attempts = 0
        while True:
            try:
                self._client.apply_events(batch)
            except ControlPlaneUnavailable as exc:
                if isinstance(exc.__cause__, _NEVER_REACHED):
                    if attempts < self._retries:
                        attempts += 1
                        time.sleep(self._backoff * attempts)
                        continue
                    self._drop(len(batch), "unreachable", str(exc))
                else:
                    self._drop(len(batch), "unknown_outcome", str(exc))
                return
            except Exception as exc:  # noqa: BLE001 - a 4xx or a bug must not kill the writer
                self._drop(len(batch), "rejected", str(exc))
                return
            with self._lock:
                self.stats.sent += len(batch)
            return

    def _drop(self, count: int, reason: str, detail: str) -> None:
        with self._lock:
            attr = f"dropped_{reason}"
            setattr(self.stats, attr, getattr(self.stats, attr) + count)
        logger.warning(
            "tokenops.ledger_events_dropped count=%d reason=%s detail=%s", count, reason, detail
        )
        if self._on_drop is not None:
            try:
                self._on_drop(count, reason)
            except Exception:  # noqa: BLE001 - a callback must not break the writer
                logger.exception("tokenops.ledger_writer on_drop callback failed")
