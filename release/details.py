import sqlite3

from facts.rows import decode_liters, encode_liters
from reconcile.classify import ClassifiedRow


def store_release_details(
    conn: sqlite3.Connection, day: str, number: str, rows: tuple[ClassifiedRow, ...],
) -> None:
    conn.executemany(
        '''INSERT INTO release_details(
               day, number, position, point, liters, partition, observation_source, registry_source
           ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
        ((day, number, row.position, row.point, encode_liters(row.liters), row.partition,
          row.observation_source, row.registry_source) for row in rows),
    )


def load_release_details(conn: sqlite3.Connection, day: str, number: str) -> tuple[ClassifiedRow, ...]:
    rows = conn.execute(
        '''SELECT position, point, liters, partition, observation_source, registry_source
           FROM release_details WHERE day = ? AND number = ? ORDER BY position''',
        (day, number),
    )
    return tuple(
        ClassifiedRow(position, point, decode_liters(liters), partition, observation_source, registry_source)
        for position, point, liters, partition, observation_source, registry_source in rows
    )
