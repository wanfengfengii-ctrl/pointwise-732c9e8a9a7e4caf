import sqlite3

from facts.editions import remove_fact_payload
from registry.editions import remove_registry_payload

from .eligibility import RetirementEligibility, check_retirement
from .history import RetirementRecord, get_retirement, record_retirement
from .inventory import mark_retired
from .store import DayStore


def retire(store: DayStore, day: str, kind: str, version: int) -> RetirementRecord:
    with store.write_transaction() as conn:
        eligibility = check_retirement(conn, day, kind, version)
        if eligibility is RetirementEligibility.ALREADY_RETIRED:
            record = get_retirement(conn, day, kind, version)
            if record is None:
                raise sqlite3.IntegrityError('retired edition has no retirement record')
            return record

        if kind == 'facts':
            remove_fact_payload(conn, day, version)
        else:
            remove_registry_payload(conn, day, version)
        mark_retired(conn, day, kind, version)
        record = record_retirement(conn, day, kind, version)
    return record
