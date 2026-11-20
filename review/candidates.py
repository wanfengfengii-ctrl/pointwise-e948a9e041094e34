from dataclasses import dataclass
from typing import TYPE_CHECKING

from review.criteria import Gauge, SlotRequirement, check_eligibility, unique_revisions
from source.measurements import MeasurementRevision, RevisionRef
from source.origins import require_label

if TYPE_CHECKING:
    from review.batches import FrozenBatch

CandidateGraph = tuple[tuple[str, tuple[str, ...]], ...]
Assignment = tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class FrozenCandidate:
    ref: RevisionRef
    exclusion: str | None


@dataclass(frozen=True)
class RequestSlot:
    name: str
    candidates: tuple[RevisionRef, ...]

    def __post_init__(self) -> None:
        require_label(self.name, 'slot')
        object.__setattr__(self, 'candidates', unique_revisions(self.candidates))


def build_frozen_candidates(measurements: tuple[MeasurementRevision, ...], gauge: Gauge,
                            slots: tuple[SlotRequirement, ...]) -> tuple[tuple[FrozenCandidate, ...], ...]:
    revisions = {revision.ref: revision for revision in measurements}
    result = []
    for slot in slots:
        options = []
        for ref in slot.candidates:
            if ref not in revisions:
                raise ValueError(f'slot {slot.name} nominates a revision outside the batch')
            options.append(FrozenCandidate(ref, check_eligibility(revisions[ref], gauge, slot)))
        result.append(tuple(options))
    return tuple(result)


def build_candidate_graph(batch: 'FrozenBatch', slots: tuple[RequestSlot, ...]) -> CandidateGraph:
    revisions = {revision.ref for revision in batch.measurements}
    eligible = {
        slot.name: {option.ref for option in options if option.exclusion is None}
        for slot, options in zip(batch.slots, batch.qualifications, strict=True)
    }
    graph = []
    for slot in slots:
        if slot.name not in eligible:
            raise ValueError(f'unknown slot {slot.name}')
        if any(ref not in revisions for ref in slot.candidates):
            raise ValueError(f'slot {slot.name} requests a revision outside the batch')
        graph.append((slot.name, tuple(ref.key for ref in slot.candidates if ref in eligible[slot.name])))
    return tuple(graph)


def restrict_graph(graph: CandidateGraph, allowed: set[str]) -> CandidateGraph:
    return tuple((slot, tuple(key for key in options if key in allowed)) for slot, options in graph)
