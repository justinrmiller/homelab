"""Connection checks for each service.

Every check takes an injectable factory so tests can exercise the success,
failure and exception paths without a live backend.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from dashboard import clients
from dashboard.config import (
    Config,
    GrafanaConfig,
    HasuraConfig,
    KafkaConfig,
    PostgresConfig,
    S3Config,
    SchemaRegistryConfig,
    ValkeyConfig,
)

CONNECTED = "🟢"
ERROR = "🔴"
WARNING = "🟠"


@dataclass(frozen=True)
class HealthResult:
    ok: bool
    message: str

    @property
    def indicator(self) -> str:
        return CONNECTED if self.ok else ERROR


def check_valkey(
    cfg: ValkeyConfig,
    factory: Callable[[ValkeyConfig], Any] = clients.make_valkey_client,
) -> HealthResult:
    try:
        if factory(cfg).ping():
            return HealthResult(True, "Connected successfully")
        return HealthResult(False, "Failed to ping server")
    except Exception as exc:
        return HealthResult(False, f"Connection error: {exc}")


def check_kafka(
    cfg: KafkaConfig,
    factory: Callable[[KafkaConfig], Any] = clients.make_kafka_admin,
) -> HealthResult:
    try:
        metadata = factory(cfg).list_topics(timeout=clients.DEFAULT_TIMEOUT)
        return HealthResult(True, f"Connected successfully. Brokers: {len(metadata.brokers)}")
    except Exception as exc:
        return HealthResult(False, f"Connection error: {exc}")


def check_schema_registry(
    cfg: SchemaRegistryConfig,
    factory: Callable[[SchemaRegistryConfig], Any] = clients.make_schema_registry_client,
) -> HealthResult:
    try:
        subjects = factory(cfg).list_subjects()
        return HealthResult(True, f"Connected successfully. Subjects: {len(subjects)}")
    except Exception as exc:
        return HealthResult(False, f"Connection error: {exc}")


def check_postgres(
    cfg: PostgresConfig,
    factory: Callable[[PostgresConfig], Any] = clients.make_postgres_engine,
) -> HealthResult:
    from sqlalchemy import text

    try:
        engine = factory(cfg)
        with engine.connect() as conn:
            version = conn.execute(text("SELECT version();")).scalar()
        return HealthResult(True, f"Connected successfully. {version}")
    except Exception as exc:
        return HealthResult(False, f"Connection error: {exc}")


def check_grafana(
    cfg: GrafanaConfig,
    getter: Callable[..., Any] | None = None,
) -> HealthResult:
    if getter is None:
        import requests

        getter = requests.get
    try:
        resp = getter(cfg.health_url, timeout=clients.DEFAULT_TIMEOUT)
        if resp.status_code != 200:
            return HealthResult(False, f"Healthcheck failed: {resp.status_code}")
        # /api/health needs no auth and reports the state of Grafana's own
        # database, which can be broken while the HTTP server still answers.
        body = resp.json()
        database = body.get("database", "unknown")
        if database != "ok":
            return HealthResult(False, f"Database: {database}")
        return HealthResult(True, f"Connected successfully. Version: {body.get('version', '?')}")
    except Exception as exc:
        return HealthResult(False, f"Connection error: {exc}")


def check_hasura(
    cfg: HasuraConfig,
    getter: Callable[..., Any] | None = None,
) -> HealthResult:
    if getter is None:
        import requests

        getter = requests.get
    try:
        resp = getter(cfg.health_url, **clients.hasura_request_kwargs(cfg))
        if resp.status_code == 200:
            return HealthResult(True, "Connected successfully")
        return HealthResult(False, f"Healthcheck failed: {resp.status_code}")
    except Exception as exc:
        return HealthResult(False, f"Connection error: {exc}")


def check_s3(
    cfg: S3Config,
    factory: Callable[[S3Config], Any] = clients.make_s3_client,
) -> HealthResult:
    try:
        buckets = factory(cfg).list_buckets().get("Buckets", [])
        return HealthResult(True, f"Connected successfully. Buckets: {len(buckets)}")
    except Exception as exc:
        return HealthResult(False, f"Connection error: {exc}")


def check_all(config: Config) -> dict[str, HealthResult]:
    """Run every check and return results keyed by display name."""
    return {
        "Valkey": check_valkey(config.valkey),
        "Kafka": check_kafka(config.kafka),
        "Schema Registry": check_schema_registry(config.schema_registry),
        "PostgreSQL": check_postgres(config.postgres),
        "Grafana": check_grafana(config.grafana),
        "Hasura": check_hasura(config.hasura),
        "S3 (Floci)": check_s3(config.s3),
    }
