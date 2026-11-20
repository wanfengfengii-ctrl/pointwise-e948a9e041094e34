from archive.initialize import initialize
from archive.publish import AFTER_COMMIT, AFTER_PREPARE, ConfirmationInterrupted, sign
from archive.readback import read
from audit.shift import audit
from ledger.cancel import cancel
from tests.support import ReviewFixture, assignment_of, stop_at


class InterleavingTests(ReviewFixture):
    def test_lost_reply_cannot_release_committed_evidence(self):
        before_loss = []

        def lose_reply(stage):
            if stage == AFTER_COMMIT:
                before_loss.append(read(self.stores, 'R-X'))
                raise ConfirmationInterrupted(stage)

        attempt = sign(self.stores, 'day', 'X', self.x, checkpoint=lose_reply)
        self.assert_no_report(attempt, 'pending')
        self.assertEqual(len(before_loss), 1)
        self.assertEqual(before_loss[0]['status'], 'signed')
        self.stores = initialize(self.directory)
        aborted = cancel(self.stores, 'day', 'X', self.x)
        y = sign(self.stores, 'day', 'Y', self.y)
        self.assert_no_report(aborted, 'already_signed')
        self.assert_no_report(y, 'not_enough')
        self.assert_no_report(read(self.stores, 'R-Y'), 'not_signed')
        recovered = sign(self.stores, 'day', 'X', self.x)
        self.assertEqual(recovered, before_loss[0])
        self.assertEqual(read(self.stores, 'R-X'), recovered)
        self.scenario('lost', {'lost': 'after_commit', 'requests': ['X', 'Y']},
                      ['pending', 'already_signed', 'not_enough'],
                      [attempt['status'], aborted['status'], y['status']],
                      [[['U', 'B'], ['V', 'A']], 'receipt:X'],
                      [assignment_of(recovered), recovered['receipt']['receipt_id']],
                      ['archive/publish.py', 'archive/readback.py', 'ledger/cancel.py', 'ledger/settlement.py'],
                      'X was read at the after-commit checkpoint; only its receipt and consumption can survive.')

    def test_lost_uncertain_outcome_keeps_claims_protected(self):
        self.assert_no_report(sign(self.stores, 'day', 'X', self.x,
                                   checkpoint=stop_at(AFTER_PREPARE)), 'pending')
        with self.blocked_ledger():
            retry = sign(self.stores, 'day', 'X', self.x)
            aborted = cancel(self.stores, 'day', 'X', self.x)
            competitor = sign(self.stores, 'day', 'Y', self.y)
            for result in (retry, aborted, competitor, read(self.stores, 'R-X')):
                self.assert_no_report(result, 'pending')
        held = audit(self.stores, 'day')['balance']['held']
        self.assertEqual(held, 2)
        self.stores = initialize(self.directory)
        recovered = sign(self.stores, 'day', 'X', self.x)
        still_short = sign(self.stores, 'day', 'Y', self.y)
        self.scenario('lost.uncertain_outcome', {'held_by': 'X', 'ledger': 'exclusive lock'},
                      ['pending', 'pending', 'pending'], [r['status'] for r in (retry, aborted, competitor)],
                      [2, 'signed', 'not_enough'], [held, recovered['status'], still_short['status']],
                      ['ledger/recovery.py', 'ledger/cancel.py', 'archive/publish.py', 'archive/readback.py'],
                      'An exclusive SQLite lock blocks independent readers and writers without releasing any claim.')

    def test_cancelled_request_reopens_as_cancelled_and_releases_evidence(self):
        self.assert_no_report(sign(self.stores, 'day', 'X', self.x,
                                   checkpoint=stop_at(AFTER_PREPARE)), 'pending')
        cancelled = cancel(self.stores, 'day', 'X', self.x)
        self.stores = initialize(self.directory)
        self.assertEqual(cancel(self.stores, 'day', 'X', self.x), cancelled)
        self.assertEqual(sign(self.stores, 'day', 'X', self.x), cancelled)
        self.assert_no_report(read(self.stores, 'R-X'), 'cancelled')
        competitor = sign(self.stores, 'day', 'Y', self.y)
        self.scenario('cancelled', {'cancel': 'after_prepare', 'subsequent': 'Y'}, 'cancelled',
                      cancelled['status'], [['V', 'A']], assignment_of(competitor),
                      ['ledger/cancel.py', 'ledger/recovery.py', 'archive/publish.py', 'archive/readback.py'],
                      'X had prepared material but no formal debit, so only Y can sign using A.')

    def test_cancelled_stale_publish_resumes_after_y_already_signed(self):
        observed = {}

        def cancel_and_reassign(stage):
            if stage == AFTER_PREPARE:
                observed['cancel'] = cancel(self.stores, 'day', 'X', self.x)
                observed['winner'] = sign(self.stores, 'day', 'Y', self.y)

        late = sign(self.stores, 'day', 'X', self.x, checkpoint=cancel_and_reassign)
        self.assert_no_report(late, 'cancelled')
        self.assert_no_report(read(self.stores, 'R-X'), 'cancelled')
        self.assertEqual(read(self.stores, 'R-Y'), observed['winner'])
        self.scenario('cancelled.stale_publish', {'sequence': ['prepare X', 'cancel X', 'sign Y', 'resume X']},
                      ['cancelled', 'signed', 'cancelled'],
                      [observed['cancel']['status'], observed['winner']['status'], late['status']],
                      ['cancelled', [['V', 'A']]],
                      [read(self.stores, 'R-X')['status'], assignment_of(observed['winner'])],
                      ['archive/prepare.py', 'archive/publish.py', 'archive/readback.py', 'ledger/settlement.py'],
                      'Withdrawal and Y complete before the suspended X reaches the terminal transaction.')
