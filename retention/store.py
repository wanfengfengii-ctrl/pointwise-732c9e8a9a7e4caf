import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager


_SCHEMA = (
    '''CREATE TABLE IF NOT EXISTS days (
        day TEXT PRIMARY KEY NOT NULL
    )''',
    '''CREATE TABLE IF NOT EXISTS fact_editions (
        day TEXT NOT NULL REFERENCES days(day),
        version INTEGER NOT NULL CHECK (version > 0),
        PRIMARY KEY(day, version)
    )''',
    '''CREATE TABLE IF NOT EXISTS fact_rows (
        day TEXT NOT NULL,
        version INTEGER NOT NULL,
        position INTEGER NOT NULL CHECK (position >= 0),
        point TEXT NOT NULL,
        liters TEXT,
        source TEXT NOT NULL,
        PRIMARY KEY(day, version, position),
        FOREIGN KEY(day, version) REFERENCES fact_editions(day, version)
    )''',
    '''CREATE TABLE IF NOT EXISTS fact_receipts (
        day TEXT NOT NULL,
        request_id TEXT NOT NULL,
        version INTEGER NOT NULL,
        content TEXT NOT NULL,
        PRIMARY KEY(day, request_id),
        UNIQUE(day, version),
        FOREIGN KEY(day, version) REFERENCES fact_editions(day, version)
    )''',
    '''CREATE TABLE IF NOT EXISTS registry_editions (
        day TEXT NOT NULL REFERENCES days(day),
        version INTEGER NOT NULL CHECK (version > 0),
        PRIMARY KEY(day, version)
    )''',
    '''CREATE TABLE IF NOT EXISTS registry_assignments (
        day TEXT NOT NULL,
        version INTEGER NOT NULL,
        point TEXT NOT NULL,
        partition TEXT NOT NULL,
        source TEXT NOT NULL,
        PRIMARY KEY(day, version, point),
        FOREIGN KEY(day, version) REFERENCES registry_editions(day, version)
    )''',
    '''CREATE TABLE IF NOT EXISTS registry_receipts (
        day TEXT NOT NULL,
        request_id TEXT NOT NULL,
        version INTEGER NOT NULL,
        content TEXT NOT NULL,
        PRIMARY KEY(day, request_id),
        UNIQUE(day, version),
        FOREIGN KEY(day, version) REFERENCES registry_editions(day, version)
    )''',
    '''CREATE TABLE IF NOT EXISTS edition_directory (
        day TEXT NOT NULL REFERENCES days(day),
        kind TEXT NOT NULL CHECK (kind IN ('facts', 'registry')),
        version INTEGER NOT NULL CHECK (version > 0),
        available INTEGER NOT NULL CHECK (available IN (0, 1)),
        PRIMARY KEY(day, kind, version)
    )''',
    '''CREATE TABLE IF NOT EXISTS retirements (
        day TEXT NOT NULL,
        kind TEXT NOT NULL,
        version INTEGER NOT NULL,
        PRIMARY KEY(day, kind, version),
        FOREIGN KEY(day, kind, version) REFERENCES edition_directory(day, kind, version)
    )''',
    '''CREATE TABLE IF NOT EXISTS release_snapshots (
        day TEXT NOT NULL,
        number TEXT NOT NULL,
        fact_version INTEGER NOT NULL,
        registry_version INTEGER NOT NULL,
        PRIMARY KEY(day, number),
        FOREIGN KEY(day, fact_version) REFERENCES fact_editions(day, version),
        FOREIGN KEY(day, registry_version) REFERENCES registry_editions(day, version)
    )''',
    '''CREATE TABLE IF NOT EXISTS release_details (
        day TEXT NOT NULL,
        number TEXT NOT NULL,
        position INTEGER NOT NULL CHECK (position >= 0),
        point TEXT NOT NULL,
        liters TEXT,
        partition TEXT NOT NULL,
        observation_source TEXT NOT NULL,
        registry_source TEXT NOT NULL,
        PRIMARY KEY(day, number, position),
        FOREIGN KEY(day, number) REFERENCES release_snapshots(day, number)
    )''',
    '''CREATE TABLE IF NOT EXISTS release_totals (
        day TEXT NOT NULL,
        number TEXT NOT NULL,
        partition TEXT NOT NULL,
        liters TEXT NOT NULL,
        missing INTEGER NOT NULL CHECK (missing >= 0),
        PRIMARY KEY(day, number, partition),
        FOREIGN KEY(day, number) REFERENCES release_snapshots(day, number)
    )''',
    '''CREATE TABLE IF NOT EXISTS release_receipts (
        day TEXT NOT NULL,
        number TEXT NOT NULL,
        PRIMARY KEY(day, number),
        FOREIGN KEY(day, number) REFERENCES release_snapshots(day, number)
    )''',
    '''CREATE TABLE IF NOT EXISTS handoff_streams (
        day TEXT PRIMARY KEY NOT NULL REFERENCES days(day),
        fact_floor INTEGER NOT NULL CHECK (fact_floor >= 0),
        registry_floor INTEGER NOT NULL CHECK (registry_floor >= 0)
    )''',
    '''CREATE TABLE IF NOT EXISTS handoff_publications (
        day TEXT NOT NULL,
        number TEXT NOT NULL,
        PRIMARY KEY(day, number),
        FOREIGN KEY(day, number) REFERENCES release_receipts(day, number)
    )''',
)


def validate_identifier(value: str, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'{name} must be a nonblank string')
    value.encode('utf-8')


def validate_version(version: int) -> None:
    if type(version) is not int or version < 1:
        raise ValueError('version must be a positive integer')


class DayStore:
    def __init__(self, path: str | os.PathLike[str]):
        self._conn = sqlite3.connect(path, isolation_level=None)
        try:
            self._conn.execute('PRAGMA foreign_keys = ON')
        except BaseException:
            self._conn.close()
            raise

    def __enter__(self) -> 'DayStore':
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()

    def close(self) -> None:
        self._conn.close()

    def initialize(self) -> None:
        with self.write_transaction() as conn:
            for statement in _SCHEMA:
                conn.execute(statement)

    @contextmanager
    def _transaction(self, begin: str) -> Iterator[sqlite3.Connection]:
        self._conn.execute(begin)
        try:
            yield self._conn
            self._conn.execute('COMMIT')
        except BaseException:
            if self._conn.in_transaction:
                self._conn.execute('ROLLBACK')
            raise

    def read_transaction(self):
        """Keep reads on one SQLite view for the duration of the operation."""
        return self._transaction('BEGIN')

    def write_transaction(self):
        """Serialize checks and changes and propagate a failed commit after rollback."""
        return self._transaction('BEGIN IMMEDIATE')


def open_store(path: str | os.PathLike[str]) -> DayStore:
    store = DayStore(path)
    try:
        store.initialize()
    except BaseException:
        store.close()
        raise
    return store
