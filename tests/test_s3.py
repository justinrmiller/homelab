from __future__ import annotations

import pytest

from dashboard import s3


def test_list_buckets(fake_s3):
    assert s3.list_buckets(fake_s3) == ["alpha", "beta"]


def test_list_buckets_empty():
    from tests.conftest import FakeS3Client

    assert s3.list_buckets(FakeS3Client()) == []


def test_create_bucket_in_us_east_1_omits_location_constraint(fake_s3):
    """S3 rejects an explicit us-east-1 LocationConstraint."""
    s3.create_bucket(fake_s3, "gamma", "us-east-1")

    assert fake_s3.created_with == [{"Bucket": "gamma"}]
    assert "gamma" in fake_s3.buckets


def test_create_bucket_in_other_region_sets_location_constraint(fake_s3):
    s3.create_bucket(fake_s3, "gamma", "eu-west-1")

    assert fake_s3.created_with == [
        {"Bucket": "gamma", "CreateBucketConfiguration": {"LocationConstraint": "eu-west-1"}}
    ]


def test_delete_bucket(fake_s3):
    s3.delete_bucket(fake_s3, "beta")

    assert "beta" not in fake_s3.buckets


def test_list_objects(fake_s3):
    objects = s3.list_objects(fake_s3, "alpha")

    assert {o.key for o in objects} == {"a.txt", "logs/b.txt"}
    assert objects[0].size == len(b"hello")
    assert objects[0].last_modified is not None


def test_list_objects_honours_prefix(fake_s3):
    objects = s3.list_objects(fake_s3, "alpha", prefix="logs/")

    assert [o.key for o in objects] == ["logs/b.txt"]


def test_list_objects_honours_limit(fake_s3):
    assert len(s3.list_objects(fake_s3, "alpha", limit=1)) == 1


def test_list_objects_on_empty_bucket(fake_s3):
    assert s3.list_objects(fake_s3, "beta") == []


def test_put_get_round_trip(fake_s3):
    s3.put_object(fake_s3, "beta", "note.txt", b"contents")

    assert s3.get_object(fake_s3, "beta", "note.txt") == b"contents"


def test_delete_object(fake_s3):
    s3.delete_object(fake_s3, "alpha", "a.txt")

    assert "a.txt" not in fake_s3.buckets["alpha"]


def test_delete_missing_object_is_a_noop(fake_s3):
    s3.delete_object(fake_s3, "alpha", "nope.txt")


def test_presign_url(fake_s3):
    url = s3.presign_url(fake_s3, "alpha", "a.txt", expires_in=60)

    assert url.startswith("http://floci:4566/alpha/a.txt")
    assert "X-Amz-Expires=60" in url


@pytest.mark.parametrize(
    ("num_bytes", "expected"),
    [
        (0, "0 B"),
        (512, "512 B"),
        (1024, "1.0 KB"),
        (1536, "1.5 KB"),
        (1024 * 1024, "1.0 MB"),
        (1024 * 1024 * 1024, "1.0 GB"),
        (5 * 1024 * 1024 * 1024, "5.0 GB"),
    ],
)
def test_human_size(num_bytes, expected):
    assert s3.human_size(num_bytes) == expected
