from sqlite3 import Connection

from ledger.store import UnconfirmedCustody, load_evidence_custody
from review.batches import FrozenBatch


def reconcile_evidence(ledger_db: Connection | None, batch: FrozenBatch) -> list[dict]:
    by_key = batch.evidence_by_key()
    qualified = {item.ref.key for options in batch.qualifications for item in options if item.exclusion is None}
    claims = {} if ledger_db is None else load_evidence_custody(ledger_db, by_key)
    rows = []
    for key, revision in by_key.items():
        claim = claims.get(key)
        if revision.reading_um is None:
            state = 'missing'
        elif ledger_db is None:
            state = 'unconfirmed'
        elif claim is not None:
            if claim.state == 'cancelled':
                raise UnconfirmedCustody('cancelled request has an active claim')
            state = 'used' if claim.state == 'issued' else 'held'
        else:
            state = 'available' if key in qualified else 'ineligible'
        rows.append({'evidence_id': key, 'measurement': revision.to_record(), 'status': state,
                     'request_id': None if claim is None else claim.request_id,
                     'report_id': None if claim is None else claim.report_id})
    return rows
