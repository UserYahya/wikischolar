"""Concurrency-safe human-readable IDs, backed by the id_sequences table."""
from django.db import connection
from django.utils import timezone


def next_value(scope, year):
    with connection.cursor() as cur:
        cur.execute(
            """
            INSERT INTO id_sequences (scope, year, last_value) VALUES (%s, %s, 1)
            ON CONFLICT (scope, year) DO UPDATE SET last_value = id_sequences.last_value + 1
            RETURNING last_value
            """,
            [scope, year],
        )
        return cur.fetchone()[0]


def next_code(scope, prefix, width=6, year=None):
    year = year or timezone.localdate().year
    return f"{prefix}-{year}-{next_value(scope, year):0{width}d}"


def next_wikischolar_id():
    """WS-<year>-000001. The year is the programme year (WS_ID_YEAR), not necessarily today's."""
    from django.conf import settings
    ws = settings.WIKISCHOLAR
    return next_code("student", ws["ID_PREFIX"], width=6, year=ws["ID_YEAR"])
