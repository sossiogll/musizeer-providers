"""MusicBrainz asks for at most one request per second: every request of the provider waits for its slot."""
import threading

import pytest

import musizeer_provider_musicbrainz as musicbrainz
from musizeer_sdk.context import StaticProviderContext
from musizeer_sdk.errors import ProviderRateLimited

from tests.conftest import FakeClock
from tests.helpers import Http


def test_requests_in_a_row_are_one_second_apart(clock, monkeypatch):
    http = Http({"/artist": {"artists": []}})
    monkeypatch.setattr(musicbrainz.httpx, "get", http)
    provider = musicbrainz.MusicBrainzMetadataProvider(StaticProviderContext())

    for _ in range(3):
        provider.search_artists("x", None)

    assert len(http.calls) == 3
    assert clock.sleeps == [1.0, 1.0]  # the first goes at once


def test_a_request_after_a_pause_does_not_wait(clock):
    pace = musicbrainz._Pace(1.0, clock=clock, sleep=clock.sleep)
    pace.wait(max_wait=10)
    clock.now += 5

    pace.wait(max_wait=10)

    assert clock.sleeps == []


def test_a_slot_further_than_the_bound_is_refused_with_how_long_to_wait(clock):
    pace = musicbrainz._Pace(1.0, clock=clock, sleep=lambda seconds: None)  # nobody's time passes
    for _ in range(3):
        pace.wait(max_wait=2)

    with pytest.raises(ProviderRateLimited) as refused:
        pace.wait(max_wait=2)

    assert refused.value.retry_after == 3


def test_threads_share_the_pace():
    clock = FakeClock()
    lock = threading.Lock()
    slots: list[float] = []

    def sleep(seconds: float) -> None:
        with lock:
            slots.append(seconds)

    pace = musicbrainz._Pace(1.0, clock=clock, sleep=sleep)
    threads = [threading.Thread(target=pace.wait, args=(100,)) for _ in range(5)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert sorted(slots) == [1.0, 2.0, 3.0, 4.0]  # one goes at once, each other one a second after the one before
