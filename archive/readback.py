from sqlite3 import Connection, OperationalError

from archive.receipts import build_receipt, load_first_receipt
from archive.store import (Stores, archive_transaction, binding_for_report, delivery_is_open,
                           load_report_material)
from ledger.recovery import recover_custody
from ledger.store import UnconfirmedCustody, custody_transaction, pin_custody_snapshot
from source.origins import require_label


def read_from_snapshot(archive_db: Connection, ledger_db: Connection | None, report_id: str) -> dict:
    binding = binding_for_report(archive_db, report_id)
    if binding is None:
        return {'status': 'unknown_report'}
    pending = {'status': 'pending', 'report_id': report_id}
    if ledger_db is None:
        return pending
    custody = recover_custody(ledger_db, binding.request_id, binding.batch_id, binding.parameters)
    material = load_report_material(archive_db, report_id)
    if not delivery_is_open(archive_db, report_id):
        if custody is not None and custody.state == 'cancelled':
            return {'status': 'cancelled', 'request_id': binding.request_id}
        return {'status': 'not_signed'} if custody is None and material is None else pending
    if material is None or material.request_id != binding.request_id:
        return pending
    links = tuple((line['slot'], line['evidence_id']) for line in material.lines)
    if material.assignment != links:
        return pending
    receipt = load_first_receipt(archive_db, report_id)
    if receipt is None or receipt != build_receipt(binding, material):
        return pending
    return {'status': 'signed', 'batch_id': binding.batch_id, 'request_id': binding.request_id,
            'report_id': report_id, 'lines': list(material.lines), 'receipt': receipt.to_record()}


def read(stores: Stores, report_id: str) -> dict:
    require_label(report_id, 'report id')
    try:
        with custody_transaction(stores.ledger) as ledger_db:
            pin_custody_snapshot(ledger_db)
            with archive_transaction(stores.archive) as archive_db:
                return read_from_snapshot(archive_db, ledger_db, report_id)
    except (OperationalError, UnconfirmedCustody):
        try:
            with archive_transaction(stores.archive) as archive_db:
                return read_from_snapshot(archive_db, None, report_id)
        except OperationalError:
            return {'status': 'pending', 'report_id': report_id}
