import sqlite3

from retention.store import DayStore, validate_identifier

from .receipts import ReleaseReceipt, lookup_release_receipt
from .snapshots import ReleaseSnapshot, load_snapshot


class ReleaseNotFound(LookupError):
    def __init__(self, day: str, number: str):
        self.day = day
        self.number = number
        super().__init__(f'publication {number!r} for {day!r} was not found')


def read_committed_release(
    conn: sqlite3.Connection, day: str, number: str,
) -> tuple[ReleaseSnapshot, ReleaseReceipt]:
    receipt = lookup_release_receipt(conn, day, number)
    if receipt is None:
        raise ReleaseNotFound(day, number)
    snapshot = load_snapshot(conn, day, number)
    if snapshot is None:
        raise sqlite3.IntegrityError('release receipt has no snapshot')
    return snapshot, receipt


def read_release(store: DayStore, day: str, number: str) -> tuple[ReleaseSnapshot, ReleaseReceipt]:
    validate_identifier(day, 'day')
    validate_identifier(number, 'number')
    with store.read_transaction() as conn:
        return read_committed_release(conn, day, number)
