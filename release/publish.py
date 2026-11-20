from reconcile.preview import calculate_preview
from retention.store import DayStore, validate_identifier, validate_version

from .audit import read_committed_release
from .receipts import ReleaseReceipt, match_release_request, store_release_receipt
from .snapshots import ReleaseSnapshot, store_snapshot


def publish(
    store: DayStore, day: str, number: str, fact_version: int, registry_version: int,
) -> tuple[ReleaseSnapshot, ReleaseReceipt]:
    validate_identifier(day, 'day')
    validate_identifier(number, 'number')
    validate_version(fact_version)
    validate_version(registry_version)
    with store.write_transaction() as conn:
        receipt = match_release_request(conn, day, number, fact_version, registry_version)
        if receipt is not None:
            return read_committed_release(conn, day, number)

        result = calculate_preview(conn, day, fact_version, registry_version)
        snapshot = ReleaseSnapshot(day, number, fact_version, registry_version, result.rows, result.totals)
        store_snapshot(conn, snapshot)
        store_release_receipt(conn, day, number)
        receipt = ReleaseReceipt(day, number, fact_version, registry_version)
    return snapshot, receipt
