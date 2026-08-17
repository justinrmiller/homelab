"""Exercise the dashboard's button handlers with faked backends.

``test_app.py`` covers page dispatch and status rendering; this module clicks
through the actual operations so the handler bodies are covered too.
"""

from __future__ import annotations

from types import SimpleNamespace

import pandas as pd
import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from dashboard import health

APP_PATH = "dashboard/app.py"


@pytest.fixture(autouse=True)
def _clear_streamlit_caches():
    st.cache_resource.clear()
    yield
    st.cache_resource.clear()


@pytest.fixture(autouse=True)
def _all_healthy(monkeypatch):
    for name in (
        "check_valkey",
        "check_kafka",
        "check_schema_registry",
        "check_postgres",
        "check_hasura",
        "check_s3",
    ):
        monkeypatch.setattr(
            health, name, lambda cfg, **kw: health.HealthResult(True, "Connected successfully")
        )


def open_page(page: str) -> AppTest:
    at = AppTest.from_file(APP_PATH, default_timeout=30).run()
    return at.sidebar.radio[0].set_value(page).run()


def click(at: AppTest, label: str) -> AppTest:
    for button in at.button:
        if button.label == label:
            return button.click().run()
    raise AssertionError(f"no button labelled {label!r}; have {[b.label for b in at.button]}")


def messages(at: AppTest) -> str:
    parts = [m.value for m in at.markdown]
    # st.caption is a separate element type, not folded into markdown.
    parts += [c.value for c in at.caption]
    parts += [s.value for s in at.success]
    parts += [i.value for i in at.info]
    parts += [w.value for w in at.warning]
    parts += [e.value for e in at.error]
    return " ".join(parts)


# --- Valkey ---------------------------------------------------------------


class FakeValkey:
    """Keys are set with str and read back as bytes, matching the real client."""

    def __init__(self, store=None):
        self.store = store if store is not None else {}

    def info(self):
        return {"redis_version": "9.1.1"}

    def set(self, key, value):
        self.store[key] = value.encode() if isinstance(value, str) else value

    def get(self, key):
        return self.store.get(key)

    def keys(self, _pattern):
        return [k.encode() for k in self.store]


@pytest.fixture
def fake_valkey(monkeypatch):
    client = FakeValkey({"existing": b"value"})
    monkeypatch.setattr("dashboard.clients.make_valkey_client", lambda cfg: client)
    return client


def test_valkey_set_key(fake_valkey):
    at = click(open_page("Valkey"), "Set Key")

    assert not at.exception
    assert "Set test-key = test-value" in messages(at)
    assert fake_valkey.store["test-key"] == b"test-value"


def test_valkey_get_missing_key(fake_valkey):
    at = click(open_page("Valkey"), "Get Key")

    assert not at.exception
    assert "not found" in messages(at)


def test_valkey_get_existing_key(fake_valkey):
    at = open_page("Valkey")
    at.text_input[2].set_value("existing").run()
    at = click(at, "Get Key")

    assert not at.exception
    assert "Value: value" in messages(at)


def test_valkey_list_keys(fake_valkey):
    at = click(open_page("Valkey"), "List All Keys")

    assert not at.exception
    assert "existing" in messages(at)


def test_valkey_list_keys_when_empty(monkeypatch):
    monkeypatch.setattr("dashboard.clients.make_valkey_client", lambda cfg: FakeValkey())
    at = click(open_page("Valkey"), "List All Keys")

    assert not at.exception
    assert "No keys found" in messages(at)


# --- Kafka ----------------------------------------------------------------


class FakeAdmin:
    def __init__(self, topics=("test-topic",), fail=False):
        self._topics = {t: object() for t in topics}
        self.fail = fail

    def list_topics(self, timeout=None):
        if self.fail:
            raise RuntimeError("broker unavailable")
        return SimpleNamespace(topics=self._topics, brokers={1: object()})

    def create_topics(self, new_topics):
        name = new_topics[0].topic
        self._topics[name] = object()
        return {name: SimpleNamespace(result=lambda: None)}


