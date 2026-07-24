"""Thread-safety (§15) — concurrent Ledger / Store / governance cache."""

from __future__ import annotations

import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from conftest import make_attr, toy_price
from tokenops.control.core import Observation, Usage
from tokenops.control.governance_cache import (
    clear_governance_config_cache,
    governance_config_cache_size,
)
from tokenops.control.ledger import Ledger
from tokenops.control.models import PolicyInstance
from tokenops.control.store import Store


@pytest.fixture(autouse=True)
def _clear_cache():
    clear_governance_config_cache()
    yield
    clear_governance_config_cache()


def _llm_obs(run_id: str, ts: float, *, input_tokens: int = 100) -> Observation:
    return Observation(
        attr=make_attr(run_id=run_id),
        node_type="llm",
        boundary_id="chat",
        ts=ts,
        provider="openai",
        model="gpt-4o-mini",
        usage=Usage(input=input_tokens, output=0),
    )


def test_concurrent_record_two_run_ids_no_lost_updates():
    ledger = Ledger(price=toy_price)
    ledger.open_run("run-a")
    ledger.open_run("run-b")
    n = 50
    # 100 input tokens → 1000 micros each (toy_price)
    per_call = 1000

    def worker(run_id: str) -> None:
        for i in range(n):
            ledger.record(_llm_obs(run_id, float(i), input_tokens=100))

    t1 = threading.Thread(target=worker, args=("run-a",))
    t2 = threading.Thread(target=worker, args=("run-b",))
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    assert ledger.step_count("run-a") == n
    assert ledger.step_count("run-b") == n
    assert ledger.cost_micros("run-a") == n * per_call
    assert ledger.cost_micros("run-b") == n * per_call
    assert len(ledger.window("run-a")) == n
    assert len(ledger.window("run-b")) == n


def test_concurrent_store_backed_spend_two_run_ids(tmp_path):
    store = Store(str(tmp_path / "ledger.db"), auto_seed=False)
    try:
        # Two Ledgers / "Governors" sharing one Store (same process).
        la = Ledger(price=toy_price, store=store)
        lb = Ledger(price=toy_price, store=store)
        la.open_run("run-a")
        lb.open_run("run-b")
        n = 40
        per_call = 1000

        def worker(ledger: Ledger, run_id: str) -> None:
            for i in range(n):
                ledger.record(_llm_obs(run_id, float(i)))

        with ThreadPoolExecutor(max_workers=2) as pool:
            fa = pool.submit(worker, la, "run-a")
            fb = pool.submit(worker, lb, "run-b")
            fa.result()
            fb.result()

        assert store.ledger_get_spent("__run_total__", "run:run-a", "lifetime") == n * per_call
        assert store.ledger_get_spent("__run_total__", "run:run-b", "lifetime") == n * per_call
        assert la.cost_micros("run-a") == n * per_call
        assert lb.cost_micros("run-b") == n * per_call
    finally:
        store.close()


def test_halt_flag_not_torn_under_concurrent_mark_and_read():
    ledger = Ledger(price=toy_price)
    ledger.open_run("run-1")
    stop = threading.Event()
    errors: list[BaseException] = []

    def marker() -> None:
        try:
            for i in range(200):
                ledger.mark_halted("run-1", f"reason-{i}")
        except BaseException as exc:  # noqa: BLE001 — collect for main thread
            errors.append(exc)

    def reader() -> None:
        try:
            while not stop.is_set():
                halted = ledger.is_halted("run-1")
                if not isinstance(halted, bool):
                    raise AssertionError(f"torn halt value: {halted!r}")
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    readers = [threading.Thread(target=reader) for _ in range(4)]
    for t in readers:
        t.start()
    marker = threading.Thread(target=marker)
    marker.start()
    marker.join()
    stop.set()
    for t in readers:
        t.join()

    assert not errors
    assert ledger.is_halted("run-1") is True
    assert ledger.runs["run-1"].halt_reason is not None


def test_store_halt_not_torn_under_concurrent_access(tmp_path):
    store = Store(str(tmp_path / "halt.db"), auto_seed=False)
    try:
        ledger = Ledger(price=toy_price, store=store)
        ledger.open_run("run-1")
        stop = threading.Event()
        errors: list[BaseException] = []

        def marker() -> None:
            try:
                for i in range(100):
                    ledger.mark_halted("run-1", f"r-{i}")
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)

        def reader() -> None:
            try:
                while not stop.is_set():
                    assert isinstance(ledger.is_halted("run-1"), bool)
                    assert isinstance(store.ledger_is_halted("run-1"), bool)
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=reader) for _ in range(3)]
        for t in threads:
            t.start()
        m = threading.Thread(target=marker)
        m.start()
        m.join()
        stop.set()
        for t in threads:
            t.join()

        assert not errors
        assert ledger.is_halted("run-1") is True
        assert store.ledger_is_halted("run-1") is True
    finally:
        store.close()


def test_governance_config_cache_concurrent_get_set_invalidate(tmp_path):
    store = Store(str(tmp_path / "gov.db"), auto_seed=False)
    store.upsert_policy_instance(
        PolicyInstance(id="p1", template="step_cap", params={"max_steps": 3}, agent="planner"),
    )
    errors: list[BaseException] = []
    barrier = threading.Barrier(8)

    def reader() -> None:
        try:
            barrier.wait()
            for _ in range(30):
                cfg = store.governance_config_for("planner")
                assert "step_cap" in cfg["governance"]["policies"]
                assert cfg["governance"]["policies"]["step_cap"]["max_steps"] in (3, 7)
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    def writer() -> None:
        try:
            barrier.wait()
            for i in range(15):
                store.upsert_policy_instance(
                    PolicyInstance(
                        id="p1",
                        template="step_cap",
                        params={"max_steps": 7 if i % 2 else 3},
                        agent="planner",
                    ),
                )
                clear_governance_config_cache(store_path=store.path)
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=reader) for _ in range(6)]
    threads += [threading.Thread(target=writer) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors
    # Cache remains consistent (size is small; may be 0 after last invalidate).
    assert governance_config_cache_size() >= 0
    store.close()


def test_asyncio_tasks_two_run_ids_via_to_thread():
    """Async tasks that hop to threads for Ledger.record — no lost updates."""
    ledger = Ledger(price=toy_price)
    ledger.open_run("run-a")
    ledger.open_run("run-b")
    n = 30
    per_call = 1000

    async def main() -> None:
        async def hammer(run_id: str) -> None:
            for i in range(n):
                await asyncio.to_thread(ledger.record, _llm_obs(run_id, float(i)))

        await asyncio.gather(hammer("run-a"), hammer("run-b"))

    asyncio.run(main())
    assert ledger.cost_micros("run-a") == n * per_call
    assert ledger.cost_micros("run-b") == n * per_call
    assert ledger.step_count("run-a") == n
    assert ledger.step_count("run-b") == n
