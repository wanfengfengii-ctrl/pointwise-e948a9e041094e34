from archive.initialize import initialize
from archive.publish import BEFORE_CLAIM, BEFORE_COMMIT, sign
from archive.readback import read
from audit.shift import audit
from ledger.cancel import cancel
from ledger.claims import load_claims
from ledger.store import custody_transaction
from review.candidates import RequestSlot
from review.criteria import Gauge, SlotRequirement
from review.freeze import freeze
from tests.support import ReviewFixture, assignment_of, stop_at


class IssueTests(ReviewFixture):
    def test_match_avoids_greedy_dead_end_and_issues_complete_report(self):
        report = sign(self.stores, 'day', 'X', self.x)
        self.assertEqual(report['status'], 'signed')
        self.assertEqual(report['receipt']['report_id'], 'R-X')
        self.assertEqual(report['receipt']['evidence_count'], 2)
        competitor = sign(self.stores, 'day', 'Y', self.y)
        self.assert_no_report(competitor, 'not_enough')
        with custody_transaction(self.stores.ledger) as db:
            claims = load_claims(db, 'X')
        self.assertEqual(claims, {'U': self.b.key, 'V': self.a.key})
        self.scenario('match', {'U': ['A', 'B'], 'V': ['A']}, [['U', 'B'], ['V', 'A']],
                      assignment_of(report), ['signed', 'not_enough'],
                      [read(self.stores, 'R-X')['status'], competitor['status']],
                      ['review/matching.py', 'ledger/claims.py', 'archive/publish.py', 'archive/readback.py'],
                      'V only has A, leaving B for U; once used A cannot supply Y.')

    def test_match_lexicographic_order_uses_request_priorities(self):
        c = self.intake('C', 10, 'dual', 4)
        refs = (self.a, c)
        freeze(self.stores, 'two', refs, Gauge(0, 10),
               tuple(SlotRequirement(slot, ('dual',), refs) for slot in ('U', 'V')))
        order = (c, self.a)
        report = sign(self.stores, 'two', 'X', tuple(RequestSlot(slot, order) for slot in ('U', 'V')))
        self.assertEqual(report['status'], 'signed')
        statement = audit(self.stores, 'two', 'R-X')
        self.scenario('match.lexicographic', {'U': ['C', 'A'], 'V': ['C', 'A']},
                      [['U', 'C'], ['V', 'A']], assignment_of(report), [2, True],
                      [statement['balance']['used'], statement['report']['all_match']],
                      ['review/candidates.py', 'review/matching.py', 'audit/by_report.py'],
                      'Both permutations cover the slots; C is the first requested candidate for U.')

    def test_not_enough_leaves_no_material_or_formal_consumption(self):
        impossible = (RequestSlot('U', (self.a,)), RequestSlot('V', (self.a,)))
        result = sign(self.stores, 'day', 'X', impossible)
        self.assert_no_report(result, 'not_enough')
        self.assert_no_report(read(self.stores, 'R-X'), 'not_signed')
        with custody_transaction(self.stores.ledger) as db:
            self.assertEqual(load_claims(db, 'X'), {})
        self.assertEqual(audit(self.stores, 'day')['balance']['used'], 0)
        competitor = sign(self.stores, 'day', 'Y', self.y)
        self.scenario('not_enough', {'U': ['A'], 'V': ['A']}, 'not_enough', result['status'],
                      [['V', 'A']], assignment_of(competitor),
                      ['review/matching.py', 'ledger/claims.py', 'archive/readback.py'],
                      'One original cannot cover two slots; one later slot can still use it.')

    def test_not_enough_claim_conflict_does_not_hold_a(self):
        slots = (SlotRequirement('U', ('dual',), (self.a,)), SlotRequirement('V', ('u',), (self.b,)))
        freeze(self.stores, 'race', (self.a, self.b), Gauge(0, 10), slots)
        race = (RequestSlot('U', (self.a,)), RequestSlot('V', (self.b,)))
        winner = []

        def take_b(stage):
            if stage == BEFORE_CLAIM:
                winner.append(sign(self.stores, 'day', 'Z', self.only_b))

        outcome = sign(self.stores, 'race', 'X', race, checkpoint=take_b)
        self.assert_no_report(outcome, 'not_enough')
        self.assert_no_report(read(self.stores, 'R-X'), 'not_signed')
        with custody_transaction(self.stores.ledger) as db:
            held = load_claims(db, 'X')
        y = sign(self.stores, 'day', 'Y', self.y)
        self.scenario('not_enough.claim_conflict', {'plan': ['A', 'B'], 'intervening_claim': 'B'},
                      ['signed', 'not_enough', {}], [winner[0]['status'], outcome['status'], held],
                      [['V', 'A']], assignment_of(y),
                      ['ledger/claims.py', 'ledger/store.py', 'archive/publish.py'],
                      'Z consumes B before X enters its claim transaction, so X cannot reserve A alone.')

    def test_retry_and_ordered_binding_preserve_first_receipt(self):
        interrupted = sign(self.stores, 'day', 'X', self.x, checkpoint=stop_at(BEFORE_COMMIT))
        self.assert_no_report(interrupted, 'pending')
        self.assert_no_report(read(self.stores, 'R-X'), 'pending')
        balance = audit(self.stores, 'day')['balance']
        self.assertEqual(balance['used'], 0)
        self.assertEqual(balance['held'], 2)
        self.stores = initialize(self.directory)
        fixed = sign(self.stores, 'day', 'X', self.x)
        self.assertEqual(fixed['status'], 'signed')
        self.assertEqual(sign(self.stores, 'day', 'X', self.x), fixed)
        self.scenario('retry', {'interruption': 'before_commit', 'request': 'X'}, ['pending', 0, 2],
                      [interrupted['status'], balance['used'], balance['held']], [['U', 'B'], ['V', 'A']],
                      assignment_of(fixed), ['ledger/settlement.py', 'archive/publish.py', 'archive/readback.py'],
                      'The interrupted transaction rolls back the formal debit; retry still has the original full claim.')
        flipped = tuple(reversed(self.x))
        wrong = sign(self.stores, 'day', 'X', flipped)
        self.assert_no_report(wrong, 'request_conflict')
        self.assert_no_report(cancel(self.stores, 'day', 'X', flipped), 'request_conflict')
        original = read(self.stores, 'R-X')
        self.scenario('retry.ordered_binding', {'original': ['U', 'V'], 'replayed': ['V', 'U']},
                      'request_conflict', wrong['status'], [True, 'receipt:X', 2],
                      [original == fixed, original['receipt']['receipt_id'], audit(self.stores, 'day')['balance']['used']],
                      ['archive/store.py', 'archive/prepare.py', 'ledger/cancel.py'],
                      'Exchanging slot positions changes the request; the already stored receipt and two debits remain.')
