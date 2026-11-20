from sqlite3 import Connection, OperationalError

from archive.store import Stores, archive_transaction, binding_for_report, list_batch_bindings
from audit.balance import count_balance
from audit.by_evidence import reconcile_evidence
from audit.by_report import reconcile_report
from ledger.recovery import list_unconfirmed_requests
from ledger.store import UnconfirmedCustody, custody_transaction, pin_custody_snapshot
from review.batches import load_frozen_batch
from source.origins import require_label


def _statement(archive_db: Connection, ledger_db: Connection | None, batch_id: str,
               report_id: str | None) -> dict:
    batch = load_frozen_batch(archive_db, batch_id)
    if batch is None:
        return {'status': 'unknown_batch'}
    report = None
    if report_id is not None:
        binding = binding_for_report(archive_db, report_id)
        if binding is not None and binding.batch_id != batch_id:
            return {'status': 'batch_mismatch'}
        report = reconcile_report(archive_db, ledger_db, batch, report_id)
    evidence = reconcile_evidence(ledger_db, batch)
    if ledger_db is None:
        unconfirmed = list_batch_bindings(archive_db, batch_id)
    else:
        unconfirmed = list_unconfirmed_requests(ledger_db, batch_id)
        if report is not None and report['status'] == 'pending' and binding is not None:
            unconfirmed = sorted({*unconfirmed, binding.request_id})
    return {'status': 'pending' if ledger_db is None else 'ok', 'batch_id': batch_id,
            'balance': count_balance(evidence), 'evidence': evidence,
            'pending_requests': unconfirmed, 'report': report}


def audit(stores: Stores, batch_id: str, report_id: str | None = None) -> dict:
    require_label(batch_id, 'batch id')
    if report_id is not None:
        require_label(report_id, 'report id')
    try:
        with custody_transaction(stores.ledger) as ledger_db:
            # The ledger snapshot can only issue archive material that already committed.
            pin_custody_snapshot(ledger_db)
            with archive_transaction(stores.archive) as archive_db:
                return _statement(archive_db, ledger_db, batch_id, report_id)
    except (OperationalError, UnconfirmedCustody):
        try:
            with archive_transaction(stores.archive) as archive_db:
                return _statement(archive_db, None, batch_id, report_id)
        except OperationalError:
            return {'status': 'pending', 'batch_id': batch_id}
