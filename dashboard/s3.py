"""S3 operations against the Floci AWS emulator.

Thin wrappers over boto3 that return plain Python values, keeping the
Streamlit layer free of SDK response-shape handling.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class ObjectSummary:
    key: str
    size: int
    last_modified: datetime | None


def list_buckets(client: Any) -> list[str]:
    return [b["Name"] for b in client.list_buckets().get("Buckets", [])]


def create_bucket(client: Any, name: str, region: str) -> None:
    """Create a bucket, handling the us-east-1 API special case.

    S3 rejects a LocationConstraint of ``us-east-1`` — that region must be
    requested by omitting the constraint entirely.
    """
    if region == "us-east-1":
        client.create_bucket(Bucket=name)
    else:
        client.create_bucket(
            Bucket=name,
            CreateBucketConfiguration={"LocationConstraint": region},
        )


def delete_bucket(client: Any, name: str) -> None:
    client.delete_bucket(Bucket=name)


def list_objects(
    client: Any, bucket: str, prefix: str = "", limit: int = 100
) -> list[ObjectSummary]:
    resp = client.list_objects_v2(Bucket=bucket, Prefix=prefix, MaxKeys=limit)
    return [
        ObjectSummary(
            key=item["Key"],
            size=item.get("Size", 0),
            last_modified=item.get("LastModified"),
        )
        for item in resp.get("Contents", [])
    ]


def put_object(client: Any, bucket: str, key: str, body: bytes) -> None:
    client.put_object(Bucket=bucket, Key=key, Body=body)


def get_object(client: Any, bucket: str, key: str) -> bytes:
    return client.get_object(Bucket=bucket, Key=key)["Body"].read()


def delete_object(client: Any, bucket: str, key: str) -> None:
    client.delete_object(Bucket=bucket, Key=key)


def presign_url(client: Any, bucket: str, key: str, expires_in: int = 3600) -> str:
    return client.generate_presigned_url(
        "get_object",
        Params={"Bucket": bucket, "Key": key},
        ExpiresIn=expires_in,
    )


def human_size(num_bytes: int) -> str:
    """Format a byte count for display."""
    size = float(num_bytes)
    for unit in ("B", "KB", "MB"):
        if abs(size) < 1024.0:
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} GB"
