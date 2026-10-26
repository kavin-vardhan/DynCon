"""Time. Every rule in this server is evaluated from timestamps, so there is exactly one
way to ask what time it is: a Clock object. Tests pass a FakeClock and move it by hand.

DemoClock is the demo's own fast clock: demo time runs `factor` times faster than real
time (60x by default, so one demo hour is one real minute) and the time blocks the
attract rotation and allocations use are measured from the server's epoch.
"""
from __future__ import annotations

import math
import time
from datetime import datetime, timedelta, timezone

UTC = timezone.utc


def iso(dt: datetime) -> str:
    """UTC, fixed width, Z-suffixed — so string order is time order in SQL."""
    dt = dt.astimezone(UTC)
    return f"{dt:%Y-%m-%dT%H:%M:%S}.{dt.microsecond:06d}Z"


def parse_iso(s: str) -> datetime:
    t = s.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    return datetime.fromisoformat(t).astimezone(UTC)


class Clock:
    """What time is it. One implementation for real runs, one for tests."""

    def now(self) -> datetime:
        raise NotImplementedError

    def monotonic(self) -> float:
        return time.monotonic()


class RealClock(Clock):
    def now(self) -> datetime:
        return datetime.now(UTC)


class FakeClock(Clock):
    def __init__(self, start: datetime | None = None):
        self._now = (start or datetime(2026, 11, 14, 5, 0, 0, tzinfo=UTC)).astimezone(UTC)
        self._mono = 1000.0

    def now(self) -> datetime:
        return self._now

    def monotonic(self) -> float:
        return self._mono

    def set(self, dt: datetime) -> datetime:
        self._now = dt.astimezone(UTC)
        return self._now

    def advance(self, seconds: float) -> datetime:
        self._now = self._now + timedelta(seconds=seconds)
        self._mono += seconds
        return self._now


class DemoClock:
    """The demo's fast clock and its time blocks.

    epoch        real time the server first started (or was last epoch-reset)
    demo_start   the demo wall-clock time that epoch stands for ("14:00")
    factor       demo seconds per real second
    block_s      real seconds in one allocation block (3 demo hours = 3 real minutes)
    """

    def __init__(self, epoch: datetime, demo_start: datetime, factor: float, block_s: float):
        self.epoch = epoch.astimezone(UTC)
        self.demo_start = demo_start.astimezone(UTC)
        self.factor = float(factor)
        self.block_s = float(block_s)

    def real_elapsed(self, now: datetime) -> float:
        return (now.astimezone(UTC) - self.epoch).total_seconds()

    def demo_time(self, now: datetime) -> datetime:
        return self.demo_start + timedelta(seconds=self.real_elapsed(now) * self.factor)

    def demo_hours_elapsed(self, now: datetime) -> float:
        return self.real_elapsed(now) * self.factor / 3600.0

    def block_index(self, now: datetime) -> int:
        return int(math.floor(self.real_elapsed(now) / self.block_s))

    def block_start(self, index: int) -> datetime:
        return self.epoch + timedelta(seconds=index * self.block_s)

    def block_end(self, index: int) -> datetime:
        return self.block_start(index + 1)