@pytest.fixture
def fake_kafka(monkeypatch):
    admin = FakeAdmin()
    monkeypatch.setattr("dashboard.clients.make_kafka_admin", lambda cfg: admin)
    return admin


def test_kafka_list_topics(fake_kafka):
    at = click(open_page("Kafka"), "List All Topics")

    assert not at.exception
    assert "test-topic" in messages(at)


def test_kafka_list_topics_when_empty(monkeypatch):
    monkeypatch.setattr("dashboard.clients.make_kafka_admin", lambda cfg: FakeAdmin(topics=()))
    at = click(open_page("Kafka"), "List All Topics")

    assert not at.exception
    assert "No topics found" in messages(at)


def test_kafka_list_topics_error(monkeypatch):
    monkeypatch.setattr("dashboard.clients.make_kafka_admin", lambda cfg: FakeAdmin(fail=True))
    at = click(open_page("Kafka"), "List All Topics")

    assert not at.exception
    assert "broker unavailable" in messages(at)


def test_kafka_create_topic(fake_kafka):
    at = click(open_page("Kafka"), "Create Topic")

    assert not at.exception
    assert "created successfully" in messages(at)


def test_kafka_create_topic_surfaces_future_errors(fake_kafka, monkeypatch):
    def boom(_new_topics):
        return {"test-topic": SimpleNamespace(result=_raise)}

    def _raise():
        raise RuntimeError("topic already exists")

    monkeypatch.setattr(fake_kafka, "create_topics", boom)
    at = click(open_page("Kafka"), "Create Topic")

    assert not at.exception
    assert "topic already exists" in messages(at)


def test_kafka_produce_message(fake_kafka, monkeypatch):
    produced = []
    producer = SimpleNamespace(
        produce=lambda topic, key, value: produced.append((topic, key, value)),
        flush=lambda timeout: 0,
    )
    monkeypatch.setattr("dashboard.clients.make_kafka_producer", lambda cfg: producer)

    at = click(open_page("Kafka"), "Produce Message")

    assert not at.exception
    assert "Message delivered" in messages(at)
    assert produced[0][0] == "test-topic"


def test_kafka_produce_reports_undelivered(fake_kafka, monkeypatch):
    producer = SimpleNamespace(produce=lambda topic, **kw: None, flush=lambda timeout: 2)
    monkeypatch.setattr("dashboard.clients.make_kafka_producer", lambda cfg: producer)

    at = click(open_page("Kafka"), "Produce Message")

    assert not at.exception
    assert "2 message(s) failed to deliver" in messages(at)


class FakeMessage:
    def __init__(self, value, key=b"k", err=None):
        self._value, self._key, self._err = value, key, err

    def error(self):
        return self._err

    def key(self):
        return self._key

    def value(self):
        return self._value

    def partition(self):
        return 0

    def offset(self):
        return 1


class FakeConsumer:
    def __init__(self, messages):
        self._messages = list(messages)
        self.closed = False

    def subscribe(self, _topics):
        pass

    def poll(self, timeout):
        return self._messages.pop(0) if self._messages else None

    def close(self):
        self.closed = True


def test_kafka_consume_json_and_plain_messages(fake_kafka, monkeypatch):
    consumer = FakeConsumer([FakeMessage(b'{"a": 1}'), FakeMessage(b"plain", key=None)])
    monkeypatch.setattr("dashboard.clients.make_kafka_consumer", lambda cfg, group_id: consumer)

    at = open_page("Kafka")
    at.number_input[2].set_value(2).run()
    at = click(at, "Consume Messages")

    assert not at.exception
    assert "Consumed 2 messages" in messages(at)
    assert consumer.closed, "consumer must be closed even on the happy path"


