"""Confluent Schema Registry REST client.

A thin wrapper over the registry's HTTP API. The transport is injectable so
tests can drive every branch without a running registry.

API reference: https://docs.confluent.io/platform/current/schema-registry/develop/api.html
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

# The registry expects and returns its own vendor content type.
CONTENT_TYPE = "application/vnd.schemaregistry.v1+json"

DEFAULT_TIMEOUT = 5


@dataclass(frozen=True)
class SchemaVersion:
    subject: str
    version: int
    schema_id: int
    schema: str
    schema_type: str = "AVRO"

    def pretty_schema(self) -> str:
        """Return the schema formatted for display, if it is JSON."""
        try:
            return json.dumps(json.loads(self.schema), indent=2)
        except (json.JSONDecodeError, TypeError):
            # Protobuf schemas are not JSON; show them as-is.
            return self.schema


class SchemaRegistryError(RuntimeError):
    """Raised when the registry returns a non-success response."""


class SchemaRegistryClient:
    def __init__(
        self,
        base_url: str,
        session: Any | None = None,
        timeout: int = DEFAULT_TIMEOUT,
    ) -> None:
        if session is None:
            import requests

            session = requests
        self.base_url = base_url.rstrip("/")
        self.session = session
        self.timeout = timeout

    # --- transport --------------------------------------------------------

    def _request(self, method: str, path: str, payload: dict | None = None) -> Any:
        url = f"{self.base_url}{path}"
        kwargs: dict[str, Any] = {
            "timeout": self.timeout,
            "headers": {"Content-Type": CONTENT_TYPE},
        }
        if payload is not None:
            kwargs["json"] = payload
        resp = getattr(self.session, method)(url, **kwargs)
        if resp.status_code >= 400:
            raise SchemaRegistryError(self._error_message(resp))
        return resp.json()

    @staticmethod
    def _error_message(resp: Any) -> str:
        """Prefer the registry's own error_code/message over a bare status."""
        try:
            body = resp.json()
        except Exception:
            return f"HTTP {resp.status_code}"
        if isinstance(body, dict) and "message" in body:
            code = body.get("error_code", resp.status_code)
            return f"{code}: {body['message']}"
        return f"HTTP {resp.status_code}"

    # --- operations -------------------------------------------------------

    def list_subjects(self) -> list[str]:
        return sorted(self._request("get", "/subjects"))

    def list_versions(self, subject: str) -> list[int]:
        return sorted(self._request("get", f"/subjects/{subject}/versions"))

    def get_version(self, subject: str, version: int | str = "latest") -> SchemaVersion:
        body = self._request("get", f"/subjects/{subject}/versions/{version}")
        return SchemaVersion(
            subject=body["subject"],
            version=body["version"],
            schema_id=body["id"],
            schema=body["schema"],
            schema_type=body.get("schemaType", "AVRO"),
        )

    def compatibility_level(self) -> str:
        body = self._request("get", "/config")
        return body.get("compatibilityLevel", "UNKNOWN")

    def register_schema(self, subject: str, schema: str, schema_type: str = "AVRO") -> int:
        payload: dict[str, Any] = {"schema": schema, "schemaType": schema_type}
        body = self._request("post", f"/subjects/{subject}/versions", payload)
        return body["id"]

    def delete_subject(self, subject: str) -> list[int]:
        return self._request("delete", f"/subjects/{subject}")
