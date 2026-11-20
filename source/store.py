from sqlite3 import Connection, Row

from source.measurements import MeasurementRevision, RevisionRef
from source.origins import Origin


def initialize_source_store(db: Connection) -> None:
    db.execute('''CREATE TABLE IF NOT EXISTS probe_batches (
        device TEXT NOT NULL,
        probe_batch TEXT NOT NULL,
        PRIMARY KEY (device, probe_batch)
    )''')
    db.execute('''CREATE TABLE IF NOT EXISTS measurement_revisions (
        evidence_id TEXT PRIMARY KEY,
        device TEXT NOT NULL,
        measurement TEXT NOT NULL,
        revision_number INTEGER NOT NULL,
        previous_id TEXT UNIQUE REFERENCES measurement_revisions(evidence_id),
        reading_um TEXT,
        category TEXT NOT NULL,
        probe_batch TEXT NOT NULL,
        document TEXT NOT NULL,
        document_line TEXT NOT NULL,
        UNIQUE (device, measurement, revision_number),
        FOREIGN KEY (device, probe_batch) REFERENCES probe_batches(device, probe_batch)
    )''')


def insert_revision(db: Connection, revision: MeasurementRevision) -> None:
    ref, origin = revision.ref, revision.origin
    db.execute('INSERT OR IGNORE INTO probe_batches VALUES (?, ?)', (ref.device, origin.probe_batch))
    db.execute('''INSERT INTO measurement_revisions (
        evidence_id, device, measurement, revision_number, previous_id, reading_um,
        category, probe_batch, document, document_line
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''', (
        ref.key, ref.device, ref.measurement, ref.number,
        None if revision.previous is None else revision.previous.key,
        None if revision.reading_um is None else str(revision.reading_um),
        revision.category, origin.probe_batch, origin.document, str(origin.line),
    ))


def _decode_revision(row: Row) -> MeasurementRevision:
    return MeasurementRevision(
        RevisionRef(row['device'], row['measurement'], row['revision_number']),
        None if row['reading_um'] is None else int(row['reading_um']), row['category'],
        Origin(row['probe_batch'], row['document'], int(row['document_line'])),
        None if row['previous_id'] is None else RevisionRef.from_key(row['previous_id']),
    )


def load_revision(db: Connection, ref: RevisionRef) -> MeasurementRevision | None:
    row = db.execute('SELECT * FROM measurement_revisions WHERE evidence_id = ?', (ref.key,)).fetchone()
    return None if row is None else _decode_revision(row)


def load_revision_chain(db: Connection, device: str, measurement: str) -> tuple[MeasurementRevision, ...]:
    rows = db.execute('''SELECT * FROM measurement_revisions WHERE device = ? AND measurement = ?
                         ORDER BY revision_number''', (device, measurement))
    return tuple(_decode_revision(row) for row in rows)
