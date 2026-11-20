from collections.abc import Iterable
from dataclasses import dataclass

from .classify import ClassifiedRow


@dataclass(frozen=True, slots=True)
class PartitionTotal:
    partition: str
    liters: int
    missing: int


def summarize_partitions(rows: Iterable[ClassifiedRow]) -> tuple[PartitionTotal, ...]:
    totals: dict[str, tuple[int, int]] = {}
    for row in rows:
        liters, missing = totals.get(row.partition, (0, 0))
        if row.liters is None:
            missing += 1
        else:
            liters += row.liters
        totals[row.partition] = (liters, missing)
    return tuple(PartitionTotal(partition, *totals[partition]) for partition in sorted(totals))
