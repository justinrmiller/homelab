from __future__ import annotations

import pytest

from dashboard import clients


def test_valkey_client_targets_configured_host(config):
    client = clients.make_valkey_client(config.valkey)
    kwargs = client.connection_pool.connection_kwargs

    assert kwargs["host"] == "valkey"
    assert kwargs["port"] == 6379
    assert kwargs["socket_timeout"] == clients.DEFAULT_TIMEOUT


def test_schema_registry_client_targets_configured_base_url(config):
    from dashboard.schema_registry import SchemaRegistryClient

    client = clients.make_schema_registry_client(config.schema_registry)

    assert isinstance(client, SchemaRegistryClient)
    assert client.base_url == "http://schema-registry:8081"
    assert client.timeout == clients.DEFAULT_TIMEOUT


def test_postgres_engine_uses_config_uri(config):
    engine = clients.make_postgres_engine(config.postgres)

    assert engine.url.host == "postgres"
    assert engine.url.database == "postgres"
    assert engine.url.username == "postgres"


def test_s3_client_points_at_floci_with_path_style(config):
    client = clients.make_s3_client(config.s3)

    assert client.meta.endpoint_url == "http://floci:4566"
    assert client.meta.region_name == "us-east-1"
    assert client.meta.config.s3["addressing_style"] == "path"


def test_kafka_admin_receives_bootstrap_servers(config, monkeypatch):
    captured = {}
    monkeypatch.setattr(
        "confluent_kafka.admin.AdminClient", lambda conf: captured.update(conf) or "admin"
    )

    assert clients.make_kafka_admin(config.kafka) == "admin"
    assert captured["bootstrap.servers"] == "kafka:9092"


def test_kafka_producer_receives_bootstrap_servers(config, monkeypatch):
    captured = {}
    monkeypatch.setattr(
        "confluent_kafka.Producer", lambda conf: captured.update(conf) or "producer"
    )

    assert clients.make_kafka_producer(config.kafka) == "producer"
    assert captured["bootstrap.servers"] == "kafka:9092"


def test_kafka_consumer_enables_partition_eof(config, monkeypatch):
    """Without enable.partition.eof the consume loop can never detect a drained topic."""
    captured = {}
    monkeypatch.setattr(
        "confluent_kafka.Consumer", lambda conf: captured.update(conf) or "consumer"
    )

    assert clients.make_kafka_consumer(config.kafka, group_id="g1") == "consumer"
    assert captured["enable.partition.eof"] is True
    assert captured["group.id"] == "g1"
    assert captured["auto.offset.reset"] == "earliest"


def test_hasura_request_kwargs(config):
    kwargs = clients.hasura_request_kwargs(config.hasura)

    assert kwargs["headers"] == {"x-hasura-admin-secret": "topsecret"}
    assert kwargs["timeout"] == clients.DEFAULT_TIMEOUT


def test_hasura_request_kwargs_custom_timeout(config):
    assert clients.hasura_request_kwargs(config.hasura, timeout=30)["timeout"] == 30


@pytest.mark.parametrize(
    "factory",
    [
        clients.make_valkey_client,
        clients.make_postgres_engine,
        clients.make_s3_client,
    ],
)
def test_factories_do_not_connect_eagerly(factory, config):
    """Constructing a client must not perform I/O, or the dashboard blocks on import."""
    mapping = {
        clients.make_valkey_client: config.valkey,
        clients.make_postgres_engine: config.postgres,
        clients.make_s3_client: config.s3,
    }
    assert factory(mapping[factory]) is not None
