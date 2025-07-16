import time


class SyncManager:
    """High-resolution master clock and orchestrator."""

    def __init__(self):
        self._epoch_ns = time.perf_counter_ns()
        self._next_ns = self._epoch_ns

    def get_time_ns(self) -> int:
        return time.perf_counter_ns() - self._epoch_ns

    def wait_next_period(self, period_ms: int):
        self._next_ns += period_ms * 1_000_000
        while time.perf_counter_ns() < self._next_ns:
            time.sleep(0)
