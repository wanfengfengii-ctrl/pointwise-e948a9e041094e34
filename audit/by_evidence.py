from sqlite3 import Connection

from ledger.store import UnconfirmedCustody, load_evidence_custody
from review.batches import FrozenBatch


def reconcile_evidence(ledger_db: Connection | None, batch: FrozenBatch,
                       delivered: dict[str, str] | None = None) -> list[dict]:
    """Reconcile each frozen revision against its one durable custody record.

    ``delivered`` maps a request id to the report whose delivery already
    committed; such a request counts as used even before the ledger is updated,
    so the shift balance never contradicts what readback can hand out.
    """
    by_key = batch.evidence_by_key()
    qualified = {item.ref.key for options in batch.qualifications for item in options if item.exclusion is None}
    claims = {} if ledger_db is None else load_evidence_custody(ledger_db, by_key)
    delivered = {} if ledger_db is None else (delivered or {})
    rows = []
    for key, revision in by_key.items():
        claim = claims.get(key)
        report_id = None
        if revision.reading_um is None:
            state = 'missing'
        elif ledger_db is None:
            state = 'unconfirmed'
        elif claim is not None:
            if claim.state == 'cancelled':
                raise UnconfirmedCustody('cancelled request has an active claim')
            committed = delivered.get(claim.request_id)
            if committed is not None and claim.report_id not in (None, committed):
                raise UnconfirmedCustody('a delivery names a different report than the claim')
            if claim.state == 'issued' or committed is not None:
                state = 'used'
                report_id = claim.report_id or committed
            else:
                state = 'held'
        else:
            state = 'available' if key in qualified else 'ineligible'
        rows.append({'evidence_id': key, 'measurement': revision.to_record(), 'status': state,
                     'request_id': None if claim is None else claim.request_id,
                     'report_id': report_id})
    return rows
