from __future__ import annotations

from types import SimpleNamespace

import pytest

from dashboard import health


class _Boom:
    """Factory that raises, standing in for a service that is down."""

    def __call__(self, cfg):
        raise ConnectionError("connection refused")


# --- Valkey ---------------------------------------------------------------


def test_valkey_connected(config):
    result = health.check_valkey(
        config.valkey, factory=lambda cfg: SimpleNamespace(ping=lambda: True)
    )

    assert result.ok
    assert result.message == "Connected successfully"
    assert result.indicator == health.CONNECTED


def test_valkey_ping_returns_false(config):
    result = health.check_valkey(
        config.valkey, factory=lambda cfg: SimpleNamespace(ping=lambda: False)
    )

    assert not result.ok
    assert result.message == "Failed to ping server"
    assert result.indicator == health.ERROR


def test_valkey_unreachable(config):
    result = health.check_valkey(config.valkey, factory=_Boom())

    assert not result.ok
    assert "connection refused" in result.message


# --- Kafka ----------------------------------------------------------------


def test_kafka_connected(config):
    metadata = SimpleNamespace(brokers={1: object(), 2: object()})
    result = health.check_kafka(
        config.kafka, factory=lambda cfg: SimpleNamespace(list_topics=lambda timeout: metadata)
    )

    assert result.ok
    assert "Brokers: 2" in result.message


def test_kafka_unreachable(config):
    result = health.check_kafka(config.kafka, factory=_Boom())

    assert not result.ok
    assert "Connection error" in result.message


# --- Schema Registry ------------------------------------------------------


def test_schema_registry_connected(config):
    result = health.check_schema_registry(
        config.schema_registry,
        factory=lambda cfg: SimpleNamespace(list_subjects=lambda: ["a", "b", "c"]),
    )

    assert result.ok
    assert "Subjects: 3" in result.message


def test_schema_registry_unreachable(config):
    result = health.check_schema_registry(config.schema_registry, factory=_Boom())

    assert not result.ok
    assert "Connection error" in result.message


# --- PostgreSQL -----------------------------------------------------------


class _FakeConnection:
    def __init__(self, version: str) -> None:
        self._version = version

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, _statement):
        return SimpleNamespace(scalar=lambda: self._version)


def test_postgres_connected(config):
    engine = SimpleNamespace(connect=lambda: _FakeConnection("PostgreSQL 18.4"))
    result = health.check_postgres(config.postgres, factory=lambda cfg: engine)

    assert result.ok
    assert "PostgreSQL 18.4" in result.message


def test_postgres_unreachable(config):
    result = health.check_postgres(config.postgres, factory=_Boom())

    assert not result.ok
    assert "Connection error" in result.message


# --- Grafana --------------------------------------------------------------


def _grafana_response(status_code=200, body=None, json_error=None):
    def json_():
        if json_error is not None:
            raise json_error
        return body

    return SimpleNamespace(status_code=status_code, json=json_)


def test_grafana_connected(config):
    captured = {}

    def getter(url, **kwargs):
        captured["url"] = url
        captured["kwargs"] = kwargs
        return _grafana_response(body={"database": "ok", "version": "13.0.2"})

    result = health.check_grafana(config.grafana, getter=getter)

    assert result.ok
    assert "Version: 13.0.2" in result.message
    # Health is checked over the compose network, not the browser-facing URL.
    assert captured["url"] == "http://grafana:3000/api/health"
    assert captured["kwargs"]["timeout"] == 5


def test_grafana_missing_version_field(config):
    result = health.check_grafana(
        config.grafana, getter=lambda url, **kw: _grafana_response(body={"database": "ok"})
    )

    assert result.ok
    assert "Version: ?" in result.message


def test_grafana_reports_broken_database(config):
    """Grafana answers HTTP 200 even when its own database is failing."""
    result = health.check_grafana(
        config.grafana,
        getter=lambda url, **kw: _grafana_response(body={"database": "failing", "version": "13"}),
    )

    assert not result.ok
    assert result.message == "Database: failing"


def test_grafana_missing_database_field(config):
    result = health.check_grafana(
        config.grafana, getter=lambda url, **kw: _grafana_response(body={"version": "13"})
    )

    assert not result.ok
    assert result.message == "Database: unknown"


