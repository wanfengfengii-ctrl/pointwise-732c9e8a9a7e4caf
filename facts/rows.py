from collections.abc import Iterable, Mapping, Sequence, Set
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class FactRow:
    position: int
    point: str
    liters: int | None
    source: str


def normalize_fact_rows(rows: Iterable[Sequence[object]]) -> tuple[FactRow, ...]:
    if isinstance(rows, (str, bytes, bytearray, Mapping, Set)):
        raise ValueError('observations must be an ordered iterable of rows')
    try:
        iterator = iter(rows)
    except TypeError as exc:
        raise ValueError('observations must be an ordered iterable of rows') from exc

    result = []
    for position, row in enumerate(iterator):
        if not isinstance(row, Sequence) or isinstance(row, (str, bytes, bytearray)) or len(row) != 3:
            raise ValueError(f'observation {position} must contain point, liters and source')
        point, liters, source = row
        if not isinstance(point, str) or not point.strip():
            raise ValueError(f'observation {position} requires a point')
        if liters is not None and type(liters) is not int:
            raise ValueError(f'observation {position} liters must be an integer or None')
        if not isinstance(source, str) or not source.strip():
            raise ValueError(f'observation {position} requires a source')
        point.encode('utf-8')
        source.encode('utf-8')
        result.append(FactRow(position, point, liters, source))
    return tuple(result)


def encode_liters(value: int | None) -> str | None:
    """Use signed hexadecimal text for exact SQLite storage at any integer size."""
    return None if value is None else format(value, 'x')


def decode_liters(value: str | None) -> int | None:
    return None if value is None else int(value, 16)
