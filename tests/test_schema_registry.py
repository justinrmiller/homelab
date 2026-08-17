from __future__ import annotations

import json

import pytest

from dashboard.schema_registry import (
    CONTENT_TYPE,
    SchemaRegistryClient,
    SchemaRegistryError,
    SchemaVersion,
)

AVRO = '{"type":"record","name":"User","fields":[{"name":"id","type":"int"}]}'


class FakeResponse:
    def __init__(self, status_code=200, body=None, raises=False):
        self.status_code = status_code
        self._body = body
        self._raises = raises

    def json(self):
        if self._raises:
            raise ValueError("not json")
        return self._body


class FakeSession:
    """Records calls and replays queued responses."""

    def __init__(self, responses=None):
        self.responses = dict(responses or {})
        self.calls: list[tuple[str, str, dict]] = []

    def _handle(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        resp = self.responses.get((method, url))
        if resp is None:
            raise AssertionError(f"unexpected {method} {url}; have {list(self.responses)}")
        return resp

    def get(self, url, **kwargs):
        return self._handle("get", url, **kwargs)

    def post(self, url, **kwargs):
        return self._handle("post", url, **kwargs)

    def delete(self, url, **kwargs):
        return self._handle("delete", url, **kwargs)


BASE = "http://schema-registry:8081"


def client(responses):
    return SchemaRegistryClient(BASE, session=FakeSession(responses))


# --- construction ---------------------------------------------------------


def test_base_url_trailing_slash_is_stripped():
    assert SchemaRegistryClient(BASE + "/", session=FakeSession()).base_url == BASE


def test_defaults_to_requests(monkeypatch):
    import requests

    c = SchemaRegistryClient(BASE)
    assert c.session is requests


# --- subjects and versions ------------------------------------------------


def test_list_subjects_is_sorted():
    c = client({("get", f"{BASE}/subjects"): FakeResponse(body=["b-value", "a-value"])})

    assert c.list_subjects() == ["a-value", "b-value"]


def test_list_subjects_sends_vendor_content_type():
    c = client({("get", f"{BASE}/subjects"): FakeResponse(body=[])})
    c.list_subjects()

    _, _, kwargs = c.session.calls[0]
    assert kwargs["headers"]["Content-Type"] == CONTENT_TYPE
    assert kwargs["timeout"] == 5


def test_list_versions_is_sorted():
    c = client({("get", f"{BASE}/subjects/s/versions"): FakeResponse(body=[3, 1, 2])})

    assert c.list_versions("s") == [1, 2, 3]


def test_get_version_defaults_to_latest():
    c = client(
        {
            ("get", f"{BASE}/subjects/s/versions/latest"): FakeResponse(
                body={"subject": "s", "version": 4, "id": 12, "schema": AVRO}
            )
        }
    )

    detail = c.get_version("s")

    assert detail == SchemaVersion(subject="s", version=4, schema_id=12, schema=AVRO)
    assert detail.schema_type == "AVRO"


def test_get_version_explicit_version_and_type():
    c = client(
        {
            ("get", f"{BASE}/subjects/s/versions/2"): FakeResponse(
                body={
                    "subject": "s",
                    "version": 2,
                    "id": 9,
                    "schema": "syntax = 'proto3';",
                    "schemaType": "PROTOBUF",
                }
            )
        }
    )

    detail = c.get_version("s", 2)

    assert detail.version == 2
    assert detail.schema_type == "PROTOBUF"


# --- config ---------------------------------------------------------------


def test_compatibility_level():
    c = client({("get", f"{BASE}/config"): FakeResponse(body={"compatibilityLevel": "BACKWARD"})})

    assert c.compatibility_level() == "BACKWARD"


def test_compatibility_level_missing_key():
    c = client({("get", f"{BASE}/config"): FakeResponse(body={})})

    assert c.compatibility_level() == "UNKNOWN"


# --- writes ---------------------------------------------------------------


def test_register_schema_returns_id_and_posts_payload():
    c = client({("post", f"{BASE}/subjects/s/versions"): FakeResponse(body={"id": 42})})

    assert c.register_schema("s", AVRO) == 42

    _, _, kwargs = c.session.calls[0]
    assert kwargs["json"] == {"schema": AVRO, "schemaType": "AVRO"}


def test_register_schema_honours_schema_type():
    c = client({("post", f"{BASE}/subjects/s/versions"): FakeResponse(body={"id": 1})})
    c.register_schema("s", "x", schema_type="JSON")

    assert c.session.calls[0][2]["json"]["schemaType"] == "JSON"


def test_delete_subject_returns_deleted_versions():
    c = client({("delete", f"{BASE}/subjects/s"): FakeResponse(body=[1, 2])})

    assert c.delete_subject("s") == [1, 2]


# --- error handling -------------------------------------------------------


def test_registry_error_message_uses_error_code_and_message():
    c = client(
        {
            ("get", f"{BASE}/subjects/nope/versions"): FakeResponse(
                status_code=404,
                body={"error_code": 40401, "message": "Subject 'nope' not found."},
            )
        }
    )

    with pytest.raises(SchemaRegistryError, match=r"40401: Subject 'nope' not found\."):
        c.list_versions("nope")


def test_registry_error_falls_back_to_status_when_body_has_no_message():
    c = client({("get", f"{BASE}/subjects"): FakeResponse(status_code=500, body={"oops": 1})})

    with pytest.raises(SchemaRegistryError, match="HTTP 500"):
        c.list_subjects()


def test_registry_error_falls_back_when_body_is_not_json():
    c = client({("get", f"{BASE}/subjects"): FakeResponse(status_code=502, raises=True)})

    with pytest.raises(SchemaRegistryError, match="HTTP 502"):
        c.list_subjects()


def test_registry_error_when_body_is_a_list():
    c = client({("get", f"{BASE}/subjects"): FakeResponse(status_code=400, body=["x"])})

    with pytest.raises(SchemaRegistryError, match="HTTP 400"):
        c.list_subjects()


# --- formatting -----------------------------------------------------------


def test_pretty_schema_formats_json():
    version = SchemaVersion(subject="s", version=1, schema_id=1, schema=AVRO)

    assert version.pretty_schema() == json.dumps(json.loads(AVRO), indent=2)
    assert "\n" in version.pretty_schema()


def test_pretty_schema_passes_through_non_json():
    version = SchemaVersion(
        subject="s", version=1, schema_id=1, schema="syntax = 'proto3';", schema_type="PROTOBUF"
    )

    assert version.pretty_schema() == "syntax = 'proto3';"


def test_pretty_schema_handles_none():
    version = SchemaVersion(subject="s", version=1, schema_id=1, schema=None)  # ty: ignore

    assert version.pretty_schema() is None
