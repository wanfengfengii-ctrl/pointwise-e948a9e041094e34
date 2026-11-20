import json
import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Stores:
    archive: Path
    ledger: Path


@dataclass(frozen=True)
class RequestBinding:
    request_id: str
    batch_id: str
    parameters: str

    @property
    def report_id(self) -> str:
        return f'R-{self.request_id}'


@dataclass(frozen=True)
class PreparedReport:
    report_id: str
    request_id: str
    assignment: tuple[tuple[str, str], ...]
    lines: tuple[dict, ...]


@contextmanager
def archive_transaction(path: Path, *, write: bool = False,
                        create: bool = False) -> Iterator[sqlite3.Connection]:
    mode = 'rwc' if create else 'rw'
    uri = f'{path.resolve().as_uri()}?mode={mode}'
    with closing(sqlite3.connect(uri, uri=True, timeout=0.2, isolation_level=None)) as db, db:
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys = ON')
        db.execute('BEGIN IMMEDIATE' if write else 'BEGIN')
        yield db


def initialize_archive_store(db: sqlite3.Connection) -> None:
    db.execute('''CREATE TABLE IF NOT EXISTS report_requests (
        request_id TEXT PRIMARY KEY,
        batch_id TEXT NOT NULL REFERENCES frozen_batches(batch_id),
        parameters TEXT NOT NULL
    )''')
    db.execute('''CREATE INDEX IF NOT EXISTS report_requests_batch
                  ON report_requests(batch_id, request_id)''')
    db.execute('''CREATE TABLE IF NOT EXISTS prepared_reports (
        report_id TEXT PRIMARY KEY,
        request_id TEXT NOT NULL UNIQUE REFERENCES report_requests(request_id),
        assignment TEXT NOT NULL,
        lines TEXT NOT NULL
    )''')
    db.execute('''CREATE TABLE IF NOT EXISTS first_receipts (
        report_id TEXT PRIMARY KEY REFERENCES prepared_reports(report_id),
        receipt TEXT NOT NULL
    )''')
    db.execute('''CREATE TABLE IF NOT EXISTS report_deliveries (
        report_id TEXT PRIMARY KEY REFERENCES first_receipts(report_id)
    )''')


def save_request_binding(db: sqlite3.Connection, binding: RequestBinding) -> RequestBinding:
    db.execute('''INSERT INTO report_requests VALUES (?, ?, ?) ON CONFLICT(request_id) DO NOTHING''',
               (binding.request_id, binding.batch_id, binding.parameters))
    result = load_request_binding(db, binding.request_id)
    if result is None:
        raise RuntimeError('binding insert did not persist in the archive transaction')
    return result


def load_request_binding(db: sqlite3.Connection, request_id: str) -> RequestBinding | None:
    row = db.execute('SELECT request_id, batch_id, parameters FROM report_requests WHERE request_id = ?',
                     (request_id,)).fetchone()
    return None if row is None else RequestBinding(*row)


def binding_for_report(db: sqlite3.Connection, report_id: str) -> RequestBinding | None:
    if not report_id.startswith('R-'):
        return None
    return load_request_binding(db, report_id[2:])


def list_batch_bindings(db: sqlite3.Connection, batch_id: str) -> list[str]:
    rows = db.execute('SELECT request_id FROM report_requests WHERE batch_id = ? ORDER BY request_id',
                      (batch_id,))
    return [row['request_id'] for row in rows]


def save_prepared_report(db: sqlite3.Connection, report: PreparedReport, receipt: dict) -> None:
    db.execute('INSERT INTO prepared_reports VALUES (?, ?, ?, ?)', (
        report.report_id, report.request_id, json.dumps(report.assignment, separators=(',', ':')),
        json.dumps(report.lines, separators=(',', ':')),
    ))
    db.execute('INSERT INTO first_receipts VALUES (?, ?)', (report.report_id, json.dumps(receipt)))


def load_report_material(db: sqlite3.Connection, report_id: str) -> PreparedReport | None:
    row = db.execute('SELECT * FROM prepared_reports WHERE report_id = ?', (report_id,)).fetchone()
    if row is None:
        return None
    return PreparedReport(row['report_id'], row['request_id'],
                          tuple(tuple(pair) for pair in json.loads(row['assignment'])),
                          tuple(json.loads(row['lines'])))


def load_receipt_record(db: sqlite3.Connection, report_id: str) -> dict | None:
    row = db.execute('SELECT receipt FROM first_receipts WHERE report_id = ?', (report_id,)).fetchone()
    return None if row is None else json.loads(row['receipt'])


def open_delivery(db: sqlite3.Connection, report_id: str) -> bool:
    result = db.execute('''INSERT INTO report_deliveries VALUES (?)
                           ON CONFLICT(report_id) DO NOTHING''', (report_id,))
    return result.rowcount == 1


def delivery_is_open(db: sqlite3.Connection, report_id: str) -> bool:
    return db.execute('SELECT 1 FROM report_deliveries WHERE report_id = ?',
                      (report_id,)).fetchone() is not None
