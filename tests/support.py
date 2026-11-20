import json
import sqlite3
import unittest
from contextlib import closing, contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory

from archive.initialize import initialize
from archive.publish import ConfirmationInterrupted
from review.candidates import RequestSlot
from review.criteria import Gauge, SlotRequirement
from review.freeze import freeze
from source.ingest import ingest
from source.origins import Origin


class ReviewFixture(unittest.TestCase):
    def setUp(self):
        directory = self.enterContext(TemporaryDirectory())
        self.directory = Path(directory)
        self.stores = initialize(self.directory)
        self.a = self.intake('A', 0, 'dual', 1)
        self.b = self.intake('B', 7, 'u', 2)
        self.m = self.intake('M', None, 'dual', 3)
        self.batch = freeze(self.stores, 'day', (self.a, self.b, self.m), Gauge(0, 10), (
            SlotRequirement('U', ('dual', 'u'), (self.a, self.b, self.m)),
            SlotRequirement('V', ('dual',), (self.a, self.b, self.m)),
        ))
        self.x = (RequestSlot('U', (self.a, self.b)), RequestSlot('V', (self.a,)))
        self.y = (RequestSlot('V', (self.a,)),)
        self.only_b = (RequestSlot('U', (self.b,)),)

    def intake(self, name, reading, category, line, *, previous=None,
               unit='um', document='probe-day.csv'):
        return ingest(self.stores, 'P1', name, unit=unit, reading=reading, category=category,
                      origin=Origin('head-day', document, line), previous=previous)

    def scenario(self, case_id, inputs, expected, actual, downstream_expected, downstream_actual,
                 code_paths, oracle):
        self.assertEqual(actual, expected)
        self.assertEqual(downstream_actual, downstream_expected)
        row = dict(case_id=case_id, input=inputs, expected=expected, actual=actual,
                   downstream_expected=downstream_expected, downstream_actual=downstream_actual,
                   code_paths=code_paths, oracle=oracle)
        print('POINTWISE_SCENARIO ' + json.dumps(row, ensure_ascii=False, sort_keys=True))

    def assert_no_report(self, result, status):
        self.assertEqual(result['status'], status)
        self.assertNotIn('lines', result)
        self.assertNotIn('receipt', result)

    @contextmanager
    def blocked_ledger(self):
        with closing(sqlite3.connect(self.stores.ledger, isolation_level=None)) as blocker:
            blocker.execute('BEGIN EXCLUSIVE')
            try:
                yield
            finally:
                blocker.rollback()


def stop_at(target):
    def checkpoint(stage):
        if stage == target:
            raise ConfirmationInterrupted(stage)
    return checkpoint


def assignment_of(report):
    return [[line['slot'], line['measurement']['ref']['measurement']] for line in report['lines']]
