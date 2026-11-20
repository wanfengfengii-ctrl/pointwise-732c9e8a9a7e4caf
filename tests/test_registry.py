import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from facts.ingest import put_facts
from reconcile.preview import preview
from registry import RegistryReceipt
from registry.assignments import DuplicatePoint
from registry.intake import put_registry
from registry.receipts import RegistryRequestConflict
from retention.store import open_store
from retention.inventory import list_editions
from retention.retire import retire


DAY = '东线日域'
ENTRIES = (('A', '东区', '旧台账A'), ('B', '东区', '旧台账B'))
CORRECTION = (('A', '西区', '新台账A'), ('B', '东区', '新台账B'))


class TestRegistry(unittest.TestCase):
    def setUp(self):
        temporary = self.enterContext(TemporaryDirectory())
        self.path = Path(temporary) / 'warehouse.sqlite3'

    def test_duplicate_point(self):
        with open_store(self.path) as store:
            first = put_registry(store, DAY, 'C1', ENTRIES)
            self.assertEqual(first, RegistryReceipt(DAY, 'C1', 1))
            for duplicate in (('A', '西区', '重复的A'), ENTRIES[0]):
                with self.subTest(duplicate=duplicate):
                    with self.assertRaises(DuplicatePoint) as error:
                        put_registry(store, DAY, 'C2', (*ENTRIES, duplicate))
                    self.assertEqual(error.exception.point, 'A')
            self.assertEqual([entry.version for entry in list_editions(store, DAY, 'registry')], [1])
            put_facts(store, DAY, 'R1', (('A', 7, '现场A'),))
            row, = preview(store, DAY, 1, 1).rows
            self.assertEqual((row.partition, row.registry_source), ('东区', '旧台账A'))
            self.assertEqual(put_registry(store, DAY, 'C2', CORRECTION).version, 2)

    def test_registry_replay(self):
        with open_store(self.path) as store:
            first = put_registry(store, DAY, 'C1', ENTRIES)
            self.assertEqual(put_registry(store, DAY, 'C1', reversed(ENTRIES)), first)
            for changed in (('A', '西区', '旧台账A'), ('A', '东区', '新出处')):
                with self.subTest(changed=changed), self.assertRaises(RegistryRequestConflict):
                    put_registry(store, DAY, 'C1', (changed, ENTRIES[1]))
            self.assertEqual(put_registry(store, DAY, 'C2', CORRECTION).version, 2)
            retire(store, DAY, 'registry', 1)
        with open_store(self.path) as store:
            self.assertEqual(put_registry(store, DAY, 'C1', reversed(ENTRIES)), first)
            with self.assertRaises(RegistryRequestConflict):
                put_registry(store, DAY, 'C1', CORRECTION)
            self.assertEqual([(entry.version, entry.available) for entry in list_editions(store, DAY, 'registry')],
                             [(1, False), (2, True)])
            self.assertEqual(put_registry(store, DAY, 'C3', ENTRIES).version, 3)
