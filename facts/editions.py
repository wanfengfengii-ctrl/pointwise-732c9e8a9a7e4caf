import sqlite3
from dataclasses import dataclass

from .rows import FactRow, decode_liters, encode_liters


@dataclass(frozen=True, slots=True)
class FactEdition:
    day: str
    version: int


def append_fact_edition(conn: sqlite3.Connection, day: str, rows: tuple[FactRow, ...]) -> FactEdition:
    last, = conn.execute('SELECT MAX(version) FROM fact_editions WHERE day = ?', (day,)).fetchone()
    edition = FactEdition(day, (last or 0) + 1)
    conn.execute('INSERT INTO fact_editions(day, version) VALUES (?, ?)', (day, edition.version))
    conn.executemany(
        '''INSERT INTO fact_rows(day, version, position, point, liters, source)
           VALUES (?, ?, ?, ?, ?, ?)''',
        ((day, edition.version, row.position, row.point, encode_liters(row.liters), row.source)
         for row in rows),
    )
    return edition


def load_fact_rows(conn: sqlite3.Connection, day: str, version: int) -> tuple[FactRow, ...]:
    rows = conn.execute(
        '''SELECT position, point, liters, source FROM fact_rows
           WHERE day = ? AND version = ? ORDER BY position''',
        (day, version),
    )
    return tuple(FactRow(position, point, decode_liters(liters), source)
                 for position, point, liters, source in rows)


def remove_fact_payload(conn: sqlite3.Connection, day: str, version: int) -> None:
    conn.execute('DELETE FROM fact_rows WHERE day = ? AND version = ?', (day, version))
