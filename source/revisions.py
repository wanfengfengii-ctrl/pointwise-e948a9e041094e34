from sqlite3 import Connection

from source.measurements import MeasurementRevision, RevisionRef
from source.origins import Origin
from source.store import insert_revision, load_revision_chain


def check_predecessor(db: Connection, device: str, measurement: str,
                      previous: RevisionRef | None) -> int:
    chain = load_revision_chain(db, device, measurement)
    if not chain:
        if previous is not None:
            raise ValueError('a first revision cannot have a predecessor')
        return 1
    tail = chain[-1].ref
    if previous != tail:
        raise ValueError('correction must reference the current revision of this measurement')
    return tail.number + 1


def append_revision(db: Connection, device: str, measurement: str, reading: int | None,
                    category: str, origin: Origin, previous: RevisionRef | None) -> RevisionRef:
    number = check_predecessor(db, device, measurement, previous)
    ref = RevisionRef(device, measurement, number)
    insert_revision(db, MeasurementRevision(ref, reading, category, origin, previous))
    return ref
