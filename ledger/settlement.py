from sqlite3 import Connection

from archive.store import RequestBinding, Stores
from ledger.claims import verify_claims
from ledger.recovery import recover_custody
from ledger.store import CustodyRecord, UnconfirmedCustody, custody_transaction, load_custody_record


def acknowledge_delivery(stores: Stores, binding: RequestBinding) -> str:
    from archive.readback import read

    delivered = read(stores, binding.report_id)
    if delivered['status'] != 'signed':
        return 'cancelled' if delivered['status'] == 'cancelled' else 'pending'
    assignment = tuple((line['slot'], line['evidence_id']) for line in delivered['lines'])
    with custody_transaction(stores.ledger, write=True) as db:
        record = recover_custody(db, binding.request_id, binding.batch_id, binding.parameters)
        if record is None:
            raise UnconfirmedCustody('custody record is unavailable')
        if record.state == 'cancelled':
            return 'cancelled'
        if record.assignment != assignment:
            raise UnconfirmedCustody('delivered report differs from the reserved assignment')
        if record.state == 'issued':
            if record.report_id != binding.report_id:
                raise UnconfirmedCustody('a different report owns this assignment')
            return 'issued'
        db.execute('UPDATE custody_requests SET state = ?, report_id = ? WHERE request_id = ?',
                   ('issued', binding.report_id, binding.request_id))
    return 'issued'


def load_settlement(db: Connection, request_id: str) -> CustodyRecord | None:
    record = load_custody_record(db, request_id)
    if record is None or record.state != 'issued':
        return None
    verify_claims(db, record)
    return record
