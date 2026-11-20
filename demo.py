import json
from pathlib import Path
from tempfile import TemporaryDirectory

from archive.initialize import initialize
from archive.publish import AFTER_COMMIT, ConfirmationInterrupted, sign
from archive.readback import read
from audit.shift import audit
from ledger.cancel import cancel
from review.candidates import RequestSlot
from review.criteria import Gauge, SlotRequirement
from review.freeze import freeze
from source.ingest import ingest
from source.origins import Origin


def assignments(report):
    return [[line['slot'], line['measurement']['ref']['measurement']] for line in report['lines']]


def main() -> None:
    sample = json.loads((Path(__file__).resolve().parent / 'samples' / 'day.json').read_text(encoding='utf-8'))
    with TemporaryDirectory() as directory:
        stores = initialize(directory)
        refs = {}
        for item in sample['readings']:
            refs[item['id']] = ingest(
                stores, sample['device'], item['id'], unit='um', reading=item['reading_um'],
                category=item['category'], origin=Origin(sample['probe_batch'], sample['document'], item['line']),
            )
        slots = tuple(SlotRequirement(item['name'], tuple(item['categories']),
                                      tuple(refs[name] for name in item['candidates'])) for item in sample['slots'])
        freeze(stores, 'day', refs.values(), Gauge(*sample['gauge_um']), slots)
        x = tuple(RequestSlot(slot, tuple(refs[name] for name in names)) for slot, names in sample['request_x'])
        y = tuple(RequestSlot(slot, tuple(refs[name] for name in names)) for slot, names in sample['request_y'])
        observed = []

        def lose_reply(stage):
            if stage == AFTER_COMMIT:
                observed.append(read(stores, 'R-X'))
                raise ConfirmationInterrupted(stage)

        interrupted = sign(stores, 'day', 'X', x, checkpoint=lose_reply)
        stores = initialize(directory)
        aborted = cancel(stores, 'day', 'X', x)
        competitor = sign(stores, 'day', 'Y', y)
        correction = sample['correction']
        ingest(stores, sample['device'], correction['id'], unit='um', reading=correction['reading_um'],
               category=correction['category'],
               origin=Origin(sample['probe_batch'], correction['document'], correction['line']),
               previous=refs[correction['id']])
        stores = initialize(directory)
        report = read(stores, 'R-X')
        statement = audit(stores, 'day', 'R-X')
        statuses = [interrupted['status'], aborted['status'], competitor['status'], report['status']]
        if statuses != ['pending', 'already_signed', 'not_enough', 'signed'] or observed != [report]:
            raise SystemExit(f'daily issue and recovery differed from expected results: {statuses}')
        expected = [['U', 'B'], ['V', 'A']]
        actual = assignments(report)
        balance = {key: statement['balance'][key] for key in ('used', 'available', 'missing')}
        downstream_expected = {'balance': {'used': 2, 'available': 0, 'missing': 1}, 'matches': True,
                               'receipt': 'receipt:X', 'B_document': 'probe-day.csv'}
        downstream_actual = {'balance': balance, 'matches': statement['report']['all_match'],
                             'receipt': report['receipt']['receipt_id'],
                             'B_document': report['lines'][0]['measurement']['origin']['document']}
        if actual != expected or downstream_actual != downstream_expected:
            raise SystemExit(f'daily issuance or shift reconciliation differed: {actual}, {downstream_actual}')
        scenario = {'case_id': 'match', 'input': sample, 'expected': expected, 'actual': actual,
                    'downstream_expected': downstream_expected, 'downstream_actual': downstream_actual,
                    'code_paths': ['review/matching.py', 'archive/publish.py', 'archive/readback.py', 'audit/shift.py'],
                    'oracle': 'V requires A, B is the remaining U candidate, and M cannot be spent. The old report keeps B line 2.'}
        print('POINTWISE_SCENARIO ' + json.dumps(scenario, ensure_ascii=False, sort_keys=True))
        print(json.dumps({'report': report, 'balance': statement['balance'], 'competing_request': competitor},
                         ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
