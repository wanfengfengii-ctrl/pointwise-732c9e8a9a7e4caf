from dataclasses import dataclass

from .discrepancies import UnmappedObservation
from .inputs import SelectedInputs


@dataclass(frozen=True, slots=True)
class ClassifiedRow:
    position: int
    point: str
    liters: int | None
    partition: str
    observation_source: str
    registry_source: str


def classify_rows(inputs: SelectedInputs) -> tuple[ClassifiedRow, ...]:
    classified = []
    for row in inputs.observations:
        assignment = inputs.registry.find(row.point)
        if assignment is None:
            raise UnmappedObservation.from_row(inputs.day, inputs.fact_version, inputs.registry_version, row)
        classified.append(ClassifiedRow(
            row.position, row.point, row.liters, assignment.partition, row.source, assignment.source,
        ))
    return tuple(classified)
