import sqlite3
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from facts.ingest import put_facts
from reconcile import PartitionTotal, UnmappedObservation
from reconcile.classify import ClassifiedRow
from reconcile.preview import preview
from registry.intake import put_registry
from release import ReleaseReceipt
from release.audit import ReleaseNotFound, read_release
from release.publish import publish
from release.receipts import PublishNumberConflict
from retention.store import open_store


DAY = '东线日域'
OBSERVATIONS = (('A', 7, '现场第1行'), ('A', 7, '现场第2行'), ('B', None, '现场第3行'))
ASSIGNMENTS = (('A', '东区', '清册A'), ('B', '东区', '清册B'))
EXPECTED_ROWS = (
    ClassifiedRow(0, 'A', 7, '东区', '现场第1行', '清册A'),
    ClassifiedRow(1, 'A', 7, '东区', '现场第2行', '清册A'),
    ClassifiedRow(2, 'B', None, '东区', '现场第3行', '清册B'),
)
EXPECTED_TOTALS = (PartitionTotal('东区', 14, 1),)


def install_commit_failure(conn):
    conn.execute('CREATE TEMP TABLE commit_parents (id INTEGER PRIMARY KEY)')
    conn.execute('''CREATE TEMP TABLE commit_guard (
        id INTEGER REFERENCES commit_parents(id) DEFERRABLE INITIALLY DEFERRED
    )''')
    conn.execute('''CREATE TEMP TRIGGER reject_release_commit AFTER INSERT ON main.release_receipts
        BEGIN
            INSERT INTO commit_guard(id) VALUES (1);
        END''')


