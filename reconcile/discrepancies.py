from facts.rows import FactRow


class UnmappedObservation(ValueError):
    def __init__(
        self, day: str, fact_version: int, registry_version: int, position: int, point: str, source: str,
    ):
        self.day = day
        self.fact_version = fact_version
        self.registry_version = registry_version
        self.position = position
        self.point = point
        self.source = source
        super().__init__(
            f'{day!r} F{fact_version}/D{registry_version} observation {position} '
            f'from {source!r} has unmapped point {point!r}'
        )

    @classmethod
    def from_row(cls, day: str, fact_version: int, registry_version: int, row: FactRow) -> 'UnmappedObservation':
        return cls(day, fact_version, registry_version, row.position, row.point, row.source)

    def as_report(self) -> dict[str, str | int]:
        return {
            'day': self.day,
            'fact_version': self.fact_version,
            'registry_version': self.registry_version,
            'position': self.position,
            'point': self.point,
            'source': self.source,
        }