def test_kafka_consume_empty_topic(fake_kafka, monkeypatch):
    consumer = FakeConsumer([])
    monkeypatch.setattr("dashboard.clients.make_kafka_consumer", lambda cfg, group_id: consumer)

    at = click(open_page("Kafka"), "Consume Messages")

    assert not at.exception
    assert "No messages available" in messages(at)
    assert consumer.closed


def test_kafka_consume_stops_at_partition_eof(fake_kafka, monkeypatch):
    from confluent_kafka import KafkaError

    eof = SimpleNamespace(code=lambda: KafkaError._PARTITION_EOF)
    consumer = FakeConsumer([FakeMessage(b"{}"), FakeMessage(b"", err=eof)])
    monkeypatch.setattr("dashboard.clients.make_kafka_consumer", lambda cfg, group_id: consumer)

    at = open_page("Kafka")
    at.number_input[2].set_value(5).run()
    at = click(at, "Consume Messages")

    assert not at.exception
    assert "Reached end of partition" in messages(at)


def test_kafka_consume_reports_consumer_errors(fake_kafka, monkeypatch):
    err = SimpleNamespace(code=lambda: -1, __str__=lambda self: "bad things")
    consumer = FakeConsumer([FakeMessage(b"", err=err)])
    monkeypatch.setattr("dashboard.clients.make_kafka_consumer", lambda cfg, group_id: consumer)

    at = click(open_page("Kafka"), "Consume Messages")

    assert not at.exception
    assert "Consumer error" in messages(at)


# --- Schema Registry ------------------------------------------------------


class FakeRegistry:
    def __init__(self, subjects=("test-topic-value",), level="BACKWARD"):
        self._subjects = list(subjects)
        self._level = level
        self.registered: list[tuple[str, str]] = []
        self.deleted: list[str] = []

    def compatibility_level(self):
        if self._level is None:
            raise RuntimeError("config unavailable")
        return self._level

    def list_subjects(self):
        return list(self._subjects)

    def list_versions(self, subject):
        return [1, 2]

    def get_version(self, subject, version="latest"):
        from dashboard.schema_registry import SchemaVersion

        return SchemaVersion(
            subject=subject,
            version=int(version),
            schema_id=77,
            schema='{"type":"record","name":"User","fields":[]}',
        )

    def register_schema(self, subject, schema, schema_type="AVRO"):
        self.registered.append((subject, schema))
        return 101

    def delete_subject(self, subject):
        self.deleted.append(subject)
        return [1, 2]


@pytest.fixture
def fake_registry(monkeypatch):
    registry = FakeRegistry()
    monkeypatch.setattr("dashboard.clients.make_schema_registry_client", lambda cfg: registry)
    return registry


def test_schema_registry_lists_subjects_and_level(fake_registry):
    at = open_page("Schema Registry")

    assert not at.exception
    body = messages(at)
    assert "test-topic-value" in body
    assert "BACKWARD" in body


def test_schema_registry_handles_missing_compatibility_level(monkeypatch):
    monkeypatch.setattr(
        "dashboard.clients.make_schema_registry_client",
        lambda cfg: FakeRegistry(level=None),
    )
    at = open_page("Schema Registry")

    assert not at.exception
    assert "Could not read compatibility level" in messages(at)


def test_schema_registry_no_subjects(monkeypatch):
    monkeypatch.setattr(
        "dashboard.clients.make_schema_registry_client",
        lambda cfg: FakeRegistry(subjects=()),
    )
    at = open_page("Schema Registry")

    assert not at.exception
    assert "No subjects registered yet" in messages(at)


def test_schema_registry_list_subjects_error(monkeypatch):
    registry = FakeRegistry()

    def boom():
        raise RuntimeError("registry down")

    monkeypatch.setattr(registry, "list_subjects", boom)
    monkeypatch.setattr("dashboard.clients.make_schema_registry_client", lambda cfg: registry)

    at = open_page("Schema Registry")

    assert not at.exception
    assert "registry down" in messages(at)


