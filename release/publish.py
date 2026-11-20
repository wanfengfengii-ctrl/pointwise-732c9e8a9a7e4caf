from reconcile.preview import calculate_preview
from retention.inventory import require_day
from retention.store import DayStore, validate_identifier, validate_version

from .audit import read_committed_release
from .handoff import (
    HandoffNumberConflict,
    HandoffNotRegistered,
    advance_handoff,
    choose_handoff_pair,
    get_handoff_stream,
    publication_origin,
    register_handoff_stream,
)
from .receipts import ReleaseReceipt, match_release_request, store_handoff_receipt, store_release_receipt
from .snapshots import ReleaseSnapshot, store_snapshot


def _require_registered(conn, day: str):
    stream = get_handoff_stream(conn, day)
    if stream is None:
        raise HandoffNotRegistered(day)
    return stream


def register_handoff(store: DayStore, day: str) -> None:
    validate_identifier(day, 'day')
    with store.write_transaction() as conn:
        require_day(conn, day)
        register_handoff_stream(conn, day)


def publish(
    store: DayStore, day: str, number: str, fact_version: int, registry_version: int,
) -> tuple[ReleaseSnapshot, ReleaseReceipt]:
    validate_identifier(day, 'day')
    validate_identifier(number, 'number')
    validate_version(fact_version)
    validate_version(registry_version)
    with store.write_transaction() as conn:
        if publication_origin(conn, day, number) == 'handoff':
            raise HandoffNumberConflict(day, number)

        receipt = match_release_request(conn, day, number, fact_version, registry_version)
        if receipt is not None:
            return read_committed_release(conn, day, number)

        result = calculate_preview(conn, day, fact_version, registry_version)
        snapshot = ReleaseSnapshot(day, number, fact_version, registry_version, result.rows, result.totals)
        store_snapshot(conn, snapshot)
        store_release_receipt(conn, day, number)
        receipt = ReleaseReceipt(day, number, fact_version, registry_version)
    return snapshot, receipt


def publish_handoff(
    store: DayStore, day: str, number: str,
) -> tuple[ReleaseSnapshot, ReleaseReceipt] | None:
    validate_identifier(day, 'day')
    validate_identifier(number, 'number')
    with store.write_transaction() as conn:
        stream = _require_registered(conn, day)

        origin = publication_origin(conn, day, number)
        if origin == 'handoff':
            return read_committed_release(conn, day, number)
        if origin is not None:
            raise HandoffNumberConflict(day, number)

        pair = choose_handoff_pair(conn, day, stream)
        if pair is None:
            return None
        fact_version, registry_version = pair

        result = calculate_preview(conn, day, fact_version, registry_version)
        snapshot = ReleaseSnapshot(day, number, fact_version, registry_version, result.rows, result.totals)
        store_snapshot(conn, snapshot)
        store_handoff_receipt(conn, day, number)
        receipt = ReleaseReceipt(day, number, fact_version, registry_version)
        advance_handoff(conn, day, fact_version, registry_version)
    return snapshot, receipt
