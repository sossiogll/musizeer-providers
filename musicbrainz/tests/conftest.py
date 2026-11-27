import pytest

import musizeer_provider_musicbrainz as musicbrainz


class FakeClock:
    """Time that moves only when the code sleeps: the pace is checked without waiting."""

    def __init__(self) -> None:
        self.now = 1000.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


@pytest.fixture(autouse=True)
def clock(monkeypatch) -> FakeClock:
    """Every test runs on a fake clock: the one-request-per-second pace holds, and no test sleeps for real."""
    fake = FakeClock()
    monkeypatch.setattr(musicbrainz, "_PACE", musicbrainz._Pace(musicbrainz._MIN_INTERVAL_S, clock=fake, sleep=fake.sleep))
    return fake
