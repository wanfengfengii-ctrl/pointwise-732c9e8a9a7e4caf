import json
import sqlite3
from dataclasses import dataclass

from .rows import FactRow, encode_liters


@dataclass(frozen=True, slots=True)
class FactReceipt:
    day: str
    request_id: str
    version: int


class FactRequestConflict(ValueError):
    def __init__(self, day: str, request_id: str):
        self.day = day
        self.request_id = request_id
        super().__init__(f'observation request {request_id!r} for {day!r} has different content')


def canonical_fact_request(rows: tuple[FactRow, ...]) -> str:
    return json.dumps(
        [(row.point, encode_liters(row.liters), row.source) for row in rows],
        ensure_ascii=False,
        separators=(',', ':'),
    )


def get_fact_receipt(
    conn: sqlite3.Connection, day: str, request_id: str,
) -> tuple[FactReceipt, str] | None:
    record = conn.execute(
        'SELECT version, content FROM fact_receipts WHERE day = ? AND request_id = ?',
        (day, request_id),
    ).fetchone()
    if record is None:
        return None
    version, content = record
    return FactReceipt(day, request_id, version), content


def record_fact_receipt(conn: sqlite3.Connection, receipt: FactReceipt, content: str) -> None:
    conn.execute(
        'INSERT INTO fact_receipts(day, request_id, version, content) VALUES (?, ?, ?, ?)',
        (receipt.day, receipt.request_id, receipt.version, content),
    )
