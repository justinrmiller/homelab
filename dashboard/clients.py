"""Client factories for each backing service.

Plain functions with no Streamlit dependency so they can be constructed in
tests; ``app.py`` wraps them in ``st.cache_resource`` for the UI.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from dashboard.config import (
        HasuraConfig,
        KafkaConfig,
        PostgresConfig,
        S3Config,
        SchemaRegistryConfig,
        ValkeyConfig,
    )

# Number of seconds to wait on any initial connection before declaring failure.
DEFAULT_TIMEOUT = 5


def make_valkey_client(cfg: ValkeyConfig, timeout: int = DEFAULT_TIMEOUT) -> Any:
    import valkey

    return valkey.Valkey(host=cfg.host, port=cfg.port, socket_timeout=timeout)


def make_kafka_admin(cfg: KafkaConfig) -> Any:
    from confluent_kafka.admin import AdminClient

    return AdminClient({"bootstrap.servers": cfg.bootstrap_servers})


def make_kafka_consumer(cfg: KafkaConfig, group_id: str) -> Any:
    from confluent_kafka import Consumer

    return Consumer(
        {
            "bootstrap.servers": cfg.bootstrap_servers,
            "group.id": group_id,
            "auto.offset.reset": "earliest",
            # Required for the consume loop to learn it has drained a partition
            # instead of silently polling until it times out.
            "enable.partition.eof": True,
        }
    )


def make_kafka_producer(cfg: KafkaConfig) -> Any:
    from confluent_kafka import Producer

    return Producer({"bootstrap.servers": cfg.bootstrap_servers})


def make_schema_registry_client(cfg: SchemaRegistryConfig) -> Any:
    from dashboard.schema_registry import SchemaRegistryClient

    return SchemaRegistryClient(cfg.base_url, timeout=DEFAULT_TIMEOUT)


def make_postgres_engine(cfg: PostgresConfig) -> Any:
    from sqlalchemy import create_engine

    return create_engine(cfg.uri, pool_pre_ping=True)


def make_s3_client(cfg: S3Config) -> Any:
    import boto3
    from botocore.config import Config as BotoConfig

    return boto3.client(
        "s3",
        endpoint_url=cfg.endpoint_url,
        region_name=cfg.region,
        aws_access_key_id=cfg.access_key,
        aws_secret_access_key=cfg.secret_key,
        # Floci serves path-style addressing at the container endpoint;
        # virtual-host style needs the localhost.floci.io DNS shim.
        config=BotoConfig(s3={"addressing_style": "path"}),
    )


def hasura_request_kwargs(cfg: HasuraConfig, timeout: int = DEFAULT_TIMEOUT) -> dict[str, Any]:
    return {"headers": cfg.headers, "timeout": timeout}
