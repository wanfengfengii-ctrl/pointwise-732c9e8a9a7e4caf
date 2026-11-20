import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from facts import FactReceipt, FactRow
from facts.editions import load_fact_rows
from facts.ingest import put_facts
from facts.receipts import FactRequestConflict
from reconcile.preview import preview
from registry.intake import put_registry
from release.audit import read_release
from release.publish import publish
from retention import open_store
from retention.inventory import UnknownDay, list_editions
from retention.retire import retire


DAY = '东线日域'
OBSERVATIONS = (('A', 7, '泵站表1'), ('A', 7, '泵站表2'), ('B', None, '巡测表3'))
REGISTRY = (('A', '东区', '台账A'), ('B', '东区', '台账B'))


class TestIngest(unittest.TestCase):
    def setUp(self):
        temporary = self.enterContext(TemporaryDirectory())
        self.path = Path(temporary) / 'warehouse.sqlite3'

    def test_same_request_replay(self):
        with open_store(self.path) as store:
            first = put_facts(store, DAY, 'R1', OBSERVATIONS)
            self.assertEqual(first, FactReceipt(DAY, 'R1', 1))
            self.assertEqual(put_facts(store, DAY, 'R1', iter(OBSERVATIONS)), first)
        with open_store(self.path) as store:
            self.assertEqual(put_facts(store, DAY, 'R1', OBSERVATIONS), first)
            directory = list_editions(store, DAY, 'facts')
            self.assertEqual([(entry.version, entry.available) for entry in directory], [(1, True)])
            with store.read_transaction() as conn:
                self.assertEqual(load_fact_rows(conn, DAY, 1), (
                    FactRow(0, 'A', 7, '泵站表1'),
                    FactRow(1, 'A', 7, '泵站表2'),
                    FactRow(2, 'B', None, '巡测表3'),
                ))
            self.assertEqual(put_facts(store, DAY, 'R2', OBSERVATIONS).version, 2)

    def test_bootstrap(self):
        with open_store(self.path) as store:
            put_facts(store, DAY, 'R1', OBSERVATIONS)
            put_registry(store, DAY, 'C1', REGISTRY)
            original = publish(store, DAY, 'P1', 1, 1)
            correction = (('A', 9, '现场更正1'), ('B', 0, '现场更正2'))
            revised = put_facts(store, DAY, 'R2', correction)
            revised_registry = put_registry(store, DAY, 'C2', (('A', '西区', '新台账A'), ('B', '东区', '新台账B')))
            retirement = retire(store, DAY, 'facts', 1)
            store.initialize()
        with open_store(self.path) as store:
            self.assertEqual(put_facts(store, DAY, 'R2', correction), revised)
            self.assertEqual(put_registry(store, DAY, 'C2', (('A', '西区', '新台账A'), ('B', '东区', '新台账B'))), revised_registry)
            self.assertEqual([entry.available for entry in list_editions(store, DAY, 'facts')], [False, True])
            self.assertEqual(retire(store, DAY, 'facts', 1), retirement)
            self.assertEqual(read_release(store, DAY, 'P1'), original)
            result = preview(store, DAY, 2, 2)
            self.assertEqual([(row.liters, row.partition) for row in result.rows], [(9, '西区'), (0, '东区')])

    def test_request_scope(self):
        with open_store(self.path) as store:
            east = put_facts(store, DAY, 'same', OBSERVATIONS)
            self.assertEqual(list_editions(store, DAY, 'registry'), ())
            east_registry = put_registry(store, DAY, 'same', REGISTRY)
            west_registry = put_registry(store, '西线日域', 'same', (('A', '西区', '西线台账'),))
            west = put_facts(store, '西线日域', 'same', (('A', 2, '西线现场'),))
            self.assertEqual([receipt.version for receipt in (east, east_registry, west, west_registry)], [1, 1, 1, 1])
            self.assertEqual(preview(store, '西线日域', 1, 1).rows[0].partition, '西区')
            self.assertEqual(preview(store, DAY, 1, 1).rows[0].partition, '东区')
            self.assertEqual(put_facts(store, DAY, 'R2', OBSERVATIONS).version, 2)
            self.assertEqual([entry.version for entry in list_editions(store, DAY, 'registry')], [1])
            self.assertEqual([entry.version for entry in list_editions(store, '西线日域', 'facts')], [1])

    def test_archived_request(self):
        with open_store(self.path) as store:
            first = put_facts(store, DAY, 'R1', OBSERVATIONS)
            put_facts(store, DAY, 'R2', (('A', 2, '现场更正'),))
            retire(store, DAY, 'facts', 1)
        with open_store(self.path) as store:
            self.assertEqual(put_facts(store, DAY, 'R1', OBSERVATIONS), first)
            with self.assertRaises(FactRequestConflict):
                put_facts(store, DAY, 'R1', (('A', 8, '泵站表1'), *OBSERVATIONS[1:]))
            self.assertEqual([entry.available for entry in list_editions(store, DAY, 'facts')], [False, True])
            self.assertEqual(put_facts(store, DAY, 'R3', OBSERVATIONS).version, 3)

    def test_conflicting_request(self):
        with open_store(self.path) as store:
            accepted = put_facts(store, DAY, 'R1', OBSERVATIONS)
            with self.assertRaises(FactRequestConflict) as error:
                put_facts(store, DAY, 'R1', (('A', 8, '泵站表1'), *OBSERVATIONS[1:]))
            self.assertEqual((error.exception.day, error.exception.request_id), (DAY, 'R1'))
            self.assertEqual(put_facts(store, DAY, 'R1', OBSERVATIONS), accepted)
            put_registry(store, DAY, 'C1', REGISTRY)
            self.assertEqual([row.liters for row in preview(store, DAY, 1, 1).rows], [7, 7, None])
            self.assertEqual(put_facts(store, DAY, 'R2', OBSERVATIONS).version, 2)

    def test_source_conflict(self):
        with open_store(self.path) as store:
            put_facts(store, DAY, 'R1', OBSERVATIONS)
            changed = (OBSERVATIONS[0], ('A', 7, '更正后的出处'), OBSERVATIONS[2])
            with self.assertRaises(FactRequestConflict):
                put_facts(store, DAY, 'R1', changed)
            self.assertEqual(put_facts(store, DAY, 'R2', changed).version, 2)
            put_registry(store, DAY, 'C1', REGISTRY)
            self.assertEqual(preview(store, DAY, 1, 1).rows[1].observation_source, '泵站表2')
            self.assertEqual(preview(store, DAY, 2, 1).rows[1].observation_source, '更正后的出处')

    def test_order_conflict(self):
        with open_store(self.path) as store:
            first = put_facts(store, DAY, 'R1', OBSERVATIONS)
            changed = (OBSERVATIONS[2], OBSERVATIONS[1], OBSERVATIONS[0])
            with self.assertRaises(FactRequestConflict):
                put_facts(store, DAY, 'R1', changed)
            self.assertEqual(put_facts(store, DAY, 'R1', OBSERVATIONS), first)
            put_registry(store, DAY, 'C1', REGISTRY)
            self.assertEqual([row.point for row in preview(store, DAY, 1, 1).rows], ['A', 'A', 'B'])

    def test_invalid_rows(self):
        with open_store(self.path) as store:
            for invalid in ((('A', True, '现场'),), (('A', 1.5, '现场'),), (('A', '7', '现场'),),
                            (('', 7, '现场'),), (('A', 7, ' '),), (('A', 7),), 'ABC', None):
                with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                    put_facts(store, DAY, 'bad', invalid)
            with self.assertRaises(UnknownDay):
                list_editions(store, DAY, 'facts')
            first = put_facts(store, DAY, 'R1', OBSERVATIONS)
            with self.assertRaises(ValueError):
                put_facts(store, DAY, 'R2', (*OBSERVATIONS, ('A', False, '非法末行')))
            self.assertEqual(list_editions(store, DAY, 'facts')[0].version, first.version)
            self.assertEqual(len(list_editions(store, DAY, 'facts')), 1)
            self.assertEqual(put_facts(store, DAY, 'R2', OBSERVATIONS).version, 2)
