from dataclasses import dataclass

from source.measurements import MeasurementRevision, RevisionRef
from source.origins import require_label


def unique_revisions(revisions) -> tuple[RevisionRef, ...]:
    try:
        refs = tuple(revisions)
    except TypeError as error:
        raise ValueError('expected a sequence of revision references') from error
    if any(not isinstance(ref, RevisionRef) for ref in refs) or len(set(refs)) != len(refs):
        raise ValueError('revision references must be distinct')
    return refs


@dataclass(frozen=True)
class Gauge:
    minimum_um: int
    maximum_um: int

    def __post_init__(self) -> None:
        if any(type(value) is not int for value in (self.minimum_um, self.maximum_um)):
            raise ValueError('gauge endpoints must be integers')
        if self.minimum_um > self.maximum_um:
            raise ValueError('gauge endpoints are reversed')


@dataclass(frozen=True)
class SlotRequirement:
    name: str
    categories: tuple[str, ...]
    candidates: tuple[RevisionRef, ...]

    def __post_init__(self) -> None:
        require_label(self.name, 'slot')
        if not isinstance(self.categories, (tuple, list)) or not self.categories:
            raise ValueError('slot requires at least one category')
        categories = tuple(self.categories)
        for category in categories:
            require_label(category, 'slot category')
        if len(set(categories)) != len(categories):
            raise ValueError('slot categories must be distinct')
        object.__setattr__(self, 'categories', categories)
        object.__setattr__(self, 'candidates', unique_revisions(self.candidates))


def check_eligibility(revision: MeasurementRevision, gauge: Gauge,
                      slot: SlotRequirement) -> str | None:
    reading = revision.reading_um
    if reading is None:
        return 'missing'
    if not gauge.minimum_um <= reading <= gauge.maximum_um:
        return 'out_of_range'
    if revision.category not in slot.categories:
        return 'category'
    return None
