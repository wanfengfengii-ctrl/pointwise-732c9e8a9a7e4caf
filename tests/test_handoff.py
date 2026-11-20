import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from facts.ingest import put_facts
from reconcile import PartitionTotal, UnmappedObservation
from reconcile.inputs import SourceEditionUnavailable
from registry.intake import put_registry
from release import ReleaseReceipt
from release.audit import read_release
from release.handoff import HandoffNumberConflict, HandoffNotRegistered, read_handoff_progress
from release.publish import publish, publish_handoff, register_handoff
from release.receipts import PublishNumberConflict
from retention.eligibility import HandoffEditionProtected, LatestEdition
from retention.history import RetirementRecord
from retention.inventory import UnknownDay, list_editions
from retention.retire import retire
from retention.store import open_store
from tests.test_publication import install_commit_failure


DAY = '东线日域'
F1 = (('A', 7, 'F1-A1'), ('A', 7, 'F1-A2'), ('A', None, 'F1-A3'))
F2 = (('C', 11, 'F2-C'),)
F3 = (('A', 13, 'F3-A'),)
F4 = (('A', 17, 'F4-A'),)
D1 = (('A', '东区', 'D1-A'), ('C', '东区', 'D1-C'))
D2 = (('B', '西区', 'D2-B'), ('C', '西区', 'D2-C'))
D3_BC = (('B', '南区', 'D3-B'), ('C', '南区', 'D3-C'))
D3_A = (('A', '北区', 'D3-A'),)


