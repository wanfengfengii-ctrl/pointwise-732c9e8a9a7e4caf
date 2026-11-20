import sqlite3
from enum import Enum

from release.handoff import get_handoff_stream

from .inventory import get_availability, require_day, validate_kind
from .store import validate_identifier, validate_version


class UnknownEdition(LookupError):
    def __init__(self, day: str, kind: str, version: int):
        self.day = day
        self.kind = kind
        self.version = version
        super().__init__(f'unknown {kind} edition {version} for {day!r}')


class LatestEdition(ValueError):
    def __init__(self, day: str, kind: str, version: int):
        self.day = day
        self.kind = kind
        self.version = version
        super().__init__(f'latest {kind} edition {version} for {day!r} is protected')


class HandoffEditionProtected(ValueError):
    def __init__(self, day: str, kind: str, version: int):
        self.day = day
        self.kind = kind
        self.version = version
        super().__init__(f'{kind} edition {version} for {day!r} is protected by the handoff stream')


class RetirementEligibility(Enum):
    ELIGIBLE = 'eligible'
    ALREADY_RETIRED = 'already_retired'


def check_retirement(
    conn: sqlite3.Connection, day: str, kind: str, version: int,
) -> RetirementEligibility:
    validate_identifier(day, 'day')
    validate_kind(kind)
    validate_version(version)
    require_day(conn, day)
    entry = get_availability(conn, day, kind, version)
    if entry is None:
        raise UnknownEdition(day, kind, version)
    if not entry.available:
        return RetirementEligibility.ALREADY_RETIRED

    latest, = conn.execute(
        'SELECT MAX(version) FROM edition_directory WHERE day = ? AND kind = ?',
        (day, kind),
    ).fetchone()
    if version == latest:
        raise LatestEdition(day, kind, version)

    stream = get_handoff_stream(conn, day)
    if stream is not None:
        floor = stream.fact_floor if kind == 'facts' else stream.registry_floor
        if version >= floor:
            raise HandoffEditionProtected(day, kind, version)
    return RetirementEligibility.ELIGIBLE
