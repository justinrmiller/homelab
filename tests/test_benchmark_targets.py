"""Hostname and port resolution: CLI beats environment beats default."""

from __future__ import annotations

import argparse

import pytest

from benchmark.cli import shared_parser
from benchmark.targets import DEFAULT_KAFKA_PORT, resolve


def parse(*argv: str) -> argparse.Namespace:
    return argparse.ArgumentParser(parents=[shared_parser()]).parse_args(list(argv))


def test_host_flag_sets_every_service(clean_env):
    targets = resolve(parse("--host", "nas.local"))
    assert targets.host == "nas.local"
    assert targets.s3.endpoint_url == "http://nas.local:4566"
    assert targets.valkey.host == "nas.local"
    assert targets.valkey.port == 6379
    assert targets.kafka.bootstrap_servers == "nas.local:9092"


def test_kafka_defaults_to_the_published_host_listener(clean_env):
    """The broker's other listener, kafka:29092, is compose-internal only."""
    assert DEFAULT_KAFKA_PORT == 9092
    assert resolve(parse("--host", "nas.local")).kafka.bootstrap_servers.endswith(":9092")


def test_port_flags_override_the_defaults(clean_env):
    targets = resolve(parse("--host", "nas.local", "--kafka-port", "29092", "--s3-port", "9000"))
    assert targets.kafka.bootstrap_servers == "nas.local:29092"
    assert targets.s3.endpoint_url == "http://nas.local:9000"


def test_environment_is_used_when_no_host_is_given(clean_env):
    clean_env.setenv("AWS_ENDPOINT_URL", "http://floci.example:4567")
    clean_env.setenv("VALKEY_HOST", "valkey.example")
    targets = resolve(parse())
    assert targets.s3.endpoint_url == "http://floci.example:4567"
    assert targets.valkey.host == "valkey.example"


def test_cli_host_wins_over_the_environment(clean_env):
    clean_env.setenv("AWS_ENDPOINT_URL", "http://floci.example:4567")
    clean_env.setenv("VALKEY_HOST", "valkey.example")
    targets = resolve(parse("--host", "nas.local"))
    assert targets.s3.endpoint_url == "http://nas.local:4566"
    assert targets.valkey.host == "nas.local"


def test_port_flag_rewrites_only_the_port_of_an_environment_endpoint(clean_env):
    clean_env.setenv("AWS_ENDPOINT_URL", "http://floci.example:4567")
    assert resolve(parse("--s3-port", "9000")).s3.endpoint_url == "http://floci.example:9000"


def test_kafka_port_flag_keeps_the_environment_host(clean_env):
    clean_env.setenv("KAFKA_BOOTSTRAP_SERVERS", "broker.example:9092")
    assert resolve(parse("--kafka-port", "29092")).kafka.bootstrap_servers == "broker.example:29092"


def test_credentials_and_region_pass_through_untouched(clean_env):
    clean_env.setenv("AWS_ACCESS_KEY_ID", "key")
    clean_env.setenv("AWS_SECRET_ACCESS_KEY", "secret")
    clean_env.setenv("AWS_DEFAULT_REGION", "eu-west-1")
    s3 = resolve(parse("--host", "nas.local")).s3
    assert (s3.access_key, s3.secret_key, s3.region) == ("key", "secret", "eu-west-1")


@pytest.mark.parametrize("host", ["localhost", "nas.local", "192.168.1.10"])
def test_any_host_produces_a_usable_endpoint(clean_env, host):
    assert resolve(parse("--host", host)).s3.endpoint_url == f"http://{host}:4566"