def test_schema_registry_view_schema(fake_registry):
    at = click(open_page("Schema Registry"), "View Schema")

    assert not at.exception
    assert any("record" in c.value for c in at.code)
    assert "77" in messages(at)


def test_schema_registry_view_schema_error(fake_registry, monkeypatch):
    def boom(subject, version="latest"):
        raise RuntimeError("schema gone")

    monkeypatch.setattr(fake_registry, "get_version", boom)
    at = click(open_page("Schema Registry"), "View Schema")

    assert not at.exception
    assert "schema gone" in messages(at)


def test_schema_registry_list_versions_error(fake_registry, monkeypatch):
    def boom(subject):
        raise RuntimeError("no versions")

    monkeypatch.setattr(fake_registry, "list_versions", boom)
    at = open_page("Schema Registry")

    assert not at.exception
    assert "no versions" in messages(at)


def test_schema_registry_register_schema(fake_registry):
    at = click(open_page("Schema Registry"), "Register Schema")

    assert not at.exception
    assert fake_registry.registered[0][0] == "test-topic-value"
    assert "101" in messages(at)


def test_schema_registry_register_schema_error(fake_registry, monkeypatch):
    def boom(subject, schema, schema_type="AVRO"):
        raise RuntimeError("incompatible schema")

    monkeypatch.setattr(fake_registry, "register_schema", boom)
    at = click(open_page("Schema Registry"), "Register Schema")

    assert not at.exception
    assert "incompatible schema" in messages(at)


def test_schema_registry_delete_subject(fake_registry):
    at = click(open_page("Schema Registry"), "Delete Subject")

    assert not at.exception
    assert fake_registry.deleted == ["test-topic-value"]


def test_schema_registry_delete_subject_error(fake_registry, monkeypatch):
    def boom(subject):
        raise RuntimeError("subject in use")

    monkeypatch.setattr(fake_registry, "delete_subject", boom)
    at = click(open_page("Schema Registry"), "Delete Subject")

    assert not at.exception
    assert "subject in use" in messages(at)


# --- PostgreSQL -----------------------------------------------------------


class FakeConn:
    def __init__(self, rows, recorder):
        self.rows = rows
        self.recorder = recorder

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, statement, params=None):
        self.recorder.append((str(statement), params))
        return iter(self.rows)


class FakeEngine:
    def __init__(self, rows=(("public_table",),)):
        self.rows = list(rows)
        self.statements: list[tuple[str, dict | None]] = []

    def connect(self):
        return FakeConn(self.rows, self.statements)

    def begin(self):
        return FakeConn(self.rows, self.statements)


@pytest.fixture
def fake_engine(monkeypatch):
    engine = FakeEngine()
    monkeypatch.setattr("dashboard.clients.make_postgres_engine", lambda cfg: engine)
    return engine


def test_postgres_list_databases(fake_engine):
    at = click(open_page("PostgreSQL"), "List Databases")

    assert not at.exception
    assert "public_table" in messages(at)


def test_postgres_list_tables(fake_engine):
    at = click(open_page("PostgreSQL"), "List Tables")

    assert not at.exception
    assert "Available tables" in messages(at)


def test_postgres_list_tables_when_empty(monkeypatch):
    monkeypatch.setattr("dashboard.clients.make_postgres_engine", lambda cfg: FakeEngine(rows=()))
    at = click(open_page("PostgreSQL"), "List Tables")

    assert not at.exception
    assert "No tables found" in messages(at)


def test_postgres_create_table(fake_engine):
    at = click(open_page("PostgreSQL"), "Create Test Table")

    assert not at.exception
    assert "created successfully" in messages(at)
    assert "CREATE TABLE IF NOT EXISTS test_table" in fake_engine.statements[0][0]


