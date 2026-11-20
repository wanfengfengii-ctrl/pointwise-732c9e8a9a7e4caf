"""Feed the two independent source chains and show the limits of V1."""
import json

from facts.ingest import put_facts
from reconcile.discrepancies import UnmappedObservation
from reconcile.inputs import SourceEditionUnavailable
from reconcile.preview import preview
from registry.intake import put_registry
from release.audit import read_release
from release.publish import publish
from retention.retire import retire
from retention.store import open_store


DAY = "东线日域"
F1 = (("A", 7, "F1-A1"), ("A", 7, "F1-A2"), ("A", None, "F1-A3"))
F2 = (("C", 11, "F2-C"),)
F3 = (("A", 13, "F3-A"),)
F4 = (("A", 17, "F4-A"),)
D1 = (("A", "东区", "D1-A"), ("C", "东区", "D1-C"))
D2 = (("B", "西区", "D2-B"), ("C", "西区", "D2-C"))
D3_BC = (("B", "南区", "D3-B"), ("C", "南区", "D3-C"))
D3_A = (("A", "北区", "D3-A"),)


def load_first(store):
    put_facts(store, DAY, "F1", F1)
    put_registry(store, DAY, "D1", D1)


def load_clash(store):
    put_facts(store, DAY, "F2", F2)
    put_facts(store, DAY, "F3", F3)
    put_registry(store, DAY, "D2", D2)


def inspect_v1(arrival):
    with open_store(":memory:") as store:
        load_first(store)
        initial = publish(store, DAY, "V1-first", 1, 1)
        load_clash(store)
        try:
            preview(store, DAY, 3, 2)
        except UnmappedObservation as error:
            if (error.position, error.point) != (0, "A"):
                raise
        else:
            raise AssertionError("F3/D2 should miss A")

        alternatives = [preview(store, DAY, 3, 1), preview(store, DAY, 2, 2)]
        if arrival == "F4":
            put_facts(store, DAY, "F4", F4)
            versions, kind, old_version = (4, 1), "registry", 1
        elif arrival == "D3":
            put_registry(store, DAY, "D3", D3_BC)
            versions, kind, old_version = (2, 3), "facts", 2
        else:
            raise ValueError("arrival must be F4 or D3")

        fixed = publish(store, DAY, "V1-next", *versions)
        retire(store, DAY, kind, old_version)
        try:
            preview(store, DAY, *versions)
        except SourceEditionUnavailable as error:
            if (error.kind, error.version, error.status) != (kind, old_version, "retired"):
                raise
        else:
            raise AssertionError("retired input should prevent a new preview")
        if read_release(store, DAY, "V1-first") != initial or read_release(store, DAY, "V1-next") != fixed:
            raise AssertionError("a frozen V1 release changed after retirement")

    return {
        "arrival": arrival,
        "latest_missing_point": "A",
        "manual_alternatives": [(trial.fact_version, trial.registry_version) for trial in alternatives],
        "lost_new_preview": versions,
        "retired": (kind, old_version),
        "frozen_totals_liters": [total.liters for total in fixed[0].totals],
    }


def main():
    for arrival in ("F4", "D3"):
        print(json.dumps(inspect_v1(arrival), ensure_ascii=False))


if __name__ == "__main__":
    main()
