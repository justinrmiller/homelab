"""Environment-driven configuration for the homelab dashboard.

Config is read through :func:`load_config` rather than at import time so that
tests can vary the environment without reimporting modules.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


def _env(name: str, default: str) -> str:
    value = os.environ.get(name)
    return default if value is None or value == "" else value


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer, got {raw!r}") from exc


@dataclass(frozen=True)
class ValkeyConfig:
    host: str
    port: int


@dataclass(frozen=True)
class KafkaConfig:
    bootstrap_servers: str


@dataclass(frozen=True)
class SchemaRegistryConfig:
    host: str
    port: int

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"


@dataclass(frozen=True)
class PostgresConfig:
    host: str
    port: int
    user: str
    password: str
    database: str

    @property
    def uri(self) -> str:
        return f"postgresql://{self.user}:{self.password}@{self.host}:{self.port}/{self.database}"


@dataclass(frozen=True)
class HasuraConfig:
    host: str
    port: int
    admin_secret: str

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    @property
    def graphql_url(self) -> str:
        return f"{self.base_url}/v1/graphql"

    @property
    def health_url(self) -> str:
        return f"{self.base_url}/healthz"

    @property
    def headers(self) -> dict[str, str]:
        if not self.admin_secret:
            return {}
        return {"x-hasura-admin-secret": self.admin_secret}


@dataclass(frozen=True)
class S3Config:
    """Connection details for the Floci AWS emulator's S3 service."""

    endpoint_url: str
    region: str
    access_key: str
    secret_key: str


@dataclass(frozen=True)
class Config:
    valkey: ValkeyConfig
    kafka: KafkaConfig
    schema_registry: SchemaRegistryConfig
    postgres: PostgresConfig
    hasura: HasuraConfig
    s3: S3Config


def load_config() -> Config:
    """Build a :class:`Config` from the current process environment."""
    return Config(
        valkey=ValkeyConfig(
            host=_env("VALKEY_HOST", "localhost"),
            port=_env_int("VALKEY_PORT", 6379),
        ),
        kafka=KafkaConfig(
            bootstrap_servers=_env("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092"),
        ),
        schema_registry=SchemaRegistryConfig(
            host=_env("SCHEMA_REGISTRY_HOST", "localhost"),
            port=_env_int("SCHEMA_REGISTRY_PORT", 8081),
        ),
        postgres=PostgresConfig(
            host=_env("POSTGRES_HOST", "localhost"),
            port=_env_int("POSTGRES_PORT", 5432),
            user=_env("POSTGRES_USER", "postgres"),
            password=_env("POSTGRES_PASSWORD", "postgres"),
            database=_env("POSTGRES_DB", "postgres"),
        ),
        hasura=HasuraConfig(
            host=_env("HASURA_HOST", "localhost"),
            port=_env_int("HASURA_PORT", 8080),
            admin_secret=_env("HASURA_GRAPHQL_ADMIN_SECRET", ""),
        ),
        s3=S3Config(
            endpoint_url=_env("AWS_ENDPOINT_URL", "http://localhost:4566"),
            region=_env("AWS_DEFAULT_REGION", "us-east-1"),
            access_key=_env("AWS_ACCESS_KEY_ID", "test"),
            secret_key=_env("AWS_SECRET_ACCESS_KEY", "test"),
        ),
    )
