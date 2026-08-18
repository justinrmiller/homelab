from __future__ import annotations

import pytest

from dashboard.config import (
    GrafanaConfig,
    HasuraConfig,
    PostgresConfig,
    SchemaRegistryConfig,
    _env,
    _env_int,
    load_config,
)


def test_defaults_when_environment_is_empty(clean_env):
    config = load_config()

    assert config.valkey.host == "localhost"
    assert config.valkey.port == 6379
    assert config.kafka.bootstrap_servers == "localhost:9092"
    assert config.schema_registry.host == "localhost"
    assert config.schema_registry.port == 8081
    assert config.postgres.host == "localhost"
    assert config.grafana.host == "localhost"
    assert config.grafana.port == 3000
    assert config.grafana.public_url == "http://localhost:3000"
    assert config.hasura.port == 8080
    assert config.s3.endpoint_url == "http://localhost:4566"
    assert config.s3.region == "us-east-1"


def test_environment_overrides_defaults(clean_env):
    clean_env.setenv("VALKEY_HOST", "valkey")
    clean_env.setenv("VALKEY_PORT", "16379")
    clean_env.setenv("AWS_ENDPOINT_URL", "http://floci:4566")
    clean_env.setenv("HASURA_GRAPHQL_ADMIN_SECRET", "shh")

    config = load_config()

    assert config.valkey.host == "valkey"
    assert config.valkey.port == 16379
    assert config.s3.endpoint_url == "http://floci:4566"
    assert config.hasura.admin_secret == "shh"


def test_empty_string_falls_back_to_default(clean_env):
    """Compose passes unset variables through as empty strings."""
    clean_env.setenv("VALKEY_HOST", "")
    clean_env.setenv("VALKEY_PORT", "")

    config = load_config()

    assert config.valkey.host == "localhost"
    assert config.valkey.port == 6379


def test_env_helpers_direct(clean_env):
    clean_env.setenv("SOME_VALUE", "abc")
    assert _env("SOME_VALUE", "fallback") == "abc"
    assert _env("MISSING_VALUE", "fallback") == "fallback"
    assert _env_int("MISSING_INT", 7) == 7


def test_non_integer_port_raises_a_clear_error(clean_env):
    clean_env.setenv("POSTGRES_PORT", "not-a-port")

    with pytest.raises(ValueError, match="POSTGRES_PORT must be an integer"):
        load_config()


def test_postgres_uri():
    cfg = PostgresConfig(host="postgres", port=5432, user="app", password="pw", database="homelab")
    assert cfg.uri == "postgresql://app:pw@postgres:5432/homelab"


def test_schema_registry_base_url():
    cfg = SchemaRegistryConfig(host="schema-registry", port=8081)
    assert cfg.base_url == "http://schema-registry:8081"


def test_hasura_urls_and_headers():
    cfg = HasuraConfig(host="hasura", port=8080, admin_secret="shh")

    assert cfg.base_url == "http://hasura:8080"
    assert cfg.graphql_url == "http://hasura:8080/v1/graphql"
    assert cfg.health_url == "http://hasura:8080/healthz"
    assert cfg.headers == {"x-hasura-admin-secret": "shh"}


def test_hasura_headers_empty_without_secret():
    cfg = HasuraConfig(host="hasura", port=8080, admin_secret="")
    assert cfg.headers == {}


def test_grafana_urls():
    cfg = GrafanaConfig(host="grafana", port=3000, public_url="http://localhost:3000")

    assert cfg.base_url == "http://grafana:3000"
    assert cfg.health_url == "http://grafana:3000/api/health"


def test_grafana_public_url_is_independent_of_host_and_port(clean_env):
    """The browser cannot resolve the compose hostname the health check uses."""
    clean_env.setenv("GRAFANA_HOST", "grafana")
    clean_env.setenv("GRAFANA_PORT", "3000")
    clean_env.setenv("GRAFANA_PUBLIC_URL", "https://grafana.homelab.lan")

    grafana = load_config().grafana

    assert grafana.health_url == "http://grafana:3000/api/health"
    assert grafana.public_url == "https://grafana.homelab.lan"
