from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Assignment:
    point: str
    partition: str
    source: str


class DuplicatePoint(ValueError):
    def __init__(self, point: str):
        self.point = point
        super().__init__(f'duplicate registry point {point!r}')


def normalize_assignments(entries: Iterable[Sequence[object]]) -> tuple[Assignment, ...]:
    if isinstance(entries, (str, bytes, bytearray, Mapping)):
        raise ValueError('registry must be an iterable of entries')
    try:
        iterator = iter(entries)
    except TypeError as exc:
        raise ValueError('registry must be an iterable of entries') from exc

    assignments = {}
    for position, entry in enumerate(iterator):
        if not isinstance(entry, Sequence) or isinstance(entry, (str, bytes, bytearray)) or len(entry) != 3:
            raise ValueError(f'registry entry {position} must contain point, partition and source')
        point, partition, source = entry
        for label, value in zip(('point', 'partition', 'source'), entry):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f'registry entry {position} requires {label}')
            value.encode('utf-8')
        if point in assignments:
            raise DuplicatePoint(point)
        assignments[point] = Assignment(point, partition, source)
    return tuple(assignments[point] for point in sorted(assignments))
