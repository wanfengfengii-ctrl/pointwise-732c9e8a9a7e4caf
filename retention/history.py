import sqlite3
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RetirementRecord:
    day: str
    kind: str
    version: int


def record_retirement(conn: sqlite3.Connection, day: str, kind: str, version: int) -> RetirementRecord:
    conn.execute('INSERT INTO retirements(day, kind, version) VALUES (?, ?, ?)', (day, kind, version))
    return RetirementRecord(day, kind, version)


def get_retirement(conn: sqlite3.Connection, day: str, kind: str, version: int) -> RetirementRecord | None:
    result = conn.execute(
        'SELECT day, kind, version FROM retirements WHERE day = ? AND kind = ? AND version = ?',
        (day, kind, version),
    ).fetchone()
    return None if result is None else RetirementRecord(*result)
