from sqlite3 import Connection

from archive.receipts import build_receipt, load_first_receipt
from archive.store import (PreparedReport, RequestBinding, Stores, delivery_is_open,
                           load_report_material)
from ledger.claims import verify_claims
from ledger.recovery import recover_custody
from ledger.store import CustodyRecord, UnconfirmedCustody, custody_transaction, load_custody_record


def delivered_material(archive_db: Connection, binding: RequestBinding) -> PreparedReport | None:
    """Return the delivered material only when this request's issuance committed."""
    if not delivery_is_open(archive_db, binding.report_id):
        return None
    material = load_report_material(archive_db, binding.report_id)
    if material is None or material.request_id != binding.request_id:
        raise UnconfirmedCustody('an open delivery lacks its prepared material')
    links = tuple((line['slot'], line['evidence_id']) for line in material.lines)
    if material.assignment != links:
        raise UnconfirmedCustody('delivered lines differ from the stored assignment')
    receipt = load_first_receipt(archive_db, binding.report_id)
    if receipt is None or receipt != build_receipt(binding, material):
        raise UnconfirmedCustody('an open delivery lacks its first receipt')
    return material


def settle_delivery(db: Connection, binding: RequestBinding, record: CustodyRecord | None,
                    material: PreparedReport) -> str:
    """Issuance already owns the evidence; withdrawal can no longer win."""
    if record is None:
        raise UnconfirmedCustody('a delivery exists without a durable claim')
    if record.state == 'cancelled':
        raise UnconfirmedCustody('a delivery conflicts with a withdrawn claim')
    if record.assignment != material.assignment:
        raise UnconfirmedCustody('delivered assignment differs from the durable claim')
    if record.state == 'issued':
        if record.report_id != binding.report_id:
            raise UnconfirmedCustody('a different report owns the durable claim')
        return 'already_signed'
    db.execute('UPDATE custody_requests SET state = ?, report_id = ? WHERE request_id = ?',
               ('issued', binding.report_id, binding.request_id))
    return 'already_signed'


def settle_withdrawal(db: Connection, binding: RequestBinding,
                      record: CustodyRecord | None) -> None:
    """Mark the request withdrawn after the archive refused any future delivery."""
    if record is None:
        db.execute('''INSERT INTO custody_requests
            (request_id, batch_id, parameters, state, assignment)
            VALUES (?, ?, ?, 'cancelled', '[]')''', (binding.request_id, binding.batch_id,
                                                      binding.parameters))
    elif record.state == 'issued':
        raise UnconfirmedCustody('the ledger issued a report the archive never delivered')
    elif record.state == 'held':
        db.execute('DELETE FROM evidence_claims WHERE request_id = ?', (binding.request_id,))
        db.execute('UPDATE custody_requests SET state = ? WHERE request_id = ?',
                   ('cancelled', binding.request_id))


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
