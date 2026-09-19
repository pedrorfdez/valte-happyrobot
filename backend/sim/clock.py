"""Scenario clock. Everything asks the clock what time it is; nothing else
touches wall time. scenario_t = start + (wall - t0) * speed."""

import time
from datetime import datetime, timedelta


class ScenarioClock:
    def __init__(self, start_iso: str, end_iso: str, speed: float):
        self.start = datetime.fromisoformat(start_iso)
        self.end = datetime.fromisoformat(end_iso)
        self.speed = speed
        self._t0_wall: float | None = None
        self._paused_at: datetime | None = None
        self._offset = timedelta(0)  # scenario time accumulated before last resume

    def start_running(self):
        self._t0_wall = time.monotonic()

    def pause(self):
        if self._t0_wall is not None:
            self._offset += self._elapsed_since_resume()
            self._t0_wall = None

    def resume(self):
        if self._t0_wall is None:
            self._t0_wall = time.monotonic()

    def _elapsed_since_resume(self) -> timedelta:
        if self._t0_wall is None:
            return timedelta(0)
        return timedelta(seconds=(time.monotonic() - self._t0_wall) * self.speed)

    def now(self) -> datetime:
        return self.start + self._offset + self._elapsed_since_resume()

    def finished(self) -> bool:
        return self.now() >= self.end
