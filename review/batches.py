import json
from dataclasses import asdict, dataclass
from sqlite3 import Connection

from review.candidates import FrozenCandidate
from review.criteria import Gauge, SlotRequirement
from source.measurements import MeasurementRevision, RevisionRef


@dataclass(frozen=True)
class FrozenBatch:
    batch_id: str
    gauge: Gauge
    measurements: tuple[MeasurementRevision, ...]
    slots: tuple[SlotRequirement, ...]
    qualifications: tuple[tuple[FrozenCandidate, ...], ...]

    def evidence_by_key(self) -> dict[str, MeasurementRevision]:
        return {revision.ref.key: revision for revision in self.measurements}


def initialize_batch_store(db: Connection) -> None:
    db.execute('''CREATE TABLE IF NOT EXISTS frozen_batches (
        batch_id TEXT PRIMARY KEY,
        snapshot TEXT NOT NULL
    )''')


def save_frozen_batch(db: Connection, batch: FrozenBatch) -> FrozenBatch:
    previous = load_frozen_batch(db, batch.batch_id)
    if previous is not None:
        if previous != batch:
            raise ValueError('batch id already identifies a different freeze')
        return previous
    db.execute('INSERT INTO frozen_batches VALUES (?, ?)', (
        batch.batch_id, json.dumps(asdict(batch), separators=(',', ':'), sort_keys=True),
    ))
    return batch


def load_frozen_batch(db: Connection, batch_id: str) -> FrozenBatch | None:
    row = db.execute('SELECT snapshot FROM frozen_batches WHERE batch_id = ?', (batch_id,)).fetchone()
    if row is None:
        return None
    record = json.loads(row['snapshot'])
    return FrozenBatch(
        batch_id,
        Gauge(**record['gauge']),
        tuple(MeasurementRevision.from_record(item) for item in record['measurements']),
        tuple(SlotRequirement(item['name'], tuple(item['categories']),
                              tuple(RevisionRef(**ref) for ref in item['candidates']))
              for item in record['slots']),
        tuple(tuple(FrozenCandidate(RevisionRef(**item['ref']), item['exclusion']) for item in options)
              for options in record['qualifications']),
    )
