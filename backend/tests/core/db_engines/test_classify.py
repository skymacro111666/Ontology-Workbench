"""classify_connect_error: driver messages bucket into UI reason codes."""

import pytest

from ontoworkbench.core.db_engines import classify_connect_error

# Realistic driver/DBAPI failure texts (SQLAlchemy re-raises them verbatim
# once unwrapped), one per bucket plus the order-sensitive overlap.
CASES = [
    # psycopg: TCP refused; pymysql: (2003, "Can't connect ...")
    ("connection refused", "REFUSED"),
    ("(2003, \"Can't connect to MySQL server on 'db:3306' (111)\")", "REFUSED"),
    # pymysql's timeout message ALSO says "can't connect" — timeout must win
    ("(2003, \"Can't connect to MySQL server on 'db:3306' (timed out)\")", "TIMEOUT"),
    ("connection timeout expired", "TIMEOUT"),
    # auth: pg password auth / mysql access denied
    ('password authentication failed for user "u"', "AUTH_FAILED"),
    ("(1045, \"Access denied for user 'u'@'h' (using password: YES)\")", "AUTH_FAILED"),
    # missing database: pg FATAL / mysql 1049
    ('database "app" does not exist', "DB_NOT_FOUND"),
    ("(1049, \"Unknown database 'app'\")", "DB_NOT_FOUND"),
    # sqlite: unopenable path (missing dir, no permission)
    ("unable to open database file", "PATH_NOT_FOUND"),
    # anything the patterns don't know
    ("something exploded in a novel way", "UNKNOWN"),
]


@pytest.mark.parametrize(("message", "expected"), CASES)
def test_buckets(message: str, expected: str) -> None:
    """Each driver message text lands in its bucket."""
    assert classify_connect_error(Exception(message)) == expected


def test_case_insensitive() -> None:
    """Real drivers capitalize; matching lowercases first."""
    assert classify_connect_error(Exception("Connection refused")) == "REFUSED"
