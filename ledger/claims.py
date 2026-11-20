import json
from collections.abc import Iterable
from pathlib import Path
from sqlite3 import Connection

from ledger.store import (CustodyRecord, UnconfirmedCustody, custody_transaction,
                          load_custody_record, load_evidence_custody)
from review.candidates import Assignment


def available_evidence(db: Connection, evidence_ids: Iterable[str]) -> tuple[set[str], set[str]]:
    keys = set(evidence_ids)
    claims = load_evidence_custody(db, keys)
    if any(record.state == 'cancelled' for record in claims.values()):
        raise UnconfirmedCustody('a cancelled request still holds evidence')
    return keys.difference(claims), {key for key, record in claims.items() if record.state == 'held'}


def load_claims(db: Connection, request_id: str) -> dict[str, str]:
    return dict(db.execute('SELECT slot, evidence_id FROM evidence_claims WHERE request_id = ?',
                           (request_id,)))


def verify_claims(db: Connection, record: CustodyRecord) -> None:
    actual = load_claims(db, record.request_id)
    expected = {} if record.state == 'cancelled' else dict(record.assignment)
    if actual != expected or (record.state != 'cancelled' and not expected):
        raise UnconfirmedCustody('the request lacks its complete durable claim set')


def claim_assignment(path: Path, request_id: str, batch_id: str, parameters: str,
                     assignment: Assignment) -> CustodyRecord | None:
    slots = {slot for slot, _ in assignment}
    keys = {key for _, key in assignment}
    if not assignment or len(slots) != len(assignment) or len(keys) != len(assignment):
        raise ValueError('a claim requires a complete one-to-one assignment')
    if tuple(slot for slot, _ in assignment) != tuple(slot for slot, _ in json.loads(parameters)):
        raise ValueError('claim slot order differs from the request')
    with custody_transaction(path, write=True) as db:
        prior = load_custody_record(db, request_id)
        if prior is not None:
            if not prior.matches(batch_id, parameters):
                raise UnconfirmedCustody('request binding differs across stores')
            verify_claims(db, prior)
            return prior
        free, _ = available_evidence(db, keys)
        if free != keys:
            return None
        db.execute('''INSERT INTO custody_requests
                      (request_id, batch_id, parameters, state, assignment)
                      VALUES (?, ?, ?, 'held', ?)''', (
            request_id, batch_id, parameters, json.dumps(assignment, separators=(',', ':')),
        ))
        db.executemany('INSERT INTO evidence_claims (evidence_id, request_id, slot) VALUES (?, ?, ?)',
                       ((key, request_id, slot) for slot, key in assignment))
        return CustodyRecord(request_id, batch_id, parameters, 'held', assignment, None)
