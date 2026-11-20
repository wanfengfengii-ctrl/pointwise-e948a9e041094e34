from collections.abc import Iterable
from sqlite3 import OperationalError

from archive.prepare import make_request_binding
from archive.store import Stores, archive_transaction, load_request_binding
from ledger.recovery import recover_custody
from ledger.store import UnconfirmedCustody, custody_transaction
from review.candidates import RequestSlot


def cancel(stores: Stores, batch_id: str, request_id: str, slots: Iterable[RequestSlot]) -> dict:
    binding = make_request_binding(batch_id, request_id, tuple(slots))
    try:
        with archive_transaction(stores.archive) as archive_db:
            existing = load_request_binding(archive_db, request_id)
        if existing is None:
            return {'status': 'unknown_request'}
        if existing != binding:
            return {'status': 'request_conflict'}
        with custody_transaction(stores.ledger, write=True) as db:
            record = recover_custody(db, request_id, batch_id, binding.parameters)
            if record is None:
                db.execute('''INSERT INTO custody_requests
                    (request_id, batch_id, parameters, state, assignment)
                    VALUES (?, ?, ?, 'cancelled', '[]')''', (request_id, batch_id, binding.parameters))
            elif record.state == 'issued':
                return {'status': 'already_signed', 'report_id': record.report_id}
            elif record.state == 'held':
                db.execute('DELETE FROM evidence_claims WHERE request_id = ?', (request_id,))
                db.execute('UPDATE custody_requests SET state = ? WHERE request_id = ?',
                           ('cancelled', request_id))
        return {'status': 'cancelled', 'request_id': request_id}
    except (OperationalError, UnconfirmedCustody):
        return {'status': 'pending', 'request_id': request_id}
