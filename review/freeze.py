from collections.abc import Iterable

from archive.store import Stores, archive_transaction
from review.batches import FrozenBatch, save_frozen_batch
from review.candidates import build_frozen_candidates
from review.criteria import Gauge, SlotRequirement, unique_revisions
from source.measurements import RevisionRef
from source.origins import require_label
from source.store import load_revision


def freeze(stores: Stores, batch_id: str, revisions: Iterable[RevisionRef],
           gauge: Gauge, slots: Iterable[SlotRequirement]) -> FrozenBatch:
    require_label(batch_id, 'batch id')
    refs = unique_revisions(revisions)
    requirements = tuple(slots)
    if not isinstance(gauge, Gauge):
        raise ValueError('expected a gauge')
    if not requirements or any(not isinstance(slot, SlotRequirement) for slot in requirements):
        raise ValueError('expected at least one slot requirement')
    if len({slot.name for slot in requirements}) != len(requirements):
        raise ValueError('duplicate slot in freeze')
    with archive_transaction(stores.archive, write=True) as db:
        measurements = []
        for ref in refs:
            revision = load_revision(db, ref)
            if revision is None:
                raise ValueError(f'unknown revision {ref.key}')
            measurements.append(revision)
        snapshot = tuple(measurements)
        qualifications = build_frozen_candidates(snapshot, gauge, requirements)
        return save_frozen_batch(db, FrozenBatch(batch_id, gauge, snapshot, requirements, qualifications))