class TestHandoff(unittest.TestCase):
    def setUp(self):
        temporary = self.enterContext(TemporaryDirectory())
        self.path = Path(temporary) / 'warehouse.sqlite3'

    def load_first(self, store):
        put_facts(store, DAY, 'F1', F1)
        put_registry(store, DAY, 'D1', D1)

    def open_clash(self, store):
        put_facts(store, DAY, 'F2', F2)
        put_facts(store, DAY, 'F3', F3)
        put_registry(store, DAY, 'D2', D2)

    def test_registration_and_first_publication(self):
        with open_store(self.path) as store:
            self.load_first(store)
            self.assertIsNone(register_handoff(store, DAY))
            self.assertEqual(read_handoff_progress(store, DAY).fact_floor, 0)
            self.assertEqual(read_handoff_progress(store, DAY).registry_floor, 0)
            snapshot, receipt = publish_handoff(store, DAY, 'H1')
            self.assertEqual((snapshot.fact_version, snapshot.registry_version), (1, 1))
            self.assertEqual(receipt, ReleaseReceipt(DAY, 'H1', 1, 1))
            self.assertEqual(snapshot.totals, (PartitionTotal('东区', 14, 1),))
            self.assertEqual([(row.position, row.point, row.liters, row.observation_source, row.registry_source)
                              for row in snapshot.rows],
                             [(0, 'A', 7, 'F1-A1', 'D1-A'), (1, 'A', 7, 'F1-A2', 'D1-A'),
                              (2, 'A', None, 'F1-A3', 'D1-A')])
            self.assertEqual(read_handoff_progress(store, DAY).fact_floor, 1)
            self.assertEqual(read_handoff_progress(store, DAY).registry_floor, 1)
        with open_store(self.path) as store:
            self.assertEqual(read_release(store, DAY, 'H1'), (snapshot, receipt))
            self.assertEqual(register_handoff(store, DAY), None)
            self.assertEqual(read_handoff_progress(store, DAY).fact_floor, 1)

    def test_nonmaximal_pair_is_not_published(self):
        # Three facts and three registries produce several compatible pairs; the
        # chosen pair must be one that no other pair strictly advances past.
        with open_store(self.path) as store:
            put_facts(store, DAY, 'F1', (('A', 1, 'F1-A'),))
            put_facts(store, DAY, 'F2', (('A', 2, 'F2-A'), ('B', 2, 'F2-B')))
            put_facts(store, DAY, 'F3', (('B', 3, 'F3-B'),))
            put_registry(store, DAY, 'D1', (('A', '东区', 'D1-A'),))
            put_registry(store, DAY, 'D2', (('A', '东区', 'D2-A'), ('B', '西区', 'D2-B')))
            put_registry(store, DAY, 'D3', (('B', '西区', 'D3-B'),))
            register_handoff(store, DAY)
            # Compatible pairs: (1,1),(1,2),(2,2),(3,2),(3,3).
            # Maximal (undominated) pairs: (2,2) and (3,3) ... (3,3) advances (2,2).
            snapshot, _ = publish_handoff(store, DAY, 'H1')
            self.assertEqual((snapshot.fact_version, snapshot.registry_version), (3, 3))
            self.assertEqual(snapshot.totals, (PartitionTotal('西区', 3, 0),))

    def test_unknown_day(self):
        with open_store(self.path) as store:
            with self.assertRaises(UnknownDay):
                register_handoff(store, '未知日域')
            with self.assertRaises(HandoffNotRegistered):
                publish_handoff(store, DAY, 'H1')
            self.load_first(store)
            with self.assertRaises(HandoffNotRegistered):
                publish_handoff(store, DAY, 'H1')

    def test_maximal_pair_choice_and_wait(self):
        with open_store(self.path) as store:
            self.load_first(store)
            register_handoff(store, DAY)
            publish_handoff(store, DAY, 'H1')
            self.open_clash(store)
            # (2,2) and (3,1) are both undominated; we take the greatest fact side.
            snapshot, receipt = publish_handoff(store, DAY, 'H2')
            self.assertEqual((snapshot.fact_version, snapshot.registry_version), (3, 1))
            self.assertEqual(snapshot.totals, (PartitionTotal('东区', 13, 0),))
            self.assertEqual(read_handoff_progress(store, DAY).fact_floor, 3)
            self.assertEqual(read_handoff_progress(store, DAY).registry_floor, 1)
            # Only D3_BC arrives; F3 cannot be classified against it.
            put_registry(store, DAY, 'D3', D3_BC)
            self.assertIsNone(publish_handoff(store, DAY, 'H3'))
            self.assertEqual(read_handoff_progress(store, DAY).fact_floor, 3)
            self.assertEqual(read_handoff_progress(store, DAY).registry_floor, 1)
            with self.assertRaises(Exception):
                read_release(store, DAY, 'H3')
            # A late F4 lets the same number succeed.
            put_facts(store, DAY, 'F4', F4)
            late, late_receipt = publish_handoff(store, DAY, 'H3')
            self.assertEqual((late.fact_version, late.registry_version), (4, 1))
            self.assertEqual(late.totals, (PartitionTotal('东区', 17, 0),))
            self.assertEqual(late_receipt, ReleaseReceipt(DAY, 'H3', 4, 1))

    def test_alternative_waiting_path_resumes_on_late_registry(self):
        with open_store(self.path) as store:
            self.load_first(store)
            register_handoff(store, DAY)
            publish_handoff(store, DAY, 'H1')
            # Only F2 and D2 arrive: the sole advancing compatible pair is F2/D2.
            put_facts(store, DAY, 'F2', F2)
            put_registry(store, DAY, 'D2', D2)
            chosen, _ = publish_handoff(store, DAY, 'H2')
            self.assertEqual((chosen.fact_version, chosen.registry_version), (2, 2))
            self.assertEqual(chosen.totals, (PartitionTotal('西区', 11, 0),))
            # F3 and F4 arrive; D1 is still available but lies below the registry floor.
            put_facts(store, DAY, 'F3', F3)
            put_facts(store, DAY, 'F4', F4)
            self.assertIsNone(publish_handoff(store, DAY, 'H3'))
            # F3 is no longer latest but remains above the fact floor.
            with self.assertRaises(HandoffEditionProtected):
                retire(store, DAY, 'facts', 3)
            # D3_A arrives and the waiting number yields F4/D3.
            put_registry(store, DAY, 'D3', D3_A)
            late, receipt = publish_handoff(store, DAY, 'H3')
            self.assertEqual((late.fact_version, late.registry_version), (4, 3))
            self.assertEqual(late.totals, (PartitionTotal('北区', 17, 0),))
            self.assertEqual(receipt, ReleaseReceipt(DAY, 'H3', 4, 3))

    def test_waiting_branch_resumes_with_late_split_registry(self):
        with open_store(self.path) as store:
            self.load_first(store)
            register_handoff(store, DAY)
            publish_handoff(store, DAY, 'H1')
            put_facts(store, DAY, 'F2', F2)
            put_registry(store, DAY, 'D2', D2)
            publish_handoff(store, DAY, 'H2')  # F2/D2, south partition arrives later.
            put_facts(store, DAY, 'F3', F3)
            put_facts(store, DAY, 'F4', F4)
            self.assertIsNone(publish_handoff(store, DAY, 'H3'))
            put_registry(store, DAY, 'D3', D3_BC)
            late, receipt = publish_handoff(store, DAY, 'H3')
            # F3/F4 need point A, which D3_BC lacks; F2 stays above the floor.
            self.assertEqual((late.fact_version, late.registry_version), (2, 3))
            self.assertEqual(late.totals, (PartitionTotal('南区', 11, 0),))
            self.assertEqual(receipt, ReleaseReceipt(DAY, 'H3', 2, 3))

    def test_retirement_boundary(self):
        with open_store(self.path) as store:
            self.load_first(store)
            register_handoff(store, DAY)
            # The sole edition is still latest, so the V1 rule reports first.
            for kind in ('facts', 'registry'):
                with self.assertRaises(LatestEdition):
                    retire(store, DAY, kind, 1)
            put_facts(store, DAY, 'F2', F2)
            put_registry(store, DAY, 'D2', D2)
            # F1 is incompatible with the current D2 yet sits at the zero floor.
            with self.assertRaises(UnmappedObservation):
                publish(store, DAY, 'manual-bad', 1, 2)
            for kind, version in (('facts', 1), ('registry', 1)):
                with self.assertRaises(HandoffEditionProtected):
                    retire(store, DAY, kind, version)
            chosen, _ = publish_handoff(store, DAY, 'H1')
            self.assertEqual((chosen.fact_version, chosen.registry_version), (2, 2))
            # Strictly below both floors: eligible; exactly at a floor: protected.
            self.assertEqual(retire(store, DAY, 'facts', 1), RetirementRecord(DAY, 'facts', 1))
            self.assertEqual(retire(store, DAY, 'facts', 1), RetirementRecord(DAY, 'facts', 1))
            self.assertEqual(retire(store, DAY, 'registry', 1), RetirementRecord(DAY, 'registry', 1))
            with self.assertRaises(LatestEdition):
                retire(store, DAY, 'facts', 2)
            with self.assertRaises(LatestEdition):
                retire(store, DAY, 'registry', 2)
        with open_store(self.path) as store:
            self.assertEqual([(entry.version, entry.available) for entry in list_editions(store, DAY, 'facts')],
                             [(1, False), (2, True)])

    def test_number_space_is_shared(self):
        with open_store(self.path) as store:
            self.load_first(store)
            register_handoff(store, DAY)
            manual = publish(store, DAY, 'P1', 1, 1)
            with self.assertRaises(HandoffNumberConflict):
                publish_handoff(store, DAY, 'P1')
            self.assertEqual(read_release(store, DAY, 'P1'), manual)
            handoff = publish_handoff(store, DAY, 'H1')
            with self.assertRaises(HandoffNumberConflict):
                publish(store, DAY, 'H1', 1, 1)
            self.assertEqual(read_release(store, DAY, 'H1'), handoff)
            # A handoff replay ignores the proposed pair and returns the fixed ledger.
            self.open_clash(store)
            self.assertEqual(publish_handoff(store, DAY, 'H1'), handoff)
        with open_store(self.path) as store:
            self.assertEqual(read_handoff_progress(store, DAY).fact_floor, 1)
            self.assertEqual(read_handoff_progress(store, DAY).registry_floor, 1)

    def test_manual_does_not_advance_floor(self):
        with open_store(self.path) as store:
            self.load_first(store)
            register_handoff(store, DAY)
            first = publish(store, DAY, 'P1', 1, 1)
            self.assertEqual((read_handoff_progress(store, DAY).fact_floor,
                              read_handoff_progress(store, DAY).registry_floor), (0, 0))
            self.assertEqual(publish(store, DAY, 'P1', 1, 1), first)
            with self.assertRaises(PublishNumberConflict):
                publish(store, DAY, 'P1', 1, 2)
            self.assertEqual((read_handoff_progress(store, DAY).fact_floor,
                              read_handoff_progress(store, DAY).registry_floor), (0, 0))

    def test_commit_failure_rolls_back_floor_and_number(self):
        with open_store(self.path) as store:
            self.load_first(store)
            register_handoff(store, DAY)
            with store.write_transaction() as conn:
                install_commit_failure(conn)
            with self.assertRaisesRegex(Exception, 'FOREIGN KEY constraint failed'):
                publish_handoff(store, DAY, 'H1')
            self.assertEqual((read_handoff_progress(store, DAY).fact_floor,
                              read_handoff_progress(store, DAY).registry_floor), (0, 0))
            for kind, version in (('facts', 1), ('registry', 1)):
                with self.assertRaises((HandoffEditionProtected, LatestEdition)):
                    retire(store, DAY, kind, version)
        with open_store(self.path) as store:
            self.assertEqual((read_handoff_progress(store, DAY).fact_floor,
                              read_handoff_progress(store, DAY).registry_floor), (0, 0))
            snapshot, receipt = publish_handoff(store, DAY, 'H1')
            self.assertEqual((snapshot.fact_version, snapshot.registry_version), (1, 1))
            self.assertEqual(read_handoff_progress(store, DAY).fact_floor, 1)


if __name__ == '__main__':
    unittest.main()
