from collections.abc import Iterable
from sqlite3 import OperationalError

from archive.prepare import make_request_binding
from archive.store import Stores, archive_transaction, load_request_binding, mark_request_cancelled
from ledger.recovery import recover_custody
from ledger.settlement import delivered_material, settle_delivery, settle_withdrawal
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
        # Hold the ledger write lock first so a busy ledger leaves no one-sided
        # archive mark. While it is held, the archive decides the terminal state:
        # either an issuance already opened delivery, or a cancellation mark
        # forbids any future delivery. Both settles commit with this transaction.
        with custody_transaction(stores.ledger, write=True) as db:
            record = recover_custody(db, request_id, batch_id, binding.parameters)
            with archive_transaction(stores.archive, write=True) as archive_db:
                material = delivered_material(archive_db, binding)
                if material is None:
                    mark_request_cancelled(archive_db, binding.request_id)
            if material is not None:
                settle_delivery(db, binding, record, material)
                return {'status': 'already_signed', 'report_id': binding.report_id}
            settle_withdrawal(db, binding, record)
            return {'status': 'cancelled', 'request_id': request_id}
    except (OperationalError, UnconfirmedCustody):
        return {'status': 'pending', 'request_id': request_id}