class TestPublication(unittest.TestCase):
    def setUp(self):
        temporary = self.enterContext(TemporaryDirectory())
        self.path = Path(temporary) / 'warehouse.sqlite3'

    def load_workday(self, store):
        put_facts(store, DAY, 'R1', OBSERVATIONS)
        put_registry(store, DAY, 'C1', ASSIGNMENTS)

    def record_counts(self, store, number):
        tables = ('release_snapshots', 'release_details', 'release_totals', 'release_receipts')
        with store.read_transaction() as conn:
            return tuple(conn.execute(f'SELECT COUNT(*) FROM {table} WHERE day = ? AND number = ?',
                                      (DAY, number)).fetchone()[0] for table in tables)

    def test_detail_and_totals(self):
        with open_store(self.path) as store:
            self.load_workday(store)
            trial = preview(store, DAY, 1, 1)
            self.assertEqual((trial.rows, trial.totals), (EXPECTED_ROWS, EXPECTED_TOTALS))
            self.assertEqual(self.record_counts(store, 'P1'), (0, 0, 0, 0))
            snapshot, receipt = publish(store, DAY, 'P1', 1, 1)
            self.assertEqual((snapshot.rows, snapshot.totals), (EXPECTED_ROWS, EXPECTED_TOTALS))
            self.assertEqual(receipt, ReleaseReceipt(DAY, 'P1', 1, 1))
        with open_store(self.path) as store:
            reopened, original_receipt = read_release(store, DAY, 'P1')
            self.assertEqual((reopened.fact_version, reopened.registry_version), (1, 1))
            self.assertEqual((reopened.rows, reopened.totals), (EXPECTED_ROWS, EXPECTED_TOTALS))
            self.assertEqual(original_receipt, receipt)

    def test_unknown_point(self):
        with open_store(self.path) as store:
            put_facts(store, DAY, 'R1', (('A', 7, '现场A'), ('B', 3, '现场B')))
            put_registry(store, DAY, 'C1', (('A', '东区', '清册A'),))
            with self.assertRaises(UnmappedObservation) as error:
                preview(store, DAY, 1, 1)
            self.assertEqual((error.exception.position, error.exception.point, error.exception.source), (1, 'B', '现场B'))
            with self.assertRaises(UnmappedObservation):
                publish(store, DAY, 'P1', 1, 1)
            with self.assertRaises(ReleaseNotFound):
                read_release(store, DAY, 'P1')
            self.assertEqual(self.record_counts(store, 'P1'), (0, 0, 0, 0))

    def test_first_gap(self):
        rows = (('A', 3, '原行0'), ('B', None, '原行1'), ('C', 5, '原行2'), ('A', 7, '原行3'))
        expected = {'day': DAY, 'fact_version': 1, 'registry_version': 1,
                    'position': 1, 'point': 'B', 'source': '原行1'}
        with open_store(self.path) as store:
            put_facts(store, DAY, 'R1', rows)
            put_registry(store, DAY, 'C1', (('A', '东区', '清册A'),))
            with self.assertRaises(UnmappedObservation) as trial:
                preview(store, DAY, 1, 1)
            with self.assertRaises(UnmappedObservation) as publication:
                publish(store, DAY, 'P1', 1, 1)
            self.assertEqual(trial.exception.as_report(), expected)
            self.assertEqual(publication.exception.as_report(), expected)
            self.assertEqual(self.record_counts(store, 'P1'), (0, 0, 0, 0))

    def test_explicit_pair(self):
        with open_store(self.path) as store:
            self.load_workday(store)
            put_facts(store, DAY, 'R2', (('A', 99, '新版现场A'),))
            put_registry(store, DAY, 'C2', (('A', '西区', '新版清册A'), ('B', '西区', '新版清册B')))
            trial = preview(store, DAY, 1, 1)
            self.assertEqual((trial.rows, trial.totals), (EXPECTED_ROWS, EXPECTED_TOTALS))
            publish(store, DAY, 'old', 1, 1)
            revised = preview(store, DAY, 2, 2)
            self.assertEqual(revised.rows, (ClassifiedRow(0, 'A', 99, '西区', '新版现场A', '新版清册A'),))
            self.assertEqual(revised.totals, (PartitionTotal('西区', 99, 0),))
        with open_store(self.path) as store:
            old, receipt = read_release(store, DAY, 'old')
            self.assertEqual(receipt, ReleaseReceipt(DAY, 'old', 1, 1))
            self.assertEqual((old.rows, old.totals), (EXPECTED_ROWS, EXPECTED_TOTALS))

    def test_manual_pairs_after_independent_revisions(self):
        with open_store(self.path) as store:
            put_facts(store, DAY, 'F1', (('A', 7, 'F1-A'),))
            put_registry(store, DAY, 'D1', (('A', '东区', 'D1-A'), ('C', '东区', 'D1-C')))
            first, _ = publish(store, DAY, 'initial', 1, 1)
            self.assertEqual(first.totals, (PartitionTotal('东区', 7, 0),))
            put_facts(store, DAY, 'F2', (('C', 8, 'F2-C'),))
            put_facts(store, DAY, 'F3', (('A', 9, 'F3-A'),))
            put_registry(store, DAY, 'D2', (('B', '西区', 'D2-B'), ('C', '西区', 'D2-C')))
            with self.assertRaises(UnmappedObservation) as error:
                preview(store, DAY, 3, 2)
            self.assertEqual((error.exception.position, error.exception.point), (0, 'A'))
            for fact_version, registry_version, expected in (
                (3, 1, ClassifiedRow(0, 'A', 9, '东区', 'F3-A', 'D1-A')),
                (2, 2, ClassifiedRow(0, 'C', 8, '西区', 'F2-C', 'D2-C')),
            ):
                with self.subTest(pair=(fact_version, registry_version)):
                    trial = preview(store, DAY, fact_version, registry_version)
                    self.assertEqual(trial.rows, (expected,))
                    number = f'manual-{fact_version}-{registry_version}'
                    fixed, receipt = publish(store, DAY, number, fact_version, registry_version)
                    self.assertEqual(fixed.rows, (expected,))
                    self.assertEqual(receipt, ReleaseReceipt(DAY, number, fact_version, registry_version))

    def test_numeric_edges(self):
        huge = 10 ** 5000
        rows = (('A', huge, '超大读数'), ('A', -4, '负读数'), ('A', 0, '实测零'), ('B', None, '缺测'))
        expected_rows = (
            ClassifiedRow(0, 'A', huge, 'East', '超大读数', '清册A'),
            ClassifiedRow(1, 'A', -4, 'East', '负读数', '清册A'),
            ClassifiedRow(2, 'A', 0, 'East', '实测零', '清册A'),
            ClassifiedRow(3, 'B', None, 'West', '缺测', '清册B'),
        )
        expected_totals = (PartitionTotal('East', huge - 4, 0), PartitionTotal('West', 0, 1))
        with open_store(self.path) as store:
            put_facts(store, DAY, 'R1', rows)
            put_registry(store, DAY, 'C1', (('B', 'West', '清册B'), ('A', 'East', '清册A')))
            trial = preview(store, DAY, 1, 1)
            self.assertEqual((trial.rows, trial.totals), (expected_rows, expected_totals))
            publish(store, DAY, 'numeric', 1, 1)
            put_facts(store, DAY, 'R2', ())
            empty = preview(store, DAY, 2, 1)
            self.assertEqual((empty.rows, empty.totals), ((), ()))
            publish(store, DAY, 'empty', 2, 1)
        with open_store(self.path) as store:
            self.assertEqual(put_facts(store, DAY, 'R1', rows).version, 1)
            numeric, _ = read_release(store, DAY, 'numeric')
            self.assertEqual((numeric.rows, numeric.totals), (expected_rows, expected_totals))
            empty_snapshot, _ = read_release(store, DAY, 'empty')
            self.assertEqual((empty_snapshot.rows, empty_snapshot.totals), ((), ()))

    def test_commit_failure_retry(self):
        with open_store(self.path) as store:
            self.load_workday(store)
            with store.write_transaction() as conn:
                install_commit_failure(conn)
            trace = []
            with store.read_transaction() as conn:
                conn.set_trace_callback(trace.append)
            trace.clear()
            with self.assertRaisesRegex(sqlite3.IntegrityError, 'FOREIGN KEY constraint failed'):
                publish(store, DAY, 'P1', 1, 1)
            self.assertEqual(trace[-2:], ['COMMIT', 'ROLLBACK'])
            self.assertEqual(self.record_counts(store, 'P1'), (0, 0, 0, 0))
        with open_store(self.path) as store:
            with self.assertRaises(ReleaseNotFound):
                read_release(store, DAY, 'P1')
            self.assertEqual(self.record_counts(store, 'P1'), (0, 0, 0, 0))
            snapshot, receipt = publish(store, DAY, 'P1', 1, 1)
            self.assertEqual((snapshot.rows, snapshot.totals), (EXPECTED_ROWS, EXPECTED_TOTALS))
            self.assertEqual(receipt, ReleaseReceipt(DAY, 'P1', 1, 1))
            self.assertEqual(self.record_counts(store, 'P1'), (1, 3, 1, 1))
        with open_store(self.path) as store:
            self.assertEqual(read_release(store, DAY, 'P1'), (snapshot, receipt))

    def test_replay_identity(self):
        with open_store(self.path) as store:
            self.load_workday(store)
            first = publish(store, DAY, 'P1', 1, 1)
        with open_store(self.path) as store:
            self.assertEqual(publish(store, DAY, 'P1', 1, 1), first)
            with self.assertRaises(PublishNumberConflict) as conflict:
                publish(store, DAY, 'P1', 1, 99)
            self.assertEqual(conflict.exception.receipt, first[1])
            self.assertEqual(read_release(store, DAY, 'P1'), first)
            self.assertEqual(self.record_counts(store, 'P1'), (1, 3, 1, 1))
            with self.assertRaises(ReleaseNotFound):
                read_release(store, '西线日域', 'P1')
            put_facts(store, '西线日域', 'R1', (('A', 6, '西线现场'),))
            put_registry(store, '西线日域', 'C1', (('A', '西区', '西线清册'),))
            west, _ = publish(store, '西线日域', 'P1', 1, 1)
            self.assertEqual(west.totals, (PartitionTotal('西区', 6, 0),))
            self.assertEqual(read_release(store, DAY, 'P1'), first)
