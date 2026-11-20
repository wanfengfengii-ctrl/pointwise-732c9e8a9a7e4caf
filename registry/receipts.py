import json
import sqlite3
from dataclasses import dataclass

from .assignments import Assignment


@dataclass(frozen=True, slots=True)
class RegistryReceipt:
    day: str
    request_id: str
    version: int


class RegistryRequestConflict(ValueError):
    def __init__(self, day: str, request_id: str):
        self.day = day
        self.request_id = request_id
        super().__init__(f'registry request {request_id!r} for {day!r} has different content')


def canonical_registry_request(assignments: tuple[Assignment, ...]) -> str:
    entries = sorted((entry.point, entry.partition, entry.source) for entry in assignments)
    return json.dumps(entries, ensure_ascii=False, separators=(',', ':'))


def get_registry_receipt(
    conn: sqlite3.Connection, day: str, request_id: str,
) -> tuple[RegistryReceipt, str] | None:
    record = conn.execute(
        'SELECT version, content FROM registry_receipts WHERE day = ? AND request_id = ?',
        (day, request_id),
    ).fetchone()
    if record is None:
        return None
    version, content = record
    return RegistryReceipt(day, request_id, version), content


def record_registry_receipt(conn: sqlite3.Connection, receipt: RegistryReceipt, content: str) -> None:
    conn.execute(
        'INSERT INTO registry_receipts(day, request_id, version, content) VALUES (?, ?, ?, ?)',
        (receipt.day, receipt.request_id, receipt.version, content),
    )
