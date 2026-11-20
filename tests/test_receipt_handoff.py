from archive.initialize import initialize
from archive.publish import AFTER_COMMIT, AFTER_PREPARE, ConfirmationInterrupted, sign
from archive.readback import read
from audit.shift import audit
from ledger.cancel import cancel
from tests.support import ReviewFixture, assignment_of, stop_at


class ReceiptHandoffTests(ReviewFixture):
    """Regressions for the duplicated write-off across a lost reply."""

    def test_lost_reply_keeps_issuance_and_audit_agrees_before_recovery(self):
        observed = []

        def lose_reply(stage):
            if stage == AFTER_COMMIT:
                observed.append(read(self.stores, 'R-X'))
                raise ConfirmationInterrupted(stage)

        interrupted = sign(self.stores, 'day', 'X', self.x, checkpoint=lose_reply)
        self.assert_no_report(interrupted, 'pending')
        self.assertEqual(observed[0]['status'], 'signed')
        # The delivery committed before the reply was lost; the shift view must
        # already agree with what readback hands out, even before acknowledgement.
        window = audit(self.stores, 'day', 'R-X')
        self.assertEqual(window['balance']['used'], 2)
        self.assertTrue(window['report']['all_match'])
        self.stores = initialize(self.directory)
        self.assertEqual(sign(self.stores, 'day', 'X', self.x), observed[0])
        self.assertEqual(cancel(self.stores, 'day', 'X', self.x)['status'], 'already_signed')
        self.assertEqual(cancel(self.stores, 'day', 'X', self.x)['status'], 'already_signed')
        competitor = sign(self.stores, 'day', 'Y', self.y)
        self.assert_no_report(competitor, 'not_enough')
        x = read(self.stores, 'R-X')
        self.assertEqual(assignment_of(x), [['U', 'B'], ['V', 'A']])
        self.assert_no_report(read(self.stores, 'R-Y'), 'not_signed')
        statement = audit(self.stores, 'day', 'R-X')
        self.assertTrue(statement['report']['all_match'])
        self.assertEqual(statement['balance']['used'], 2)

    def test_withdrawal_wins_over_a_suspended_publisher(self):
        results = {}

        def withdraw_and_issue_y(stage):
            if stage == AFTER_PREPARE:
                results['withdrawn'] = cancel(self.stores, 'day', 'X', self.x)
                results['successor'] = sign(self.stores, 'day', 'Y', self.y)

        late = sign(self.stores, 'day', 'X', self.x, checkpoint=withdraw_and_issue_y)
        self.assert_no_report(results['withdrawn'], 'cancelled')
        self.assert_no_report(late, 'cancelled')
        self.stores = initialize(self.directory)
        self.assert_no_report(read(self.stores, 'R-X'), 'cancelled')
        self.assertEqual(sign(self.stores, 'day', 'X', self.x), late)
        self.assertEqual(cancel(self.stores, 'day', 'X', self.x), results['withdrawn'])
        y = read(self.stores, 'R-Y')
        self.assertEqual(y, results['successor'])
        self.assertEqual(assignment_of(y), [['V', 'A']])
        statement = audit(self.stores, 'day', 'R-Y')
        self.assertTrue(statement['report']['all_match'])
        self.assertEqual(statement['balance']['used'], 1)
        self.assertEqual(statement['balance']['available'], 1)

    def test_withdrawn_request_cannot_be_revived_by_new_candidates(self):
        self.assert_no_report(sign(self.stores, 'day', 'X', self.x,
                                   checkpoint=stop_at(AFTER_PREPARE)), 'pending')
        cancelled = cancel(self.stores, 'day', 'X', self.x)
        reopened = initialize(self.directory)
        # Same parameters replay the terminal withdrawal; different parameters clash.
        self.assertEqual(cancel(reopened, 'day', 'X', self.x), cancelled)
        self.assertEqual(sign(reopened, 'day', 'X', self.x), cancelled)
        self.assert_no_report(sign(reopened, 'day', 'X', self.only_b), 'request_conflict')
        flipped = tuple(reversed(self.x))
        self.assert_no_report(cancel(reopened, 'day', 'X', flipped), 'request_conflict')
        self.assert_no_report(read(reopened, 'R-X'), 'cancelled')
        competitor = sign(reopened, 'day', 'Y', self.y)
        self.assertEqual(assignment_of(competitor), [['V', 'A']])