def test_postgres_create_table_rejects_bad_identifier(fake_engine):
    at = open_page("PostgreSQL")
    at.text_input[0].set_value("users; DROP TABLE students").run()
    at = click(at, "Create Test Table")

    assert not at.exception
    assert "not a valid table name" in messages(at)
    assert fake_engine.statements == [], "no SQL should reach the database"


def test_postgres_insert_row(fake_engine):
    at = click(open_page("PostgreSQL"), "Insert Row")

    assert not at.exception
    assert "inserted into" in messages(at)
    statement, params = fake_engine.statements[0]
    assert "INSERT INTO test_table" in statement
    assert params == {"name": "Test Name", "value": 42}


def test_postgres_insert_rejects_bad_identifier(fake_engine):
    at = open_page("PostgreSQL")
    at.text_input[1].set_value("bad name").run()
    at = click(at, "Insert Row")

    assert not at.exception
    assert "not a valid table name" in messages(at)


def test_postgres_query_table(fake_engine, monkeypatch):
    frame = pd.DataFrame({"name": ["a", "b"], "value": [1, 2]})
    monkeypatch.setattr(pd, "read_sql", lambda sql, con: frame)

    at = click(open_page("PostgreSQL"), "Query Table")

    assert not at.exception
    assert at.dataframe[0].value["value"].tolist() == [1, 2]


def test_postgres_query_table_empty(fake_engine, monkeypatch):
    monkeypatch.setattr(pd, "read_sql", lambda sql, con: pd.DataFrame())

    at = click(open_page("PostgreSQL"), "Query Table")

    assert not at.exception
    assert "No data found" in messages(at)


def test_postgres_custom_select(fake_engine, monkeypatch):
    monkeypatch.setattr(pd, "read_sql", lambda sql, con: pd.DataFrame({"version": ["18.4"]}))

    at = click(open_page("PostgreSQL"), "Execute SQL")

    assert not at.exception
    assert at.dataframe[0].value["version"].tolist() == ["18.4"]


def test_postgres_custom_write_statement(fake_engine):
    at = open_page("PostgreSQL")
    at.text_area[0].set_value("DELETE FROM test_table").run()
    at = click(at, "Execute SQL")

    assert not at.exception
    assert "executed successfully" in messages(at)
    assert fake_engine.statements[0][0] == "DELETE FROM test_table"


def test_postgres_custom_sql_error(fake_engine, monkeypatch):
    def boom(sql, con):
        raise RuntimeError("syntax error")

    monkeypatch.setattr(pd, "read_sql", boom)
    at = click(open_page("PostgreSQL"), "Execute SQL")

    assert not at.exception
    assert "syntax error" in messages(at)


# --- Hasura ---------------------------------------------------------------


def test_hasura_query_success(monkeypatch):
    captured = {}

    def fake_post(url, json=None, **kwargs):
        captured["url"] = url
        captured["headers"] = kwargs.get("headers")
        return SimpleNamespace(status_code=200, json=lambda: {"data": {"ok": True}})

    monkeypatch.setattr("requests.post", fake_post)
    monkeypatch.setenv("HASURA_GRAPHQL_ADMIN_SECRET", "topsecret")

    at = click(open_page("Hasura"), "Execute GraphQL Query")

    assert not at.exception
    assert captured["url"].endswith("/v1/graphql")
    assert captured["headers"] == {"x-hasura-admin-secret": "topsecret"}


def test_hasura_query_failure(monkeypatch):
    monkeypatch.setattr(
        "requests.post",
        lambda url, json=None, **kw: SimpleNamespace(status_code=400, text="bad query"),
    )

    at = click(open_page("Hasura"), "Execute GraphQL Query")

    assert not at.exception
    assert "bad query" in messages(at)


def test_hasura_query_exception(monkeypatch):
    def boom(url, json=None, **kw):
        raise RuntimeError("network down")

    monkeypatch.setattr("requests.post", boom)

    at = click(open_page("Hasura"), "Execute GraphQL Query")

    assert not at.exception
    assert "network down" in messages(at)


