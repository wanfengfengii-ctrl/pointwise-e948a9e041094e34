from dataclasses import asdict, dataclass
from hashlib import sha256
from sqlite3 import Connection
import json

from archive.store import PreparedReport, RequestBinding, load_receipt_record


@dataclass(frozen=True)
class Receipt:
    receipt_id: str
    report_id: str
    request_id: str
    batch_id: str
    evidence_count: int
    material_digest: str

    def to_record(self) -> dict:
        return asdict(self)


def build_receipt(binding: RequestBinding, material: PreparedReport) -> Receipt:
    canonical = json.dumps((binding.parameters, material.assignment, material.lines),
                           sort_keys=True, separators=(',', ':'))
    return Receipt(f'receipt:{binding.request_id}', material.report_id, binding.request_id,
                   binding.batch_id, len(material.assignment), sha256(canonical.encode('utf-8')).hexdigest())


def load_first_receipt(db: Connection, report_id: str) -> Receipt | None:
    record = load_receipt_record(db, report_id)
    return None if record is None else Receipt(**record)
