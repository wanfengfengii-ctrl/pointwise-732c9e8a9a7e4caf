import sqlite3
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ReleaseReceipt:
    day: str
    number: str
    fact_version: int
    registry_version: int


class PublishNumberConflict(ValueError):
    def __init__(self, receipt: ReleaseReceipt):
        self.receipt = receipt
        super().__init__(f'publication {receipt.number!r} for {receipt.day!r} already uses different editions')


def lookup_release_receipt(conn: sqlite3.Connection, day: str, number: str) -> ReleaseReceipt | None:
    record = conn.execute(
        '''SELECT snapshot.fact_version, snapshot.registry_version
           FROM release_receipts AS receipt
           JOIN release_snapshots AS snapshot USING(day, number)
           WHERE receipt.day = ? AND receipt.number = ?''',
        (day, number),
    ).fetchone()
    if record is None:
        return None
    return ReleaseReceipt(day, number, *record)


def match_release_request(
    conn: sqlite3.Connection, day: str, number: str, fact_version: int, registry_version: int,
) -> ReleaseReceipt | None:
    receipt = lookup_release_receipt(conn, day, number)
    if receipt is not None and (receipt.fact_version, receipt.registry_version) != (fact_version, registry_version):
        raise PublishNumberConflict(receipt)
    return receipt


def store_release_receipt(conn: sqlite3.Connection, day: str, number: str) -> None:
    conn.execute('INSERT INTO release_receipts(day, number) VALUES (?, ?)', (day, number))
