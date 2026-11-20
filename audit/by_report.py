from sqlite3 import Connection

from archive.readback import read_from_snapshot
from ledger.settlement import load_settlement
from ledger.store import load_evidence_custody
from review.batches import FrozenBatch
from source.measurements import RevisionRef
from source.store import load_revision


def reconcile_report(archive_db: Connection, ledger_db: Connection | None,
                     batch: FrozenBatch, report_id: str) -> dict:
    report = read_from_snapshot(archive_db, ledger_db, report_id)
    if report['status'] != 'signed':
        return report
    settlement = load_settlement(ledger_db, report['request_id'])
    custody = load_evidence_custody(ledger_db, (line['evidence_id'] for line in report['lines']))
    frozen = batch.evidence_by_key()
    lines = []
    for item in report['lines']:
        key = item['evidence_id']
        slot = item['slot']
        ref = RevisionRef.from_key(key)
        source = load_revision(archive_db, ref)
        claim = custody.get(key)
        origin_matches = source is not None and source == frozen.get(key) and (
            source.to_record() == item['measurement']
        )
        custody_matches = (
            settlement is not None and settlement.report_id == report_id and claim is not None
            and claim.request_id == report['request_id'] and claim.report_id == report_id
            and claim.state == 'issued' and claim.slot == slot
        )
        lines.append({**item, 'origin_matches': origin_matches, 'custody_matches': custody_matches})
    return {**report, 'lines': lines,
            'all_match': all(line['origin_matches'] and line['custody_matches'] for line in lines)}
