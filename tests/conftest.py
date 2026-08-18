"""Shared fixtures and fakes.

The dashboard talks to every service in the compose stack; these fakes stand in
for them so the suite runs with no containers up.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

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

SERVICE_ENV_VARS = [
    "VALKEY_HOST",
    "VALKEY_PORT",
    "KAFKA_BOOTSTRAP_SERVERS",
    "SCHEMA_REGISTRY_HOST",
    "SCHEMA_REGISTRY_PORT",
    "POSTGRES_HOST",
    "POSTGRES_PORT",
    "POSTGRES_USER",
    "POSTGRES_PASSWORD",
    "POSTGRES_DB",
    "GRAFANA_HOST",
    "GRAFANA_PORT",
    "GRAFANA_PUBLIC_URL",
    "HASURA_HOST",
    "HASURA_PORT",
    "HASURA_GRAPHQL_ADMIN_SECRET",
    "AWS_ENDPOINT_URL",
    "AWS_DEFAULT_REGION",
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
]


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    """Remove every service env var so defaults are observable."""
    for name in SERVICE_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


@pytest.fixture
def config() -> Config:
    return Config(
        valkey=ValkeyConfig(host="valkey", port=6379),
        kafka=KafkaConfig(bootstrap_servers="kafka:9092"),
        schema_registry=SchemaRegistryConfig(host="schema-registry", port=8081),
        postgres=PostgresConfig(
            host="postgres",
            port=5432,
            user="postgres",
            password="secret",
            database="postgres",
        ),
        grafana=GrafanaConfig(host="grafana", port=3000, public_url="http://localhost:3000"),
        hasura=HasuraConfig(host="hasura", port=8080, admin_secret="topsecret"),
        s3=S3Config(
            endpoint_url="http://floci:4566",
            region="us-east-1",
            access_key="test",
            secret_key="test",
        ),
    )


class FakeS3Client:
    """In-memory stand-in for the subset of the boto3 S3 client we use."""

    def __init__(self, buckets: dict[str, dict[str, bytes]] | None = None) -> None:
        self.buckets: dict[str, dict[str, bytes]] = buckets if buckets is not None else {}
        self.created_with: list[dict] = []

    def list_buckets(self) -> dict:
        return {"Buckets": [{"Name": name} for name in self.buckets]}

    def create_bucket(self, **kwargs) -> dict:
        self.created_with.append(kwargs)
        self.buckets.setdefault(kwargs["Bucket"], {})
        return {}

    def delete_bucket(self, Bucket: str) -> dict:  # noqa: N803 - boto3 casing
        del self.buckets[Bucket]
        return {}

    def list_objects_v2(self, Bucket: str, Prefix: str = "", MaxKeys: int = 1000) -> dict:  # noqa: N803
        items = [
            {
                "Key": key,
                "Size": len(body),
                "LastModified": datetime(2026, 1, 1, tzinfo=UTC),
            }
            for key, body in self.buckets[Bucket].items()
            if key.startswith(Prefix)
        ]
        return {"Contents": items[:MaxKeys]} if items else {}

    def put_object(self, Bucket: str, Key: str, Body: bytes) -> dict:  # noqa: N803
        self.buckets[Bucket][Key] = Body
        return {}

    def get_object(self, Bucket: str, Key: str) -> dict:  # noqa: N803
        class _Body:
            def __init__(self, data: bytes) -> None:
                self._data = data

            def read(self) -> bytes:
                return self._data

        return {"Body": _Body(self.buckets[Bucket][Key])}

    def delete_object(self, Bucket: str, Key: str) -> dict:  # noqa: N803
        self.buckets[Bucket].pop(Key, None)
        return {}

    def generate_presigned_url(self, operation: str, Params: dict, ExpiresIn: int) -> str:  # noqa: N803
        return (
            f"http://floci:4566/{Params['Bucket']}/{Params['Key']}"
            f"?op={operation}&X-Amz-Expires={ExpiresIn}"
        )


@pytest.fixture
def fake_s3() -> FakeS3Client:
    return FakeS3Client({"alpha": {"a.txt": b"hello", "logs/b.txt": b"world"}, "beta": {}})
