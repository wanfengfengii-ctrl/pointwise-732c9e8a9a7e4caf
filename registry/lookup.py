import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from .assignments import Assignment
from .editions import load_registry_assignments


@dataclass(frozen=True, slots=True)
class RegistryLookup:
    by_point: Mapping[str, Assignment]

    def find(self, point: str) -> Assignment | None:
        return self.by_point.get(point)


def load_registry_lookup(conn: sqlite3.Connection, day: str, version: int) -> RegistryLookup:
    assignments = load_registry_assignments(conn, day, version)
    return RegistryLookup(MappingProxyType({entry.point: entry for entry in assignments}))
