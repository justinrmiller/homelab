"""The pure parts of the Kafka benchmark: preflight and leader waiting."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from benchmark import cli
from benchmark.kafka_bench import advertised_mismatch, wait_for_leaders


def test_a_loopback_advertisement_is_fatal_for_a_remote_host():
    problem = advertised_mismatch(["localhost"], "nas.local")
    assert problem is not None
    assert "KAFKA_ADVERTISED_HOST=nas.local" in problem


@pytest.mark.parametrize("advertised", ["127.0.0.1", "::1", "0.0.0.0", "LOCALHOST"])
def test_every_loopback_spelling_is_caught(advertised):
    assert advertised_mismatch([advertised], "nas.local") is not None


def test_one_loopback_broker_among_several_still_trips_it():
    assert advertised_mismatch(["nas.local", "127.0.0.1"], "nas.local") is not None


def test_benchmarking_localhost_is_fine():
    assert advertised_mismatch(["localhost"], "localhost") is None
    assert advertised_mismatch(["localhost"], "127.0.0.1") is None


def test_a_matching_advertisement_is_fine():
    assert advertised_mismatch(["nas.local"], "nas.local") is None


def test_a_different_but_routable_advertisement_is_not_fatal():
    assert advertised_mismatch(["broker.internal"], "nas.local") is None


class FakeAdmin:
    """Stands in for AdminClient, returning canned ClusterMetadata."""

    def __init__(self, leaders: list[int], partitions: int = 1) -> None:
        self.leaders = list(leaders)
        self.partitions = partitions
        self.calls = 0

    def list_topics(self, topic: str, timeout: float) -> SimpleNamespace:
        self.calls += 1
        leader = self.leaders[min(self.calls - 1, len(self.leaders) - 1)]
        parts = {i: SimpleNamespace(leader=leader, error=None) for i in range(self.partitions)}
        return SimpleNamespace(topics={topic: SimpleNamespace(error=None, partitions=parts)})


def test_wait_for_leaders_returns_once_a_leader_is_elected():
    admin = FakeAdmin(leaders=[-1, -1, 0])
    wait_for_leaders(admin, "bench-x", partitions=1, timeout=5)
    assert admin.calls == 3


def test_wait_for_leaders_gives_up_with_a_preflight_error():
    admin = FakeAdmin(leaders=[-1])
    with pytest.raises(cli.PreflightError, match="no partition leaders"):
        wait_for_leaders(admin, "bench-x", partitions=1, timeout=0.5)


def test_wait_for_leaders_waits_for_every_partition():
    admin = FakeAdmin(leaders=[0], partitions=2)
    with pytest.raises(cli.PreflightError):
        # Metadata only ever reports two partitions; asking for three must not
        # be satisfied by a prefix of them.
        wait_for_leaders(admin, "bench-x", partitions=3, timeout=0.5)


def test_a_missing_topic_is_not_mistaken_for_a_ready_one():
    class Missing:
        def list_topics(self, topic: str, timeout: float) -> SimpleNamespace:
            return SimpleNamespace(topics={})

    with pytest.raises(cli.PreflightError):
        wait_for_leaders(Missing(), "bench-x", partitions=1, timeout=0.3)
