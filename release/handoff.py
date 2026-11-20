"""交班流状态、自动选版与跨入口发布号归属。"""
import sqlite3
from dataclasses import dataclass

from facts.editions import load_fact_rows
from registry.editions import load_registry_assignments
from retention.store import DayStore, validate_identifier


class HandoffNotRegistered(LookupError):
    def __init__(self, day: str):
        self.day = day
        super().__init__(f'no handoff stream is registered for {day!r}')


class HandoffNumberConflict(ValueError):
    def __init__(self, day: str, number: str):
        self.day = day
        self.number = number
        super().__init__(f'publication {number!r} for {day!r} is already used by the other entry')


@dataclass(frozen=True, slots=True)
class HandoffStream:
    day: str
    fact_floor: int
    registry_floor: int


def get_handoff_stream(conn: sqlite3.Connection, day: str) -> HandoffStream | None:
    record = conn.execute(
        'SELECT fact_floor, registry_floor FROM handoff_streams WHERE day = ?',
        (day,),
    ).fetchone()
    return None if record is None else HandoffStream(day, record[0], record[1])


def read_handoff_progress(store: DayStore, day: str) -> HandoffStream | None:
    validate_identifier(day, 'day')
    with store.read_transaction() as conn:
        return get_handoff_stream(conn, day)


def register_handoff_stream(conn: sqlite3.Connection, day: str) -> HandoffStream:
    """Start a stream at ``(0, 0)`` without disturbing existing progress."""
    conn.execute(
        'INSERT INTO handoff_streams(day, fact_floor, registry_floor) VALUES (?, 0, 0) '
        'ON CONFLICT(day) DO NOTHING',
        (day,),
    )
    stream = get_handoff_stream(conn, day)
    if stream is None:
        raise sqlite3.IntegrityError('handoff stream was not stored')
    return stream


def publication_origin(conn: sqlite3.Connection, day: str, number: str) -> str | None:
    """Return ``'handoff'``, ``'manual'`` or ``None`` for an unused number."""
    if conn.execute(
        'SELECT 1 FROM handoff_publications WHERE day = ? AND number = ?',
        (day, number),
    ).fetchone() is not None:
        return 'handoff'
    if conn.execute(
        'SELECT 1 FROM release_receipts WHERE day = ? AND number = ?',
        (day, number),
    ).fetchone() is not None:
        return 'manual'
    return None


def record_handoff_publication(conn: sqlite3.Connection, day: str, number: str) -> None:
    conn.execute(
        'INSERT INTO handoff_publications(day, number) VALUES (?, ?)',
        (day, number),
    )


def advance_handoff(
    conn: sqlite3.Connection, day: str, fact_version: int, registry_version: int,
) -> None:
    result = conn.execute(
        '''UPDATE handoff_streams SET fact_floor = ?, registry_floor = ?
           WHERE day = ? AND fact_floor <= ? AND registry_floor <= ?''',
        (fact_version, registry_version, day, fact_version, registry_version),
    )
    if result.rowcount != 1:
        raise sqlite3.IntegrityError('handoff progress must advance monotonically')


def _available_versions(conn: sqlite3.Connection, day: str, kind: str) -> tuple[int, ...]:
    records = conn.execute(
        '''SELECT version FROM edition_directory
           WHERE day = ? AND kind = ? AND available = 1 ORDER BY version''',
        (day, kind),
    )
    return tuple(version for version, in records)


def candidate_pairs(
    conn: sqlite3.Connection, day: str, stream: HandoffStream,
) -> tuple[tuple[int, int], ...]:
    """Enumerate compatible available pairs that stay above both floors and advance."""
    fact_versions = tuple(
        version for version in _available_versions(conn, day, 'facts')
        if version >= stream.fact_floor
    )
    registry_versions = tuple(
        version for version in _available_versions(conn, day, 'registry')
        if version >= stream.registry_floor
    )
    registry_points = {
        version: {assignment.point for assignment in load_registry_assignments(conn, day, version)}
        for version in registry_versions
    }
    pairs = []
    for fact_version in fact_versions:
        points = {row.point for row in load_fact_rows(conn, day, fact_version)}
        for registry_version in registry_versions:
            if fact_version == stream.fact_floor and registry_version == stream.registry_floor:
                continue
            if points <= registry_points[registry_version]:
                pairs.append((fact_version, registry_version))
    return tuple(pairs)


def maximal_pairs(pairs: tuple[tuple[int, int], ...]) -> tuple[tuple[int, int], ...]:
    """Keep pairs that no other compatible pair can advance beyond on either side."""
    return tuple(
        pair for pair in pairs
        if not any(
            other[0] >= pair[0] and other[1] >= pair[1] and other != pair
            for other in pairs
        )
    )


def choose_handoff_pair(
    conn: sqlite3.Connection, day: str, stream: HandoffStream,
) -> tuple[int, int] | None:
    """Pick the lexicographically greatest maximal pair (fact first, then registry)."""
    maximal = maximal_pairs(candidate_pairs(conn, day, stream))
    return None if not maximal else max(maximal)
