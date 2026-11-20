import json
import unittest

from archive.initialize import initialize
from archive.publish import AFTER_COMMIT, AFTER_PREPARE, ConfirmationInterrupted, sign
from archive.readback import read
from audit.shift import audit
from ledger.cancel import cancel
from tests.support import ReviewFixture, assignment_of


def uses(report, evidence_id):
    return (report['status'] == 'signed' and isinstance(report.get('receipt'), dict)
            and any(line['evidence_id'] == evidence_id for line in report.get('lines', ())))


def summary(report):
    return {'report': report['report_id'], 'assignment': assignment_of(report),
            'receipt': report['receipt']['receipt_id']}


class ReceiptHandoffTests(ReviewFixture):
    def test_commit_then_lost_reply(self):
        observed = []

        def lose_reply(stage):
            if stage == AFTER_COMMIT:
                observed.append(read(self.stores, 'R-X'))
                raise ConfirmationInterrupted(stage)

        interrupted = sign(self.stores, 'day', 'X', self.x, checkpoint=lose_reply)
        self.assert_no_report(interrupted, 'pending')
        self.stores = initialize(self.directory)
        withdrawn = cancel(self.stores, 'day', 'X', self.x)
        competitor = sign(self.stores, 'day', 'Y', self.y)
        x = read(self.stores, 'R-X')
        y = read(self.stores, 'R-Y')
        if (withdrawn['status'] == 'cancelled' and competitor['status'] == 'signed'
                and observed == [x] and uses(x, self.a.key) and uses(y, self.a.key)):
            self.fail('EVIDENCE_DOUBLE_SPENT ' + json.dumps({'X': summary(x), 'Y': summary(y)}))
        self.assert_no_report(withdrawn, 'already_signed')
        self.assert_no_report(competitor, 'not_enough')
        self.assert_no_report(y, 'not_signed')
        self.assertEqual(x['status'], 'signed')
        self.assertEqual(assignment_of(x), [['U', 'B'], ['V', 'A']])
        self.assertEqual(observed, [x])
        self.assertEqual(sign(self.stores, 'day', 'X', self.x), x)
        statement = audit(self.stores, 'day', 'R-X')
        self.assertTrue(statement['report']['all_match'])
        self.assertEqual(statement['balance']['used'], 2)

    def test_withdrawal_then_stale_publisher(self):
        results = {}

        def withdraw_and_issue_y(stage):
            if stage == AFTER_PREPARE:
                results['withdrawn'] = cancel(self.stores, 'day', 'X', self.x)
                results['successor'] = sign(self.stores, 'day', 'Y', self.y)

        late = sign(self.stores, 'day', 'X', self.x, checkpoint=withdraw_and_issue_y)
        self.stores = initialize(self.directory)
        x = read(self.stores, 'R-X')
        y = read(self.stores, 'R-Y')
        if (results['withdrawn']['status'] == 'cancelled'
                and uses(x, self.a.key) and uses(y, self.a.key)):
            self.fail('STALE_REPORT_AFTER_WITHDRAWAL ' + json.dumps({'X': summary(x), 'Y': summary(y)}))
        self.assert_no_report(results['withdrawn'], 'cancelled')
        self.assert_no_report(late, 'cancelled')
        self.assert_no_report(x, 'cancelled')
        self.assertEqual(sign(self.stores, 'day', 'X', self.x), late)
        self.assertEqual(y, results['successor'])
        self.assertEqual(y['status'], 'signed')
        self.assertEqual(assignment_of(y), [['V', 'A']])
        statement = audit(self.stores, 'day', 'R-Y')
        self.assertTrue(statement['report']['all_match'])
        self.assertEqual(statement['balance']['used'], 1)
        self.assertEqual(statement['balance']['available'], 1)


if __name__ == '__main__':
    unittest.main()