# --- S3 -------------------------------------------------------------------


@pytest.fixture
def s3_page(monkeypatch, fake_s3):
    monkeypatch.setattr("dashboard.clients.make_s3_client", lambda cfg: fake_s3)
    return fake_s3


def test_s3_create_bucket(s3_page):
    at = click(open_page("S3 (Floci)"), "Create Bucket")

    assert not at.exception
    assert "test-bucket" in s3_page.buckets


def test_s3_create_bucket_error(s3_page, monkeypatch):
    def boom(**kwargs):
        raise RuntimeError("bucket already exists")

    monkeypatch.setattr(s3_page, "create_bucket", boom)
    at = click(open_page("S3 (Floci)"), "Create Bucket")

    assert not at.exception
    assert "bucket already exists" in messages(at)


def test_s3_delete_bucket(s3_page):
    at = click(open_page("S3 (Floci)"), "Delete Bucket")

    assert not at.exception
    assert "alpha" not in s3_page.buckets


def test_s3_delete_bucket_error(s3_page, monkeypatch):
    def boom(Bucket):  # noqa: N803
        raise RuntimeError("bucket not empty")

    monkeypatch.setattr(s3_page, "delete_bucket", boom)
    at = click(open_page("S3 (Floci)"), "Delete Bucket")

    assert not at.exception
    assert "bucket not empty" in messages(at)


def test_s3_presign_url(s3_page):
    at = click(open_page("S3 (Floci)"), "Presign URL")

    assert not at.exception
    assert any("X-Amz-Expires" in c.value for c in at.code)


def test_s3_delete_object(s3_page):
    at = click(open_page("S3 (Floci)"), "Delete Object")

    assert not at.exception
    assert "a.txt" not in s3_page.buckets["alpha"]


def test_s3_download_object(s3_page):
    at = click(open_page("S3 (Floci)"), "Fetch for Download")

    assert not at.exception


def test_s3_object_listing_error(s3_page, monkeypatch):
    def boom(**kwargs):
        raise RuntimeError("listing failed")

    monkeypatch.setattr(s3_page, "list_objects_v2", boom)
    at = open_page("S3 (Floci)")

    assert not at.exception
    assert "listing failed" in messages(at)


def test_s3_empty_bucket_shows_prompt(monkeypatch):
    from tests.conftest import FakeS3Client

    monkeypatch.setattr("dashboard.clients.make_s3_client", lambda cfg: FakeS3Client())
    at = open_page("S3 (Floci)")

    assert not at.exception
    assert "No buckets yet" in messages(at)


def test_s3_upload_uses_filename_by_default(s3_page):
    at = open_page("S3 (Floci)")
    at.file_uploader[0].upload("notes.txt", b"file contents").run()
    at = click(at, "Upload")

    assert not at.exception
    assert s3_page.buckets["alpha"]["notes.txt"] == b"file contents"


def test_s3_upload_honours_key_override(s3_page):
    at = open_page("S3 (Floci)")
    at.file_uploader[0].upload("notes.txt", b"file contents").run()
    # text_input[2] is the object-key override on the upload form.
    at.text_input[2].set_value("archive/renamed.txt").run()
    at = click(at, "Upload")

    assert not at.exception
    assert "archive/renamed.txt" in s3_page.buckets["alpha"]
    assert "notes.txt" not in s3_page.buckets["alpha"]


def test_s3_upload_error(s3_page, monkeypatch):
    def boom(**kwargs):
        raise RuntimeError("upload rejected")

    monkeypatch.setattr(s3_page, "put_object", boom)
    at = open_page("S3 (Floci)")
    at.file_uploader[0].upload("notes.txt", b"data").run()
    at = click(at, "Upload")

    assert not at.exception
    assert "upload rejected" in messages(at)


