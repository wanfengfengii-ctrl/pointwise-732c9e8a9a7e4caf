import sqlite3
from dataclasses import dataclass

from .assignments import Assignment


@dataclass(frozen=True, slots=True)
class RegistryEdition:
    day: str
    version: int


def append_registry_edition(
    conn: sqlite3.Connection, day: str, assignments: tuple[Assignment, ...],
) -> RegistryEdition:
    last, = conn.execute('SELECT MAX(version) FROM registry_editions WHERE day = ?', (day,)).fetchone()
    edition = RegistryEdition(day, (last or 0) + 1)
    conn.execute('INSERT INTO registry_editions(day, version) VALUES (?, ?)', (day, edition.version))
    conn.executemany(
        '''INSERT INTO registry_assignments(day, version, point, partition, source)
           VALUES (?, ?, ?, ?, ?)''',
        ((day, edition.version, entry.point, entry.partition, entry.source) for entry in assignments),
    )
    return edition


def load_registry_assignments(conn: sqlite3.Connection, day: str, version: int) -> tuple[Assignment, ...]:
    rows = conn.execute(
        '''SELECT point, partition, source FROM registry_assignments
           WHERE day = ? AND version = ? ORDER BY point''',
        (day, version),
    )
    return tuple(Assignment(*row) for row in rows)


def remove_registry_payload(conn: sqlite3.Connection, day: str, version: int) -> None:
    conn.execute('DELETE FROM registry_assignments WHERE day = ? AND version = ?', (day, version))
