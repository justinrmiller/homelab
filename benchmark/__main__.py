"""Benchmark every service in the stack against one host.

Run with: uv run python -m benchmark --host <hostname>

Each service keeps its own defaults for --ops and --payload-size, because a
hundred 1 MiB objects is a reasonable S3 run and a pointless Valkey one. Pass
either flag to override all of them at once.
"""

from __future__ import annotations

import argparse

from benchmark import cli, kafka_bench, s3_bench, valkey_bench

_SERVICES = (
    ("s3", s3_bench),
    ("valkey", valkey_bench),
    ("kafka", kafka_bench),
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="benchmark", description=__doc__, parents=[cli.shared_parser()]
    )
    parser.add_argument(
        "--only",
        action="append",
        choices=[name for name, _ in _SERVICES],
        help="benchmark just this service; repeatable",
    )
    for _, module in _SERVICES:
        module.add_arguments(parser)
    args = parser.parse_args(argv)

    selected = [(name, m.run) for name, m in _SERVICES if not args.only or name in args.only]
    return cli.execute(selected, args)


if __name__ == "__main__":
    raise SystemExit(main())
