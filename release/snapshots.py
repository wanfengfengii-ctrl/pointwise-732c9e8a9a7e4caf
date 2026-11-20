import sqlite3
from dataclasses import dataclass

from facts.rows import encode_liters
from reconcile.classify import ClassifiedRow
from reconcile.totals import PartitionTotal

from .details import load_release_details, store_release_details


@dataclass(frozen=True, slots=True)
class ReleaseSnapshot:
    day: str
    number: str
    fact_version: int
    registry_version: int
    rows: tuple[ClassifiedRow, ...]
    totals: tuple[PartitionTotal, ...]


def store_snapshot(conn: sqlite3.Connection, snapshot: ReleaseSnapshot) -> None:
    day, number = snapshot.day, snapshot.number
    conn.execute(
        '''INSERT INTO release_snapshots(day, number, fact_version, registry_version)
           VALUES (?, ?, ?, ?)''',
        (day, number, snapshot.fact_version, snapshot.registry_version),
    )
    store_release_details(conn, day, number, snapshot.rows)
    conn.executemany(
        '''INSERT INTO release_totals(day, number, partition, liters, missing)
           VALUES (?, ?, ?, ?, ?)''',
        ((day, number, total.partition, encode_liters(total.liters), total.missing)
         for total in snapshot.totals),
    )


def load_snapshot(conn: sqlite3.Connection, day: str, number: str) -> ReleaseSnapshot | None:
    header = conn.execute(
        'SELECT fact_version, registry_version FROM release_snapshots WHERE day = ? AND number = ?',
        (day, number),
    ).fetchone()
    if header is None:
        return None
    fact_version, registry_version = header
    totals = conn.execute(
        '''SELECT partition, liters, missing FROM release_totals
           WHERE day = ? AND number = ? ORDER BY partition''',
        (day, number),
    )
    return ReleaseSnapshot(
        day,
        number,
        fact_version,
        registry_version,
        load_release_details(conn, day, number),
        tuple(PartitionTotal(partition, int(liters, 16), missing) for partition, liters, missing in totals),
    )
