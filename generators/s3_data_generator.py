#!/usr/bin/env python3
"""Seed the Floci S3 emulator with sample objects.

Run with: uv run --group generators python generators/s3_data_generator.py
"""

from __future__ import annotations

import argparse
import json

from faker import Faker

from dashboard import s3
from dashboard.clients import make_s3_client
from dashboard.config import load_config


def generate_user(fake: Faker) -> dict:
    return {
        "name": fake.name(),
        "email": fake.email(),
        "address": fake.address(),
        "created_at": fake.date_time_this_decade().isoformat(),
        "is_active": fake.boolean(),
        "age": fake.random_int(min=18, max=80),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bucket", default="sample-data")
    parser.add_argument("--objects", type=int, default=100)
    parser.add_argument("--users-per-object", type=int, default=100)
    args = parser.parse_args()

    config = load_config()
    client = make_s3_client(config.s3)
    fake = Faker()

    if args.bucket not in s3.list_buckets(client):
        s3.create_bucket(client, args.bucket, config.s3.region)
        print(f"Created bucket {args.bucket}")

    for i in range(args.objects):
        users = [generate_user(fake) for _ in range(args.users_per_object)]
        key = f"users/batch-{i:04d}.json"
        s3.put_object(client, args.bucket, key, json.dumps(users).encode("utf-8"))
        print(f"Wrote {key} ({len(users)} users)")

    total = args.objects * args.users_per_object
    print(f"Done: {total} users across {args.objects} objects in s3://{args.bucket}")


if __name__ == "__main__":
    main()
