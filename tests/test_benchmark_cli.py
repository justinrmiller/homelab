"""Argument parsing and the shared exit-code rules."""

from __future__ import annotations

import argparse
import json

import pytest

from benchmark import cli
from benchmark.report import ServiceReport
from benchmark.stats import PhaseResult


def parse(*argv: str) -> argparse.Namespace:
    return argparse.ArgumentParser(parents=[cli.shared_parser()]).parse_args(list(argv))


@pytest.mark.parametrize(
    ("text", "expected"),
    [("512", 512), ("4k", 4096), ("1MiB", 1048576), ("2mb", 2097152), ("64B", 64)],
)
def test_size_suffixes(text, expected):
    assert cli.parse_size(text) == expected


@pytest.mark.parametrize("text", ["", "abc", "1x", "-4k", "0"])
def test_bad_sizes_are_rejected(text):
    with pytest.raises(argparse.ArgumentTypeError):
        cli.parse_size(text)


def test_ops_and_payload_default_to_none_so_services_choose():
    args = parse()
    assert args.ops is None
    assert args.payload_size is None
    assert args.concurrency == 4


def test_non_positive_counts_are_a_usage_error():
    with pytest.raises(SystemExit):
        parse("--ops", "0")
    with pytest.raises(SystemExit):
        parse("--concurrency", "-1")


def test_warmup_may_be_zero_but_not_negative():
    assert parse("--warmup", "0").warmup == 0
    with pytest.raises(SystemExit):
        parse("--warmup", "-1")


def test_default_warmup_is_a_tenth_of_the_run_capped():
    assert cli.default_warmup(1000, None) == 100
    assert cli.default_warmup(100_000, None) == 100
    assert cli.default_warmup(5, None) == 1
    assert cli.default_warmup(1000, 7) == 7
    assert cli.default_warmup(1000, 0) == 0


def test_run_id_is_usable_as_a_topic_name():
    run_id = cli.new_run_id()
    assert all(c.isalnum() or c in "._-" for c in run_id)


def _report(**phase_kwargs) -> ServiceReport:
    phase = PhaseResult(name="set", requested=1, elapsed=1.0, **phase_kwargs)
    return ServiceReport(
        service="Valkey",
        target="nas.local:6379",
        run_id="run",
        started_at="2026-09-16T00:00:00+0000",
        params={"ops": 1},
        phases=(phase,),
    )


def test_exit_code_is_zero_when_nothing_failed():
    assert cli.exit_code([_report(latencies=(0.1,))]) == cli.EXIT_OK


def test_exit_code_is_nonzero_when_any_op_failed():
    assert cli.exit_code([_report(error_counts={"boom": 1})]) == cli.EXIT_ERRORS


def test_execute_reports_a_preflight_failure_without_running_the_rest(capsys):
    def boom(_args):
        raise cli.PreflightError("nothing listening")

    code = cli.execute([("valkey", boom)], parse())
    assert code == cli.EXIT_PREFLIGHT
    assert "nothing listening" in capsys.readouterr().out


def test_execute_keeps_going_after_one_service_fails(capsys):
    def boom(_args):
        raise cli.PreflightError("nope")

    code = cli.execute([("kafka", boom), ("valkey", lambda _a: _report(latencies=(0.1,)))], parse())
    out = capsys.readouterr().out
    assert code == cli.EXIT_PREFLIGHT
    assert "nope" in out
    assert "Valkey" in out


def test_out_file_receives_the_same_json(tmp_path, capsys):
    target = tmp_path / "run.json"
    args = parse("--out", str(target))
    cli.emit([_report(latencies=(0.1,))], args)
    capsys.readouterr()
    payload = json.loads(target.read_text())
    assert payload["schema"] == 1
    assert payload["runs"][0]["service"] == "Valkey"
