from archive.store import archive_transaction
from review.batches import load_frozen_batch
from review.criteria import Gauge, SlotRequirement
from review.freeze import freeze
from source.measurements import RevisionRef
from source.store import load_revision, load_revision_chain
from tests.support import ReviewFixture


class IntakeTests(ReviewFixture):
    def test_zero_and_missing_preserve_value_and_origin(self):
        values = {item.ref.measurement: [item.reading_um, item.origin.line]
                  for item in self.batch.measurements if item.ref != self.b}
        choices = {column.ref.measurement: column.exclusion for column in self.batch.qualifications[1]}
        self.scenario('zero', {'readings': {'A': 0, 'M': None}}, {'A': [0, 1], 'M': [None, 3]}, values,
                      {'A': None, 'B': 'category', 'M': 'missing'}, choices,
                      ['source/ingest.py', 'review/criteria.py', 'review/freeze.py'],
                      'Read the supplied original line numbers and check zero against inclusive limits.')

    def test_zero_category_and_range(self):
        foreign = self.intake('C', 4, 'other', 4)
        high = self.intake('H', 11, 'dual', 5)
        endpoint = self.intake('E', 10, 'dual', 6)
        refs = (self.a, self.m, foreign, high, endpoint)
        batch = freeze(self.stores, 'criteria', refs, Gauge(0, 10), (SlotRequirement('V', ('dual',), refs),))
        actual = [item.exclusion for item in batch.qualifications[0]]
        qualified = [item.ref.measurement for item in batch.qualifications[0] if item.exclusion is None]
        self.scenario('zero.category_and_range', {'readings': [0, None, 4, 11, 10], 'range': [0, 10]},
                      [None, 'missing', 'category', 'out_of_range', None], actual, ['A', 'E'], qualified,
                      ['source/measurements.py', 'review/criteria.py', 'review/candidates.py', 'review/freeze.py'],
                      'Both endpoints satisfy the closed interval; 4 has the wrong category; 11 is above it.')

    def test_bad_unit_has_no_successor_and_old_revision_can_freeze(self):
        with self.assertRaisesRegex(ValueError, 'unit') as rejection:
            self.intake('B', 8, 'u', 7, unit='mm', previous=self.b)
        with archive_transaction(self.stores.archive) as db:
            chain = load_revision_chain(db, 'P1', 'B')
            invalid = load_revision(db, RevisionRef('P1', 'B', 2))
        kept = freeze(self.stores, 'kept', (self.b,), Gauge(0, 10),
                      (SlotRequirement('U', ('u',), (self.b,)),))
        self.scenario('bad_unit', {'previous': 1, 'unit': 'mm'}, [1], [item.ref.number for item in chain],
                      7, kept.measurements[0].reading_um,
                      ['source/ingest.py', 'source/store.py', 'review/freeze.py'],
                      'The rejected input requests millimetres and the original input was 7 micrometres.')
        corrected = self.intake('B', 8, 'u', 8, previous=self.b)
        with archive_transaction(self.stores.archive) as db:
            chain = load_revision_chain(db, 'P1', 'B')
        self.scenario('bad_unit.atomic_intake', {'previous': 1, 'bad_unit': 'mm', 'next_unit': 'um'},
                      {'bad_successor': None, 'rejected': True},
                      {'bad_successor': invalid, 'rejected': isinstance(rejection.exception, ValueError)},
                      [2, [[1, 7, 2], [2, 8, 8]]],
                      [corrected.number, [[item.ref.number, item.reading_um, item.origin.line] for item in chain]],
                      ['source/ingest.py', 'source/revisions.py', 'source/store.py'],
                      'Only the original and the valid correction should occupy the two positions in the chain.')

    def test_freeze_rejects_unknown_revisions_duplicate_slots_and_rebinding(self):
        with self.assertRaisesRegex(ValueError, 'unknown revision'):
            freeze(self.stores, 'unknown', (RevisionRef('P1', 'A', 2),), self.batch.gauge, self.batch.slots)
        with self.assertRaisesRegex(ValueError, 'duplicate slot'):
            freeze(self.stores, 'duplicate', (self.a, self.b, self.m), self.batch.gauge,
                   (self.batch.slots[0], self.batch.slots[0]))
        with self.assertRaisesRegex(ValueError, 'different freeze'):
            freeze(self.stores, 'day', (self.a, self.b, self.m), Gauge(0, 9), self.batch.slots)
        with archive_transaction(self.stores.archive) as db:
            self.assertEqual(load_frozen_batch(db, 'day'), self.batch)
            self.assertIsNone(load_frozen_batch(db, 'unknown'))
            self.assertIsNone(load_frozen_batch(db, 'duplicate'))

    def test_invalid_origin_reading_and_predecessor_leave_chain_intact(self):
        cases = (
            {'reading': True, 'line': 4, 'previous': self.b},
            {'reading': 8, 'line': 0, 'previous': self.b},
            {'reading': 8, 'line': 4, 'previous': self.a},
        )
        for case in cases:
            with self.subTest(case=case), self.assertRaises(ValueError):
                self.intake('B', category='u', **case)
        with archive_transaction(self.stores.archive) as db:
            chain = load_revision_chain(db, 'P1', 'B')
        self.assertEqual([revision.ref for revision in chain], [self.b])
