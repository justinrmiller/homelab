from __future__ import annotations

import pytest

from dashboard.sql import is_read_only, safe_identifier


@pytest.mark.parametrize(
    "name",
    ["users", "test_table", "_private", "t1", "A" * 63],
)
def test_accepts_bare_identifiers(name):
    assert safe_identifier(name) == name


def test_strips_surrounding_whitespace():
    assert safe_identifier("  users  ") == "users"


@pytest.mark.parametrize(
    "name",
    [
        "users; DROP TABLE students",
        "users--",
        "1users",
        "",
        "   ",
        "public.users",
        'users"',
        "A" * 64,
    ],
)
def test_rejects_anything_else(name):
    with pytest.raises(ValueError, match="not a valid table name"):
        safe_identifier(name)


@pytest.mark.parametrize(
    "statement",
    [
        "SELECT 1",
        "  select version();",
        "WITH x AS (SELECT 1) SELECT * FROM x",
        "SHOW timezone",
        "EXPLAIN SELECT 1",
        "(SELECT 1)",
        "TABLE users",
        "VALUES (1)",
    ],
)
def test_read_only_statements(statement):
    assert is_read_only(statement)


@pytest.mark.parametrize(
    "statement",
    [
        "INSERT INTO users VALUES (1)",
        "UPDATE users SET a = 1",
        "DELETE FROM users",
        "DROP TABLE users",
        "CREATE TABLE t (id int)",
        "TRUNCATE users",
    ],
)
def test_write_statements(statement):
    assert not is_read_only(statement)