def test_grafana_non_200(config):
    result = health.check_grafana(
        config.grafana, getter=lambda url, **kw: _grafana_response(status_code=503)
    )

    assert not result.ok
    assert "503" in result.message


def test_grafana_non_json_body(config):
    """A proxy or wrong port can return 200 with HTML."""
    result = health.check_grafana(
        config.grafana,
        getter=lambda url, **kw: _grafana_response(json_error=ValueError("not json")),
    )

    assert not result.ok
    assert "not json" in result.message


def test_grafana_unreachable(config):
    def getter(url, **kwargs):
        raise TimeoutError("timed out")

    result = health.check_grafana(config.grafana, getter=getter)

    assert not result.ok
    assert "timed out" in result.message


def test_grafana_uses_requests_by_default(config, monkeypatch):
    import requests

    monkeypatch.setattr(
        requests,
        "get",
        lambda url, **kw: _grafana_response(body={"database": "ok", "version": "13.0.2"}),
    )

    assert health.check_grafana(config.grafana).ok


# --- Hasura ---------------------------------------------------------------


def test_hasura_connected(config):
    captured = {}

    def getter(url, **kwargs):
        captured["url"] = url
        captured["kwargs"] = kwargs
        return SimpleNamespace(status_code=200)

    result = health.check_hasura(config.hasura, getter=getter)

    assert result.ok
    assert captured["url"] == "http://hasura:8080/healthz"
    # The admin secret must ride along or a secured Hasura returns 401.
    assert captured["kwargs"]["headers"] == {"x-hasura-admin-secret": "topsecret"}


def test_hasura_non_200(config):
    result = health.check_hasura(
        config.hasura, getter=lambda url, **kw: SimpleNamespace(status_code=503)
    )

    assert not result.ok
    assert "503" in result.message


def test_hasura_unreachable(config):
    def getter(url, **kwargs):
        raise TimeoutError("timed out")

    result = health.check_hasura(config.hasura, getter=getter)

    assert not result.ok
    assert "timed out" in result.message


def test_hasura_uses_requests_by_default(config, monkeypatch):
    import requests

    monkeypatch.setattr(requests, "get", lambda url, **kw: SimpleNamespace(status_code=200))

    assert health.check_hasura(config.hasura).ok


# --- S3 -------------------------------------------------------------------


def test_s3_connected(config, fake_s3):
    result = health.check_s3(config.s3, factory=lambda cfg: fake_s3)

    assert result.ok
    assert "Buckets: 2" in result.message


def test_s3_unreachable(config):
    result = health.check_s3(config.s3, factory=_Boom())

    assert not result.ok
    assert "Connection error" in result.message


# --- Aggregate ------------------------------------------------------------


ALL_CHECKS = (
    "check_valkey",
    "check_kafka",
    "check_schema_registry",
    "check_postgres",
    "check_grafana",
    "check_hasura",
    "check_s3",
)


def test_check_all_reports_every_service(config, monkeypatch):
    ok = health.HealthResult(True, "fine")
    for name in ALL_CHECKS:
        monkeypatch.setattr(health, name, lambda cfg, _ok=ok, **kw: _ok)

    results = health.check_all(config)

    assert set(results) == {
        "Valkey",
        "Kafka",
        "Schema Registry",
        "PostgreSQL",
        "Grafana",
        "Hasura",
        "S3 (Floci)",
    }
    assert all(r.ok for r in results.values())


def test_check_all_surfaces_failures(config, monkeypatch):
    monkeypatch.setattr(
        health, "check_valkey", lambda cfg, **kw: health.HealthResult(False, "down")
    )
    for name in ALL_CHECKS[1:]:
        monkeypatch.setattr(health, name, lambda cfg, **kw: health.HealthResult(True, "fine"))

    results = health.check_all(config)

    assert not results["Valkey"].ok
    assert results["Valkey"].indicator == health.ERROR


@pytest.mark.parametrize(("ok", "expected"), [(True, health.CONNECTED), (False, health.ERROR)])
def test_indicator(ok, expected):
    assert health.HealthResult(ok, "m").indicator == expected
