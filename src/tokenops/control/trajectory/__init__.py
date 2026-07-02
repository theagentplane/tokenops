"""Trajectory hint cache — scope keys, index build, and lookup helpers."""

__all__ = ["enqueue_completed_run", "schedule_trajectory_drain"]


def __getattr__(name: str):
    if name == "enqueue_completed_run":
        from tokenops.control.trajectory.enqueue import enqueue_completed_run

        return enqueue_completed_run
    if name == "schedule_trajectory_drain":
        from tokenops.control.trajectory.worker import schedule_trajectory_drain

        return schedule_trajectory_drain
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
