from archive.store import Stores, archive_transaction
from source.measurements import RevisionRef, validate_reading
from source.origins import Origin, require_label, validate_origin
from source.revisions import append_revision


def ingest(stores: Stores, device: str, measurement: str, *, unit: str,
           reading: int | None, category: str, origin: Origin,
           previous: RevisionRef | None = None) -> RevisionRef:
    require_label(device, 'device')
    require_label(measurement, 'measurement')
    require_label(category, 'measurement category')
    validate_reading(unit, reading)
    validate_origin(origin)
    if previous is not None and not isinstance(previous, RevisionRef):
        raise ValueError('previous must be a revision reference')
    with archive_transaction(stores.archive, write=True) as db:
        return append_revision(db, device, measurement, reading, category, origin, previous)
