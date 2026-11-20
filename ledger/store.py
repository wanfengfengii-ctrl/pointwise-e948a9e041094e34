import json
import sqlite3
from collections.abc import Iterable, Iterator
from contextlib import closing, contextmanager
from dataclasses import dataclass
from pathlib import Path


class UnconfirmedCustody(RuntimeError):
    """The order and ownership of the durable claims cannot be confirmed."""


@dataclass(frozen=True)
class CustodyRecord:
    request_id: str
    batch_id: str
    parameters: str
    state: str
    assignment: tuple[tuple[str, str], ...]
    report_id: str | None

    def matches(self, batch_id: str, parameters: str) -> bool:
        return (self.batch_id, self.parameters) == (batch_id, parameters)


@dataclass(frozen=True)
class EvidenceCustody:
    request_id: str
    slot: str
    state: str
    report_id: str | None


@contextmanager
def custody_transaction(path: Path, *, write: bool = False,
                        create: bool = False) -> Iterator[sqlite3.Connection]:
    mode = 'rwc' if create else 'rw'
    uri = f'{path.resolve().as_uri()}?mode={mode}'
    with closing(sqlite3.connect(uri, uri=True, timeout=0.2, isolation_level=None)) as db, db:
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys = ON')
        db.execute('BEGIN IMMEDIATE' if write else 'BEGIN')
        yield db


def initialize_ledger_store(db: sqlite3.Connection) -> None:
    db.execute('''CREATE TABLE IF NOT EXISTS custody_requests (
        request_id TEXT PRIMARY KEY,
        batch_id TEXT NOT NULL,
        parameters TEXT NOT NULL,
        state TEXT NOT NULL CHECK (state IN ('held', 'issued', 'cancelled')),
        assignment TEXT NOT NULL,
        report_id TEXT UNIQUE,
        CHECK ((state = 'issued') = (report_id IS NOT NULL))
    )''')
    db.execute('''CREATE TABLE IF NOT EXISTS evidence_claims (
        evidence_id TEXT PRIMARY KEY,
        request_id TEXT NOT NULL REFERENCES custody_requests(request_id),
        slot TEXT NOT NULL,
        UNIQUE (request_id, slot)
    )''')
    db.execute('''CREATE INDEX IF NOT EXISTS custody_batch_state
                  ON custody_requests(batch_id, state, request_id)''')


def pin_custody_snapshot(db: sqlite3.Connection) -> None:
    db.execute('SELECT request_id FROM custody_requests LIMIT 1').fetchone()


def load_custody_record(db: sqlite3.Connection, request_id: str) -> CustodyRecord | None:
    row = db.execute('SELECT * FROM custody_requests WHERE request_id = ?', (request_id,)).fetchone()
    if row is None:
        return None
    return CustodyRecord(row['request_id'], row['batch_id'], row['parameters'], row['state'],
                         tuple(tuple(pair) for pair in json.loads(row['assignment'])), row['report_id'])


def load_evidence_custody(db: sqlite3.Connection,
                          evidence_ids: Iterable[str]) -> dict[str, EvidenceCustody]:
    records = {}
    for evidence_id in dict.fromkeys(evidence_ids):
        row = db.execute('''SELECT claims.request_id, claims.slot, requests.state, requests.report_id
            FROM evidence_claims AS claims JOIN custody_requests AS requests USING (request_id)
            WHERE claims.evidence_id = ?''', (evidence_id,)).fetchone()
        if row is not None:
            records[evidence_id] = EvidenceCustody(*row)
    return records
