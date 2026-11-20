import sqlite3
from dataclasses import dataclass

from .store import DayStore, validate_identifier


@dataclass(frozen=True, slots=True)
class EditionAvailability:
    day: str
    kind: str
    version: int
    available: bool


class UnknownDay(LookupError):
    def __init__(self, day: str):
        self.day = day
        super().__init__(f'unknown day {day!r}')


class InvalidSourceKind(ValueError):
    def __init__(self, kind: str):
        self.kind = kind
        super().__init__(f'invalid source kind {kind!r}')


def validate_kind(kind: str) -> None:
    if not isinstance(kind, str) or kind not in ('facts', 'registry'):
        raise InvalidSourceKind(kind)


def require_day(conn: sqlite3.Connection, day: str) -> None:
    if conn.execute('SELECT 1 FROM days WHERE day = ?', (day,)).fetchone() is None:
        raise UnknownDay(day)


def ensure_day(conn: sqlite3.Connection, day: str) -> None:
    conn.execute('INSERT INTO days(day) VALUES (?) ON CONFLICT(day) DO NOTHING', (day,))


def list_editions(store: DayStore, day: str, kind: str) -> tuple[EditionAvailability, ...]:
    validate_identifier(day, 'day')
    validate_kind(kind)
    with store.read_transaction() as conn:
        require_day(conn, day)
        records = conn.execute(
            '''SELECT version, available FROM edition_directory
               WHERE day = ? AND kind = ? ORDER BY version''',
            (day, kind),
        )
        return tuple(EditionAvailability(day, kind, version, bool(available)) for version, available in records)


def get_availability(conn: sqlite3.Connection, day: str, kind: str, version: int) -> EditionAvailability | None:
    if version > (1 << 63) - 1:
        return None
    record = conn.execute(
        'SELECT available FROM edition_directory WHERE day = ? AND kind = ? AND version = ?',
        (day, kind, version),
    ).fetchone()
    if record is None:
        return None
    return EditionAvailability(day, kind, version, bool(record[0]))


def register_available(conn: sqlite3.Connection, day: str, kind: str, version: int) -> None:
    conn.execute(
        'INSERT INTO edition_directory(day, kind, version, available) VALUES (?, ?, ?, 1)',
        (day, kind, version),
    )


def mark_retired(conn: sqlite3.Connection, day: str, kind: str, version: int) -> None:
    result = conn.execute(
        '''UPDATE edition_directory SET available = 0
           WHERE day = ? AND kind = ? AND version = ? AND available = 1''',
        (day, kind, version),
    )
    if result.rowcount != 1:
        raise sqlite3.IntegrityError('retirement requires exactly one available source edition')
