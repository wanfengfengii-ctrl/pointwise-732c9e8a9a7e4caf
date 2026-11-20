import sqlite3
from dataclasses import dataclass

from retention.store import DayStore

from .classify import ClassifiedRow, classify_rows
from .inputs import load_pair
from .totals import PartitionTotal, summarize_partitions


@dataclass(frozen=True, slots=True)
class Preview:
    day: str
    fact_version: int
    registry_version: int
    rows: tuple[ClassifiedRow, ...]
    totals: tuple[PartitionTotal, ...]


def calculate_preview(conn: sqlite3.Connection, day: str, fact_version: int, registry_version: int) -> Preview:
    inputs = load_pair(conn, day, fact_version, registry_version)
    rows = classify_rows(inputs)
    return Preview(day, fact_version, registry_version, rows, summarize_partitions(rows))


def preview(store: DayStore, day: str, fact_version: int, registry_version: int) -> Preview:
    with store.read_transaction() as conn:
        return calculate_preview(conn, day, fact_version, registry_version)
