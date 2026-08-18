#!/usr/bin/env python3
"""Streamlit dashboard for the local Valkey, Kafka, PostgreSQL, Hasura and S3 services."""

from __future__ import annotations

import json
import random
from datetime import datetime

import pandas as pd
import plotly.express as px
import requests
import streamlit as st
from sqlalchemy import text

from dashboard import clients, health, s3
from dashboard.config import app_version, load_config
from dashboard.sql import is_read_only, safe_identifier

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # pragma: no cover - dotenv is optional at runtime
    pass

st.set_page_config(
    page_title="Homelab Services Dashboard",
    page_icon="🏡",
    layout="wide",
    initial_sidebar_state="expanded",
)

CONFIG = load_config()

DOCS = {
    "Valkey": ("Redis-compatible in-memory database", "https://valkey.io/docs/"),
    "Kafka": (
        "Distributed event streaming platform",
        "https://docs.confluent.io/platform/current/kafka/introduction.html",
    ),
    "Schema Registry": (
        "Schema storage and compatibility for Kafka",
        "https://docs.confluent.io/platform/current/schema-registry/index.html",
    ),
    "PostgreSQL": (
        "Advanced open-source relational database",
        "https://www.postgresql.org/docs/18/index.html",
    ),
    "Grafana": (
        "Dashboards over PostgreSQL, provisioned from files",
        "https://grafana.com/docs/grafana/latest/",
    ),
    "Hasura": ("Instant GraphQL on PostgreSQL", "https://hasura.io/docs/latest/"),
    "S3 (Floci)": ("Local AWS emulator", "https://floci.io/floci/services/s3/"),
}

# Services with a UI of their own, linked from the overview. Grafana is driven
# entirely from its own interface, so it gets a link rather than a page here.
SERVICE_URLS = {"Grafana": CONFIG.grafana.public_url}


# --- Cached clients -------------------------------------------------------
# Without caching, every widget interaction reopens every connection.


@st.cache_resource
def valkey_client():
    return clients.make_valkey_client(CONFIG.valkey)


@st.cache_resource
def kafka_admin():
    return clients.make_kafka_admin(CONFIG.kafka)


@st.cache_resource
def schema_registry_client():
    return clients.make_schema_registry_client(CONFIG.schema_registry)


@st.cache_resource
def postgres_engine():
    return clients.make_postgres_engine(CONFIG.postgres)


@st.cache_resource
def s3_client():
    return clients.make_s3_client(CONFIG.s3)


def show_status(result: health.HealthResult, service: str) -> bool:
    st.write(f"Connection Status: {result.indicator} {result.message}")
    if not result.ok:
        st.error(f"Cannot connect to {service}. Check that the service is running.")
    return result.ok


# --- Overview -------------------------------------------------------------


