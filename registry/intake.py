from collections.abc import Iterable, Sequence

from retention.inventory import ensure_day, register_available
from retention.store import DayStore, validate_identifier

from .assignments import normalize_assignments
from .editions import append_registry_edition
from .receipts import (
    RegistryReceipt,
    RegistryRequestConflict,
    canonical_registry_request,
    get_registry_receipt,
    record_registry_receipt,
)


def put_registry(
    store: DayStore, day: str, request_id: str, entries: Iterable[Sequence[object]],
) -> RegistryReceipt:
    validate_identifier(day, 'day')
    validate_identifier(request_id, 'request_id')
    assignments = normalize_assignments(entries)
    content = canonical_registry_request(assignments)
    with store.write_transaction() as conn:
        previous = get_registry_receipt(conn, day, request_id)
        if previous is not None:
            receipt, original = previous
            if original != content:
                raise RegistryRequestConflict(day, request_id)
            return receipt

        ensure_day(conn, day)
        edition = append_registry_edition(conn, day, assignments)
        register_available(conn, day, 'registry', edition.version)
        receipt = RegistryReceipt(day, request_id, edition.version)
        record_registry_receipt(conn, receipt, content)
    return receipt
