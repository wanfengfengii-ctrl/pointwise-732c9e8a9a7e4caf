import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from facts.ingest import put_facts
from reconcile import PartitionTotal
from reconcile.classify import ClassifiedRow
from reconcile.inputs import SourceEditionUnavailable
from reconcile.preview import preview
from registry.intake import put_registry
from release import ReleaseReceipt
from release.audit import ReleaseNotFound, read_release
from release.publish import publish
from release.receipts import PublishNumberConflict
from retention.eligibility import LatestEdition, UnknownEdition
from retention.history import RetirementRecord, get_retirement
from retention.inventory import EditionAvailability, InvalidSourceKind, UnknownDay, list_editions
from retention.retire import retire
from retention.store import open_store


DAY = '东线日域'
OLD_ROWS = (('A', 7, '现场1'), ('A', 7, '现场2'), ('B', None, '现场3'))
OLD_REGISTRY = (('A', '东区', '东区A'), ('B', '东区', '东区B'))
NEW_ROWS = (('A', 9, '更正1'), ('B', 0, '更正2'))
NEW_REGISTRY = (('A', '西区', '西区A'), ('B', '东区', '东区B'))


class TestRetention(unittest.TestCase):
    def setUp(self):
        temporary = self.enterContext(TemporaryDirectory())
        self.path = Path(temporary) / 'warehouse.sqlite3'

    def load_old_pair(self, store):
        put_facts(store, DAY, 'R1', OLD_ROWS)
        put_registry(store, DAY, 'C1', OLD_REGISTRY)

    def load_new_pair(self, store):
        put_facts(store, DAY, 'R2', NEW_ROWS)
        put_registry(store, DAY, 'C2', NEW_REGISTRY)

    def test_archived_input_historical_release(self):
        with open_store(self.path) as store:
            self.load_old_pair(store)
            original = publish(store, DAY, 'P1', 1, 1)
            self.load_new_pair(store)
            self.assertEqual(retire(store, DAY, 'facts', 1), RetirementRecord(DAY, 'facts', 1))
            self.assertEqual(retire(store, DAY, 'registry', 1), RetirementRecord(DAY, 'registry', 1))
        with open_store(self.path) as store:
            for kind in ('facts', 'registry'):
                self.assertEqual(list_editions(store, DAY, kind), (
                    EditionAvailability(DAY, kind, 1, False), EditionAvailability(DAY, kind, 2, True),
                ))
            with self.assertRaises(SourceEditionUnavailable):
                preview(store, DAY, 1, 2)
            snapshot, receipt = read_release(store, DAY, 'P1')
            self.assertEqual((snapshot, receipt), original)
            self.assertEqual(receipt, ReleaseReceipt(DAY, 'P1', 1, 1))
            self.assertEqual(snapshot.rows, (
                ClassifiedRow(0, 'A', 7, '东区', '现场1', '东区A'),
                ClassifiedRow(1, 'A', 7, '东区', '现场2', '东区A'),
                ClassifiedRow(2, 'B', None, '东区', '现场3', '东区B'),
            ))
            self.assertEqual(snapshot.totals, (PartitionTotal('东区', 14, 1),))

    def test_archived_gate(self):
        with open_store(self.path) as store:
            self.load_old_pair(store)
            self.load_new_pair(store)
            retire(store, DAY, 'facts', 1)
            retire(store, DAY, 'registry', 1)
        with open_store(self.path) as store:
            for fact_version, registry_version, expected in (
                (1, 2, ('facts', 1, 'retired')),
                (2, 1, ('registry', 1, 'retired')),
                (99, 2, ('facts', 99, 'missing')),
                (2, 99, ('registry', 99, 'missing')),
            ):
                with self.subTest(pair=(fact_version, registry_version)):
                    with self.assertRaises(SourceEditionUnavailable) as trial:
                        preview(store, DAY, fact_version, registry_version)
                    with self.assertRaises(SourceEditionUnavailable) as publication:
                        publish(store, DAY, 'new', fact_version, registry_version)
                    for error in (trial.exception, publication.exception):
                        self.assertEqual((error.kind, error.version, error.status), expected)
                    with self.assertRaises(ReleaseNotFound):
                        read_release(store, DAY, 'new')
            self.assertEqual(publish(store, DAY, 'new', 2, 2)[0].totals,
                             (PartitionTotal('东区', 0, 0), PartitionTotal('西区', 9, 0)))

    def test_archived_replay(self):
        with open_store(self.path) as store:
            self.load_old_pair(store)
            original = publish(store, DAY, 'P1', 1, 1)
            self.load_new_pair(store)
            retire(store, DAY, 'facts', 1)
            retire(store, DAY, 'registry', 1)
        with open_store(self.path) as store:
            self.assertEqual(publish(store, DAY, 'P1', 1, 1), original)
            with self.assertRaises(PublishNumberConflict):
                publish(store, DAY, 'P1', 2, 2)
            self.assertEqual(read_release(store, DAY, 'P1'), original)

    def test_retire_replay(self):
        with open_store(self.path) as store:
            self.load_old_pair(store)
            self.load_new_pair(store)
            records = {kind: retire(store, DAY, kind, 1) for kind in ('facts', 'registry')}
            self.assertEqual(retire(store, DAY, 'facts', 1), records['facts'])
        with open_store(self.path) as store:
            for kind, record in records.items():
                self.assertEqual(retire(store, DAY, kind, 1), record)
            with store.read_transaction() as conn:
                self.assertEqual(get_retirement(conn, DAY, 'facts', 1), records['facts'])
                self.assertEqual(get_retirement(conn, DAY, 'registry', 1), records['registry'])
                self.assertEqual(conn.execute('SELECT COUNT(*) FROM retirements WHERE day = ?', (DAY,)).fetchone(), (2,))
                for table in ('fact_rows', 'registry_assignments'):
                    self.assertEqual(conn.execute(f'SELECT COUNT(*) FROM {table} WHERE day = ? AND version = 1',
                                                  (DAY,)).fetchone(), (0,))
                for table in ('fact_editions', 'fact_receipts', 'registry_editions', 'registry_receipts'):
                    self.assertEqual(conn.execute(f'SELECT COUNT(*) FROM {table} WHERE day = ? AND version = 1',
                                                  (DAY,)).fetchone(), (1,))

    def test_active_latest_protection(self):
        with open_store(self.path) as store:
            self.load_old_pair(store)
            self.load_new_pair(store)
            trial = preview(store, DAY, 2, 2)
            for kind in ('facts', 'registry'):
                before = list_editions(store, DAY, kind)
                with self.assertRaises(LatestEdition) as error:
                    retire(store, DAY, kind, 2)
                self.assertEqual((error.exception.day, error.exception.kind, error.exception.version), (DAY, kind, 2))
                self.assertEqual(list_editions(store, DAY, kind), before)
            self.assertEqual(preview(store, DAY, 2, 2), trial)
            with store.read_transaction() as conn:
                self.assertIsNone(get_retirement(conn, DAY, 'facts', 2))
                self.assertIsNone(get_retirement(conn, DAY, 'registry', 2))

    def test_scoped_latest(self):
        other = '西线日域'
        with open_store(self.path) as store:
            put_facts(store, DAY, 'F1', (('A', 7, '东线现场'),))
            for version in range(1, 4):
                put_registry(store, DAY, f'D{version}', (('A', '东区', f'东册{version}'),))
            put_registry(store, other, 'D1', (('A', '西区', '西册1'),))
            for version in range(1, 5):
                put_facts(store, other, f'F{version}', (('A', version, f'西线现场{version}'),))
            for day, kind, version in ((DAY, 'facts', 1), (DAY, 'registry', 3),
                                       (other, 'registry', 1), (other, 'facts', 4)):
                with self.subTest(day=day, kind=kind), self.assertRaises(LatestEdition):
                    retire(store, day, kind, version)
            self.assertEqual(preview(store, DAY, 1, 3).totals, (PartitionTotal('东区', 7, 0),))
            self.assertEqual(preview(store, other, 4, 1).totals, (PartitionTotal('西区', 4, 0),))
            self.assertEqual([entry.version for entry in list_editions(store, DAY, 'facts')], [1])
            self.assertEqual([entry.version for entry in list_editions(store, other, 'registry')], [1])
            with self.assertRaises(UnknownDay):
                list_editions(store, '未知日域', 'facts')
            with self.assertRaises(UnknownDay):
                retire(store, '未知日域', 'facts', 1)
            with self.assertRaises(InvalidSourceKind):
                list_editions(store, DAY, 'unknown')
            with self.assertRaises(InvalidSourceKind):
                retire(store, DAY, 'unknown', 1)
            with self.assertRaises(UnknownEdition):
                retire(store, DAY, 'facts', 4)
            with self.assertRaises(UnknownEdition):
                retire(store, DAY, 'facts', 2 ** 80)

    def test_historical_compatible_version_can_retire(self):
        with open_store(self.path) as store:
            for version, point in enumerate(('A', 'C', 'A'), start=1):
                put_facts(store, DAY, f'F{version}', ((point, version, f'现场{version}'),))
            put_registry(store, DAY, 'D1', (('A', '东区', 'D1-A'), ('C', '东区', 'D1-C')))
            put_registry(store, DAY, 'D2', (('B', '西区', 'D2-B'), ('C', '西区', 'D2-C')))
            original = publish(store, DAY, 'P2', 2, 2)
            put_registry(store, DAY, 'D3', (('B', '南区', 'D3-B'), ('C', '南区', 'D3-C')))
            self.assertEqual(preview(store, DAY, 2, 3).totals, (PartitionTotal('南区', 2, 0),))
            self.assertEqual(retire(store, DAY, 'facts', 2), RetirementRecord(DAY, 'facts', 2))
        with open_store(self.path) as store:
            with self.assertRaises(SourceEditionUnavailable) as error:
                preview(store, DAY, 2, 3)
            self.assertEqual((error.exception.kind, error.exception.version, error.exception.status),
                             ('facts', 2, 'retired'))
            self.assertEqual(read_release(store, DAY, 'P2'), original)
            self.assertEqual(preview(store, DAY, 3, 1).totals, (PartitionTotal('东区', 3, 0),))