def show_overview() -> None:
    st.title("Homelab Services Overview")

    results = health.check_all(CONFIG)
    status_df = pd.DataFrame(
        {
            "Service": list(results),
            "Status": [r.indicator for r in results.values()],
            "Message": [r.message for r in results.values()],
        }
    )
    st.dataframe(status_df, hide_index=True, width="stretch")
    st.write(f"Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    if st.button("Refresh"):
        st.rerun()

    st.subheader("Services")
    for name, (blurb, url) in DOCS.items():
        line = f"- **{name}** — {blurb} · [docs]({url})"
        service_url = SERVICE_URLS.get(name)
        if service_url:
            line += f" · [open]({service_url})"
        st.markdown(line)


# --- Valkey ---------------------------------------------------------------


def interact_with_valkey() -> None:
    st.title("Valkey Dashboard")
    if not show_status(health.check_valkey(CONFIG.valkey), "Valkey"):
        return

    client = valkey_client()

    with st.expander("Server Information"):
        st.json(client.info())

    st.subheader("Key Management")
    col1, col2 = st.columns(2)

    with col1:
        st.write("Set a key-value pair")
        key_name = st.text_input("Key Name", "test-key")
        value = st.text_input("Value", "test-value")
        if st.button("Set Key"):
            client.set(key_name, value)
            st.success(f"Set {key_name} = {value}")

    with col2:
        st.write("Get a key value")
        get_key = st.text_input("Key to Get", "test-key")
        if st.button("Get Key"):
            val = client.get(get_key)
            if val:
                st.success(f"Value: {val.decode('utf-8')}")
            else:
                st.warning(f"Key '{get_key}' not found")

    if st.button("List All Keys"):
        keys = client.keys("*")
        if keys:
            st.write("Keys in database:")
            for k in keys:
                st.write(f"- {k.decode('utf-8')}")
        else:
            st.info("No keys found in the database")


# --- Kafka ----------------------------------------------------------------


def interact_with_kafka() -> None:
    st.title("Kafka Dashboard")
    if not show_status(health.check_kafka(CONFIG.kafka), "Kafka"):
        return

    admin = kafka_admin()

    st.subheader("Topic Management")
    if st.button("List All Topics"):
        try:
            topics = sorted(admin.list_topics(timeout=10).topics)
            if topics:
                st.write("Available topics:")
                for topic in topics:
                    st.write(f"- {topic}")
            else:
                st.info("No topics found")
        except Exception as exc:
            st.error(f"Error listing topics: {exc}")

    st.write("Create a new topic")
    topic_name = st.text_input("Topic Name", "test-topic")
    num_partitions = st.number_input("Number of Partitions", min_value=1, value=1)
    replication_factor = st.number_input("Replication Factor", min_value=1, max_value=3, value=1)

    if st.button("Create Topic"):
        from confluent_kafka.admin import NewTopic

        try:
            futures = admin.create_topics(
                [NewTopic(topic_name, int(num_partitions), int(replication_factor))]
            )
            # create_topics is async; resolving the future surfaces real errors
            # such as "topic already exists" instead of silently succeeding.
            futures[topic_name].result()
            st.success(f"Topic '{topic_name}' created successfully")
        except Exception as exc:
            st.error(f"Error creating topic: {exc}")

    st.subheader("Produce Message")
    prod_topic = st.text_input("Topic for Production", "test-topic")
    message_key = st.text_input("Message Key (optional)")
    message_value = st.text_area("Message Value (JSON)", '{"message": "test"}')

    if st.button("Produce Message"):
        try:
            producer = clients.make_kafka_producer(CONFIG.kafka)
            producer.produce(
                prod_topic,
                key=message_key.encode("utf-8") if message_key else None,
                value=message_value.encode("utf-8"),
            )
            remaining = producer.flush(timeout=10)
            if remaining:
                st.error(f"{remaining} message(s) failed to deliver")
            else:
                st.success(f"Message delivered to '{prod_topic}'")
        except Exception as exc:
            st.error(f"Error producing message: {exc}")

    st.subheader("Consume Messages")
    cons_topic = st.text_input("Topic for Consumption", "test-topic")
    num_messages = st.number_input("Number of Messages to Consume", min_value=1, value=5)

    if st.button("Consume Messages"):
        consumer = None
        try:
            from confluent_kafka import KafkaError

            consumer = clients.make_kafka_consumer(
                CONFIG.kafka, group_id=f"streamlit-consumer-{random.randint(1, 10000)}"
            )
            consumer.subscribe([cons_topic])

            messages: list[dict] = []
            attempts = 0
            while len(messages) < num_messages and attempts < 30:
                msg = consumer.poll(timeout=1.0)
                attempts += 1
                if msg is None:
                    continue
                if msg.error():
                    if msg.error().code() == KafkaError._PARTITION_EOF:
                        st.info(f"Reached end of partition for '{cons_topic}'")
                        break
                    st.error(f"Consumer error: {msg.error()}")
                    break

                key = msg.key().decode("utf-8") if msg.key() else None
                raw = msg.value().decode("utf-8")
                try:
                    value = json.loads(raw)
                except json.JSONDecodeError:
                    value = raw
                messages.append(
                    {
                        "partition": msg.partition(),
                        "offset": msg.offset(),
                        "key": key,
                        "value": value,
                    }
                )

            if messages:
                st.write(f"Consumed {len(messages)} messages:")
                st.json(messages)
            else:
                st.info(f"No messages available in topic '{cons_topic}'")
        except Exception as exc:
            st.error(f"Error consuming messages: {exc}")
        finally:
            if consumer is not None:
                consumer.close()


# --- Schema Registry ------------------------------------------------------

SAMPLE_AVRO_SCHEMA = json.dumps(
    {
        "type": "record",
        "name": "User",
        "fields": [
            {"name": "id", "type": "int"},
            {"name": "name", "type": "string"},
        ],
    },
    indent=2,
)


def interact_with_schema_registry() -> None:
    st.title("Schema Registry Dashboard")
    if not show_status(health.check_schema_registry(CONFIG.schema_registry), "Schema Registry"):
        return

    client = schema_registry_client()

    try:
        level = client.compatibility_level()
        st.caption(f"Global compatibility level: **{level}**")
    except Exception as exc:
        st.warning(f"Could not read compatibility level: {exc}")

    st.subheader("Subjects")
    try:
        subjects = client.list_subjects()
    except Exception as exc:
        st.error(f"Error listing subjects: {exc}")
        return

    if subjects:
        for subject in subjects:
            st.write(f"- {subject}")
    else:
        st.info("No subjects registered yet. Register one below.")

    if subjects:
        st.subheader("Inspect Schema")
        subject = st.selectbox("Subject", subjects, key="sr_subject")
        try:
            versions = client.list_versions(subject)
        except Exception as exc:
            st.error(f"Error listing versions: {exc}")
            versions = []

        if versions:
            version = st.selectbox("Version", versions, key="sr_version")
            if st.button("View Schema"):
                try:
                    detail = client.get_version(subject, version)
                    st.write(f"Schema ID **{detail.schema_id}** · type **{detail.schema_type}**")
                    st.code(detail.pretty_schema(), language="json")
                except Exception as exc:
                    st.error(f"Error fetching schema: {exc}")

        if st.button("Delete Subject"):
            try:
                deleted = client.delete_subject(subject)
                st.success(f"Deleted subject '{subject}' (versions: {deleted})")
                st.rerun()
            except Exception as exc:
                st.error(f"Error deleting subject: {exc}")

    st.subheader("Register Schema")
    new_subject = st.text_input("Subject Name", "test-topic-value")
    schema_text = st.text_area("Schema (Avro JSON)", SAMPLE_AVRO_SCHEMA, height=200)
    if st.button("Register Schema"):
        try:
            schema_id = client.register_schema(new_subject, schema_text)
            st.success(f"Registered schema for '{new_subject}' with ID {schema_id}")
            st.rerun()
        except Exception as exc:
            st.error(f"Error registering schema: {exc}")


# --- PostgreSQL -----------------------------------------------------------


def interact_with_postgres() -> None:
    st.title("PostgreSQL Dashboard")
    if not show_status(health.check_postgres(CONFIG.postgres), "PostgreSQL"):
        return

    engine = postgres_engine()

    st.subheader("Database Management")
    if st.button("List Databases"):
        try:
            with engine.connect() as conn:
                rows = conn.execute(
                    text("SELECT datname FROM pg_database WHERE datistemplate = false;")
                )
                for db in [row[0] for row in rows]:
                    st.write(f"- {db}")
        except Exception as exc:
            st.error(f"Error listing databases: {exc}")

    st.subheader("Table Management")
    if st.button("List Tables"):
        try:
            with engine.connect() as conn:
                rows = conn.execute(
                    text(
                        "SELECT tablename FROM pg_catalog.pg_tables "
                        "WHERE schemaname NOT IN ('pg_catalog', 'information_schema');"
                    )
                )
                tables = [row[0] for row in rows]
            if tables:
                st.write("Available tables:")
                for table in tables:
                    st.write(f"- {table}")
            else:
                st.info("No tables found in the current database")
        except Exception as exc:
            st.error(f"Error listing tables: {exc}")

    st.write("Create a new table")
    table_name = st.text_input("Table Name", "test_table")
    if st.button("Create Test Table"):
        try:
            table = safe_identifier(table_name)
            with engine.begin() as conn:
                conn.execute(
                    text(
                        f"CREATE TABLE IF NOT EXISTS {table} ("
                        "id SERIAL PRIMARY KEY, "
                        "name VARCHAR(100), "
                        "value INTEGER, "
                        "created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);"
                    )
                )
            st.success(f"Table '{table}' created successfully")
        except Exception as exc:
            st.error(f"Error creating table: {exc}")

    st.subheader("Insert Data")
    insert_table = st.text_input("Table for Insertion", "test_table")
    col1, col2 = st.columns(2)
    with col1:
        name_value = st.text_input("Name", "Test Name")
    with col2:
        number_value = st.number_input("Value", value=42)

    if st.button("Insert Row"):
        try:
            table = safe_identifier(insert_table)
            with engine.begin() as conn:
                conn.execute(
                    text(f"INSERT INTO {table} (name, value) VALUES (:name, :value)"),
                    {"name": name_value, "value": int(number_value)},
                )
            st.success(f"Data inserted into '{table}' successfully")
        except Exception as exc:
            st.error(f"Error inserting data: {exc}")

    st.subheader("Query Data")
    query_table = st.text_input("Table to Query", "test_table")
    if st.button("Query Table"):
        try:
            table = safe_identifier(query_table)
            df = pd.read_sql(f"SELECT * FROM {table} ORDER BY id DESC LIMIT 10", engine)
            if df.empty:
                st.info(f"No data found in table '{table}'")
            else:
                st.write(f"Data from '{table}':")
                st.dataframe(df, width="stretch")
                if "value" in df.columns and "name" in df.columns:
                    st.plotly_chart(px.bar(df, x="name", y="value", title=f"Values from {table}"))
        except Exception as exc:
            st.error(f"Error querying data: {exc}")

    st.subheader("Execute Custom SQL")
    st.caption("This console runs arbitrary SQL against the database. Handle with care.")
    sql_query = st.text_area("SQL Query", "SELECT version();")
    if st.button("Execute SQL"):
        try:
            if is_read_only(sql_query):
                st.dataframe(pd.read_sql(sql_query, engine), width="stretch")
            else:
                with engine.begin() as conn:
                    conn.execute(text(sql_query))
                st.success("Query executed successfully")
        except Exception as exc:
            st.error(f"Error executing SQL: {exc}")


# --- Hasura ---------------------------------------------------------------


def interact_with_hasura() -> None:
    st.title("Hasura Dashboard")
    if not show_status(health.check_hasura(CONFIG.hasura), "Hasura"):
        return

    if not CONFIG.hasura.admin_secret:
        st.warning(
            "Hasura has no admin secret set. Anyone who can reach this port has "
            "full GraphQL read/write access to PostgreSQL."
        )

    st.subheader("GraphQL Query")
    default_query = "{\n  __schema {\n    queryType { name }\n  }\n}"
    graphql_query = st.text_area("GraphQL Query", default_query, height=150)
    variables = st.text_area("Variables (JSON)", "{}", height=68)

    if st.button("Execute GraphQL Query"):
        try:
            payload = {
                "query": graphql_query,
                "variables": json.loads(variables or "{}"),
            }
            resp = requests.post(
                CONFIG.hasura.graphql_url,
                json=payload,
                **clients.hasura_request_kwargs(CONFIG.hasura),
            )
            if resp.status_code == 200:
                st.json(resp.json())
            else:
                st.error(f"Query failed: {resp.status_code} {resp.text}")
        except Exception as exc:
            st.error(f"Error executing GraphQL query: {exc}")


# --- S3 (Floci) -----------------------------------------------------------


def interact_with_s3() -> None:
    st.title("S3 Dashboard (Floci)")
    if not show_status(health.check_s3(CONFIG.s3), "Floci"):
        return

    client = s3_client()
    st.caption(f"Endpoint: {CONFIG.s3.endpoint_url} · Region: {CONFIG.s3.region}")

    st.subheader("Buckets")
    try:
        buckets = s3.list_buckets(client)
    except Exception as exc:
        st.error(f"Error listing buckets: {exc}")
        return

    if buckets:
        st.write("Available buckets:")
        for bucket_name in buckets:
            st.write(f"- {bucket_name}")
    else:
        st.info("No buckets yet. Create one below.")

    col1, col2 = st.columns(2)
    with col1:
        new_bucket = st.text_input("New Bucket Name", "test-bucket")
        if st.button("Create Bucket"):
            try:
                s3.create_bucket(client, new_bucket, CONFIG.s3.region)
                st.success(f"Bucket '{new_bucket}' created")
                st.rerun()
            except Exception as exc:
                st.error(f"Error creating bucket: {exc}")
    with col2:
        if buckets:
            drop_bucket = st.selectbox("Delete Bucket", buckets, key="drop_bucket")
            if st.button("Delete Bucket"):
                try:
                    s3.delete_bucket(client, drop_bucket)
                    st.success(f"Bucket '{drop_bucket}' deleted")
                    st.rerun()
                except Exception as exc:
                    st.error(f"Error deleting bucket: {exc}")

    if not buckets:
        return

    st.subheader("Objects")
    bucket = st.selectbox("Bucket", buckets, key="object_bucket")
    prefix = st.text_input("Prefix filter", "")

    try:
        objects = s3.list_objects(client, bucket, prefix)
    except Exception as exc:
        st.error(f"Error listing objects: {exc}")
        return

    if objects:
        st.dataframe(
            pd.DataFrame(
                {
                    "Key": [o.key for o in objects],
                    "Size": [s3.human_size(o.size) for o in objects],
                    "Last Modified": [o.last_modified for o in objects],
                }
            ),
            hide_index=True,
            width="stretch",
        )
    else:
        st.info("No objects match that prefix.")

    st.subheader("Upload")
    upload = st.file_uploader("File to upload")
    key_override = st.text_input("Object key (defaults to filename)", "")
    if st.button("Upload") and upload is not None:
        try:
            key = key_override.strip() or upload.name
            s3.put_object(client, bucket, key, upload.getvalue())
            st.success(f"Uploaded '{key}' to '{bucket}'")
            st.rerun()
        except Exception as exc:
            st.error(f"Error uploading object: {exc}")

    if objects:
        st.subheader("Object Actions")
        keys = [o.key for o in objects]
        selected = st.selectbox("Object", keys, key="object_key")
        col3, col4, col5 = st.columns(3)
        with col3:
            if st.button("Fetch for Download"):
                try:
                    st.download_button(
                        "Save file",
                        data=s3.get_object(client, bucket, selected),
                        file_name=selected.rsplit("/", 1)[-1],
                    )
                except Exception as exc:
                    st.error(f"Error fetching object: {exc}")
        with col4:
            if st.button("Presign URL"):
                try:
                    st.code(s3.presign_url(client, bucket, selected))
                except Exception as exc:
                    st.error(f"Error presigning URL: {exc}")
        with col5:
            if st.button("Delete Object"):
                try:
                    s3.delete_object(client, bucket, selected)
                    st.success(f"Deleted '{selected}'")
                    st.rerun()
                except Exception as exc:
                    st.error(f"Error deleting object: {exc}")


PAGES = {
    "Overview": show_overview,
    "Valkey": interact_with_valkey,
    "Kafka": interact_with_kafka,
    "Schema Registry": interact_with_schema_registry,
    "PostgreSQL": interact_with_postgres,
    "Hasura": interact_with_hasura,
    "S3 (Floci)": interact_with_s3,
}


def main() -> None:
    st.sidebar.title("Services Dashboard")
    choice = st.sidebar.radio("Select Service", list(PAGES))
    PAGES[choice]()
    # A version that lags the repo means the container is running a stale
    # image; rebuild with `make up` (which always builds) or `make build`.
    st.sidebar.caption(f"dashboard v{app_version()}")


main()
