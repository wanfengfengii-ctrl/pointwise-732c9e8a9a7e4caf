from collections.abc import Iterable, Sequence

from retention.inventory import ensure_day, register_available
from retention.store import DayStore, validate_identifier

from .editions import append_fact_edition
from .receipts import (
    FactReceipt,
    FactRequestConflict,
    canonical_fact_request,
    get_fact_receipt,
    record_fact_receipt,
)
from .rows import normalize_fact_rows


def put_facts(
    store: DayStore, day: str, request_id: str, rows: Iterable[Sequence[object]],
) -> FactReceipt:
    validate_identifier(day, 'day')
    validate_identifier(request_id, 'request_id')
    observations = normalize_fact_rows(rows)
    content = canonical_fact_request(observations)
    with store.write_transaction() as conn:
        previous = get_fact_receipt(conn, day, request_id)
        if previous is not None:
            receipt, original = previous
            if original != content:
                raise FactRequestConflict(day, request_id)
            return receipt

        ensure_day(conn, day)
        edition = append_fact_edition(conn, day, observations)
        register_available(conn, day, 'facts', edition.version)
        receipt = FactReceipt(day, request_id, edition.version)
        record_fact_receipt(conn, receipt, content)
    return receipt
