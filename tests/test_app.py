"""End-to-end rendering tests driven by Streamlit's AppTest harness.

These run the real script with the network layer faked out, so they cover the
page dispatch and the status/error rendering that unit tests cannot reach.
"""

from __future__ import annotations

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from dashboard import health

APP_PATH = "dashboard/app.py"
ALL_SERVICES = ["Valkey", "Kafka", "PostgreSQL", "Hasura", "S3 (Floci)"]


@pytest.fixture(autouse=True)
def _clear_streamlit_caches():
    """st.cache_resource is process-global and would leak fakes between tests."""
    st.cache_resource.clear()
    yield
    st.cache_resource.clear()


@pytest.fixture
def all_healthy(monkeypatch):
    for name in ("check_valkey", "check_kafka", "check_postgres", "check_hasura", "check_s3"):
        monkeypatch.setattr(
            health, name, lambda cfg, **kw: health.HealthResult(True, "Connected successfully")
        )


@pytest.fixture
def all_down(monkeypatch):
    for name in ("check_valkey", "check_kafka", "check_postgres", "check_hasura", "check_s3"):
        monkeypatch.setattr(
            health, name, lambda cfg, **kw: health.HealthResult(False, "Connection error: refused")
        )


def run_app(page: str | None = None) -> AppTest:
    at = AppTest.from_file(APP_PATH, default_timeout=30).run()
    if page is not None:
        at.sidebar.radio[0].set_value(page).run()
    return at


def test_overview_lists_every_service(all_healthy):
    at = run_app()

    assert not at.exception
    assert at.title[0].value == "Homelab Services Overview"
    rendered = at.dataframe[0].value["Service"].tolist()
    assert rendered == ALL_SERVICES


def test_overview_shows_failures(all_down):
    at = run_app()

    assert not at.exception
    statuses = at.dataframe[0].value["Status"].tolist()
    assert set(statuses) == {health.ERROR}


def test_removed_services_are_gone(all_healthy):
    at = run_app()

    options = at.sidebar.radio[0].options
    assert "Qdrant" not in options
    assert "MongoDB" not in options
    assert "S3 (Floci)" in options


@pytest.mark.parametrize("page", ALL_SERVICES)
def test_each_page_reports_a_down_service_without_crashing(all_down, page):
    at = run_app(page)

    assert not at.exception
    assert any("Cannot connect" in e.value for e in at.error)


def test_s3_page_renders_buckets_and_objects(all_healthy, monkeypatch, fake_s3):
    monkeypatch.setattr("dashboard.clients.make_s3_client", lambda cfg: fake_s3)

    at = run_app("S3 (Floci)")

    assert not at.exception
    assert at.title[0].value == "S3 Dashboard (Floci)"
    body = " ".join(m.value for m in at.markdown)
    assert "alpha" in body
    # Object listing renders in a dataframe once a bucket is selected.
    assert at.dataframe[0].value["Key"].tolist() == ["a.txt", "logs/b.txt"]


def test_s3_page_surfaces_listing_errors(all_healthy, monkeypatch):
    class Broken:
        def list_buckets(self):
            raise RuntimeError("emulator unavailable")

    monkeypatch.setattr("dashboard.clients.make_s3_client", lambda cfg: Broken())

    at = run_app("S3 (Floci)")

    assert not at.exception
    assert any("emulator unavailable" in e.value for e in at.error)


def test_hasura_page_warns_when_no_admin_secret(all_healthy, monkeypatch):
    monkeypatch.setenv("HASURA_GRAPHQL_ADMIN_SECRET", "")

    at = run_app("Hasura")

    assert not at.exception
    assert any("no admin secret" in w.value for w in at.warning)


def test_hasura_page_quiet_when_secret_is_set(all_healthy, monkeypatch):
    monkeypatch.setenv("HASURA_GRAPHQL_ADMIN_SECRET", "topsecret")

    at = run_app("Hasura")

    assert not at.exception
    assert not any("no admin secret" in w.value for w in at.warning)
