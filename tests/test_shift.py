from archive.initialize import initialize
from archive.publish import AFTER_PREPARE, BEFORE_COMMIT, sign
from archive.readback import read
from archive.store import archive_transaction
from audit.shift import audit
from ledger.cancel import cancel
from review.batches import load_frozen_batch
from review.candidates import RequestSlot
from review.criteria import Gauge, SlotRequirement
from review.freeze import freeze
from source.store import load_revision_chain
from tests.support import ReviewFixture, assignment_of, stop_at


class ShiftTests(ReviewFixture):
    def test_history_exact_revision_and_unique_evidence(self):
        original = sign(self.stores, 'day', 'X', self.x)
        self.assertEqual(original['status'], 'signed')
        corrected = self.intake('B', 9, 'u', 4, previous=self.b, document='corrected.csv')
        self.assertEqual(corrected.number, 2)
        self.stores = initialize(self.directory)
        reopened = read(self.stores, 'R-X')
        self.assertEqual(reopened, original)
        statement = audit(self.stores, 'day', 'R-X')
        self.assertTrue(statement['report']['all_match'])
        b_line = statement['report']['lines'][0]['measurement']
        self.scenario('history', {'corrected': 'B', 'read_report': 'R-X'}, [['U', 'B'], ['V', 'A']],
                      assignment_of(reopened), [True, 'receipt:X'],
                      [statement['report']['all_match'], statement['report']['receipt']['receipt_id']],
                      ['archive/readback.py', 'archive/receipts.py', 'audit/by_report.py'],
                      'B was in U when X was signed; later source edits have no bearing on the stored assignment.')
        self.scenario('history.exact_revision', {'old': [1, 7, 'probe-day.csv'], 'new': [2, 9, 'corrected.csv']},
                      [1, 7, 'probe-day.csv', 2],
                      [b_line['ref']['number'], b_line['reading_um'], b_line['origin']['document'], b_line['origin']['line']],
                      [True, True], [statement['report']['lines'][0]['origin_matches'], reopened['receipt'] == original['receipt']],
                      ['source/revisions.py', 'source/store.py', 'archive/readback.py', 'audit/by_report.py'],
                      'Inspect B revision one and its original line 2; the correction carries a different document.')
        self.scenario('history.unique_evidence', {'eligible_A_slots': ['U', 'V'], 'missing': ['M']},
                      {'used': 2, 'available': 0, 'held': 0, 'missing': 1, 'ineligible': 0, 'unconfirmed': 0},
                      statement['balance'], [['A', 'used'], ['B', 'used'], ['M', 'missing']],
                      [[row['measurement']['ref']['measurement'], row['status']] for row in statement['evidence']],
                      ['audit/by_evidence.py', 'audit/balance.py', 'audit/shift.py'],
                      'A and B are the two unique consumed revisions; M is the sole missing revision.')

    def test_history_batch_mismatch_rejected_and_cross_batch_custody_preserved(self):
        sign(self.stores, 'day', 'X', self.x)
        freeze(self.stores, 'other', (self.a,), Gauge(0, 10),
               (SlotRequirement('V', ('dual',), (self.a,)),))
        mismatch = audit(self.stores, 'other', 'R-X')
        self.assertNotIn('report', mismatch)
        other = sign(self.stores, 'other', 'Y', self.y)
        self.assert_no_report(other, 'not_enough')
        owner = audit(self.stores, 'other')['evidence'][0]['report_id']
        self.scenario('history.batch_mismatch', {'report': 'R-X', 'report_batch': 'day', 'audit_batch': 'other'},
                      'batch_mismatch', mismatch['status'], ['not_enough', 'R-X'], [other['status'], owner],
                      ['audit/shift.py', 'review/batches.py', 'ledger/claims.py'],
                      'R-X belongs to day; A keeps its unique debit even when included by another freeze.')

    def test_history_pending_view_then_confirmed_view(self):
        self.assert_no_report(sign(self.stores, 'day', 'X', self.x,
                                   checkpoint=stop_at(AFTER_PREPARE)), 'pending')
        held = audit(self.stores, 'day', 'R-X')
        self.assertEqual(held['balance']['held'], 2)
        self.assertEqual(held['balance']['available'], 0)
        self.assertEqual(held['pending_requests'], ['X'])
        self.assert_no_report(held['report'], 'pending')
        with self.blocked_ledger():
            unknown = audit(self.stores, 'day', 'R-X')
        self.assert_no_report(unknown['report'], 'pending')
        issued = sign(self.stores, 'day', 'X', self.x)
        accepted = audit(self.stores, 'day', 'R-X')
        self.assertEqual(issued, read(self.stores, 'R-X'))
        self.scenario('history.pending_view', {'ledger': 'locked then restored', 'request': 'X'},
                      ['pending', ['X'], 2, 0, 1],
                      [unknown['status'], unknown['pending_requests'], unknown['balance']['unconfirmed'],
                       unknown['balance']['available'], unknown['balance']['missing']],
                      ['ok', [], 2, True], [accepted['status'], accepted['pending_requests'],
                                           accepted['balance']['used'], accepted['report']['all_match']],
                      ['ledger/recovery.py', 'archive/readback.py', 'audit/by_evidence.py', 'audit/shift.py'],
                      'Frozen M remains missing during the lock; the two protected claims become used after sign commits.')

    def test_initialization_preserves_user_data_first_receipt_and_pending_claim(self):
        original = sign(self.stores, 'day', 'X', self.x)
        self.assertEqual(original['status'], 'signed')
        b2 = self.intake('B', 9, 'u', 4, previous=self.b, document='corrected.csv')
        batch = freeze(self.stores, 'correction', (b2,), Gauge(0, 10), (SlotRequirement('U', ('u',), (b2,)),))
        claim = (RequestSlot('U', (b2,)),)
        self.assert_no_report(sign(self.stores, 'correction', 'H', claim,
                                   checkpoint=stop_at(BEFORE_COMMIT)), 'pending')
        self.stores = initialize(self.directory)
        self.assertEqual(initialize(self.directory), self.stores)
        with archive_transaction(self.stores.archive) as db:
            versions = load_revision_chain(db, 'P1', 'B')
            self.assertEqual(load_frozen_batch(db, 'day'), self.batch)
            self.assertEqual(load_frozen_batch(db, 'correction'), batch)
        reopened = read(self.stores, 'R-X')
        self.assertEqual(reopened, original)
        self.assertEqual(sign(self.stores, 'day', 'X', self.x), original)
        before = audit(self.stores, 'day', 'R-X')
        self.scenario('initialization', {'init_calls_after_sign': 2}, ['signed', 'receipt:X'],
                      [reopened['status'], reopened['receipt']['receipt_id']], [2, True],
                      [before['balance']['used'], before['report']['all_match']],
                      ['archive/initialize.py', 'archive/readback.py', 'audit/shift.py'],
                      'Initialization acts on schema; all fields in the original signed result remain equal.')
        preserved = audit(self.stores, 'correction', 'R-H')
        self.assert_no_report(preserved['report'], 'pending')
        self.assertEqual(preserved['pending_requests'], ['H'])
        self.assertEqual(preserved['balance']['held'], 1)
        self.assertEqual(cancel(self.stores, 'correction', 'H', claim)['status'], 'cancelled')
        self.assert_no_report(sign(self.stores, 'correction', 'H', claim), 'cancelled')
        self.assert_no_report(sign(self.stores, 'day', 'Y', self.y), 'not_enough')
        winner = sign(self.stores, 'correction', 'Z', claim)
        self.assertEqual(winner['lines'][0]['measurement']['ref']['number'], 2)
        self.scenario('initialization.preserve_user_data', {'revisions': [1, 2], 'held': 'H'},
                      [[1, 7], [2, 9]], [[item.ref.number, item.reading_um] for item in versions],
                      ['R-X', 'R-Z'], [audit(self.stores, 'day')['evidence'][0]['report_id'],
                                       audit(self.stores, 'correction')['evidence'][0]['report_id']],
                      ['source/store.py', 'review/batches.py', 'ledger/store.py', 'archive/initialize.py', 'audit/shift.py'],
                      'Cancellation releases only H’s revision two; revision one of A remains debited to X.')
