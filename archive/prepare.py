import json
from pathlib import Path

from archive.receipts import build_receipt, load_first_receipt
from archive.store import (PreparedReport, RequestBinding, archive_transaction, load_report_material,
                           load_request_binding, save_prepared_report, save_request_binding)
from ledger.store import UnconfirmedCustody
from review.batches import FrozenBatch
from review.candidates import Assignment, RequestSlot
from source.origins import require_label


def make_request_binding(batch_id: str, request_id: str, slots: tuple[RequestSlot, ...]) -> RequestBinding:
    require_label(batch_id, 'batch id')
    require_label(request_id, 'request id')
    if not slots or any(not isinstance(slot, RequestSlot) for slot in slots):
        raise ValueError('expected at least one request slot')
    if len({slot.name for slot in slots}) != len(slots):
        raise ValueError('duplicate slot in request')
    parameters = json.dumps([(slot.name, [ref.key for ref in slot.candidates]) for slot in slots],
                            separators=(',', ':'))
    return RequestBinding(request_id, batch_id, parameters)


def bind_request(path: Path, binding: RequestBinding) -> RequestBinding:
    with archive_transaction(path, write=True) as db:
        return save_request_binding(db, binding)


def prepare_report(path: Path, binding: RequestBinding, batch: FrozenBatch,
                   assignment: Assignment) -> PreparedReport:
    requested = json.loads(binding.parameters)
    if batch.batch_id != binding.batch_id or len(requested) != len(assignment):
        raise UnconfirmedCustody('assignment cannot be materialized for this request')
    evidence = batch.evidence_by_key()
    eligible = {
        slot.name: {option.ref.key for option in options if option.exclusion is None}
        for slot, options in zip(batch.slots, batch.qualifications, strict=True)
    }
    lines = []
    for (slot, key), (requested_slot, candidates) in zip(assignment, requested, strict=True):
        if slot != requested_slot or key not in candidates or key not in eligible.get(slot, ()):
            raise UnconfirmedCustody('assignment differs from the frozen request')
        lines.append({'slot': slot, 'evidence_id': key, 'measurement': evidence[key].to_record()})
    material = PreparedReport(binding.report_id, binding.request_id, assignment, tuple(lines))
    receipt = build_receipt(binding, material)
    with archive_transaction(path, write=True) as db:
        if load_request_binding(db, binding.request_id) != binding:
            raise UnconfirmedCustody('archive binding changed before material preparation')
        existing = load_report_material(db, binding.report_id)
        if existing is not None:
            if existing != material or load_first_receipt(db, binding.report_id) != receipt:
                raise UnconfirmedCustody('prepared material differs from the held request')
            return existing
        save_prepared_report(db, material, receipt.to_record())
    return material