def test_s3_upload_button_without_a_file_is_a_noop(s3_page):
    at = click(open_page("S3 (Floci)"), "Upload")

    assert not at.exception
    assert list(s3_page.buckets["alpha"]) == ["a.txt", "logs/b.txt"]


def test_s3_download_error(s3_page, monkeypatch):
    def boom(**kwargs):
        raise RuntimeError("object vanished")

    monkeypatch.setattr(s3_page, "get_object", boom)
    at = click(open_page("S3 (Floci)"), "Fetch for Download")

    assert not at.exception
    assert "object vanished" in messages(at)


def test_s3_presign_error(s3_page, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("cannot sign")

    monkeypatch.setattr(s3_page, "generate_presigned_url", boom)
    at = click(open_page("S3 (Floci)"), "Presign URL")

    assert not at.exception
    assert "cannot sign" in messages(at)


def test_s3_delete_object_error(s3_page, monkeypatch):
    def boom(**kwargs):
        raise RuntimeError("access denied")

    monkeypatch.setattr(s3_page, "delete_object", boom)
    at = click(open_page("S3 (Floci)"), "Delete Object")

    assert not at.exception
    assert "access denied" in messages(at)


def test_s3_prefix_with_no_matches(s3_page):
    at = open_page("S3 (Floci)")
    # text_input[0] is the new-bucket name, [1] is the prefix filter.
    at.text_input[1].set_value("nothing-matches/").run()

    assert not at.exception
    assert "No objects match that prefix" in messages(at)


# --- Remaining error paths ------------------------------------------------


def test_overview_refresh_button(monkeypatch):
    at = AppTest.from_file(APP_PATH, default_timeout=30).run()
    at = click(at, "Refresh")

    assert not at.exception
    assert at.title[0].value == "Homelab Services Overview"


def test_kafka_produce_error(fake_kafka, monkeypatch):
    def boom(cfg):
        raise RuntimeError("no broker")

    monkeypatch.setattr("dashboard.clients.make_kafka_producer", boom)
    at = click(open_page("Kafka"), "Produce Message")

    assert not at.exception
    assert "no broker" in messages(at)


def test_kafka_consume_error(fake_kafka, monkeypatch):
    def boom(cfg, group_id):
        raise RuntimeError("subscribe failed")

    monkeypatch.setattr("dashboard.clients.make_kafka_consumer", boom)
    at = click(open_page("Kafka"), "Consume Messages")

    assert not at.exception
    assert "subscribe failed" in messages(at)


class BrokenEngine:
    def __init__(self, message="connection lost"):
        self.message = message

    def connect(self):
        raise RuntimeError(self.message)

    def begin(self):
        raise RuntimeError(self.message)


@pytest.fixture
def broken_engine(monkeypatch):
    monkeypatch.setattr("dashboard.clients.make_postgres_engine", lambda cfg: BrokenEngine())


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        ("List Databases", "Error listing databases"),
        ("List Tables", "Error listing tables"),
        ("Create Test Table", "Error creating table"),
        ("Insert Row", "Error inserting data"),
    ],
)
def test_postgres_error_paths(broken_engine, label, expected):
    at = click(open_page("PostgreSQL"), label)

    assert not at.exception
    assert expected in messages(at)


def test_postgres_query_table_error(fake_engine, monkeypatch):
    def boom(sql, con):
        raise RuntimeError("relation does not exist")

    monkeypatch.setattr(pd, "read_sql", boom)
    at = click(open_page("PostgreSQL"), "Query Table")

    assert not at.exception
    assert "relation does not exist" in messages(at)


def test_postgres_query_without_chartable_columns(fake_engine, monkeypatch):
    """The bar chart is only drawn when both name and value columns exist."""
    monkeypatch.setattr(pd, "read_sql", lambda sql, con: pd.DataFrame({"id": [1, 2]}))

    at = click(open_page("PostgreSQL"), "Query Table")

    assert not at.exception
    assert at.dataframe[0].value["id"].tolist() == [1, 2]
