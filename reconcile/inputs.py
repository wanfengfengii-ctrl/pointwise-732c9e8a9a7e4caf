import sqlite3
from dataclasses import dataclass

from facts.editions import load_fact_rows
from facts.rows import FactRow
from registry.lookup import RegistryLookup, load_registry_lookup
from retention.inventory import get_availability
from retention.store import validate_identifier, validate_version


@dataclass(frozen=True, slots=True)
class SelectedInputs:
    day: str
    fact_version: int
    registry_version: int
    observations: tuple[FactRow, ...]
    registry: RegistryLookup


class SourceEditionUnavailable(LookupError):
    def __init__(self, day: str, kind: str, version: int, status: str):
        self.day = day
        self.kind = kind
        self.version = version
        self.status = status
        super().__init__(f'{kind} edition {version} for {day!r} is {status}')


def load_pair(conn: sqlite3.Connection, day: str, fact_version: int, registry_version: int) -> SelectedInputs:
    validate_identifier(day, 'day')
    validate_version(fact_version)
    validate_version(registry_version)
    for kind, version in (('facts', fact_version), ('registry', registry_version)):
        entry = get_availability(conn, day, kind, version)
        if entry is None:
            raise SourceEditionUnavailable(day, kind, version, 'missing')
        if not entry.available:
            raise SourceEditionUnavailable(day, kind, version, 'retired')
    return SelectedInputs(
        day,
        fact_version,
        registry_version,
        load_fact_rows(conn, day, fact_version),
        load_registry_lookup(conn, day, registry_version),
    )
