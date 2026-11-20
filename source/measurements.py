import json
from dataclasses import asdict, dataclass

from source.origins import Origin, require_label


@dataclass(frozen=True)
class RevisionRef:
    device: str
    measurement: str
    number: int

    def __post_init__(self) -> None:
        require_label(self.device, 'device')
        require_label(self.measurement, 'measurement')
        if type(self.number) is not int or self.number < 1:
            raise ValueError('revision number must be a positive integer')

    @property
    def key(self) -> str:
        return json.dumps((self.device, self.measurement, self.number), separators=(',', ':'))

    @classmethod
    def from_key(cls, key: str) -> 'RevisionRef':
        return cls(*json.loads(key))


@dataclass(frozen=True)
class MeasurementRevision:
    ref: RevisionRef
    reading_um: int | None
    category: str
    origin: Origin
    previous: RevisionRef | None = None

    def to_record(self) -> dict:
        return asdict(self)

    @classmethod
    def from_record(cls, record: dict) -> 'MeasurementRevision':
        previous = record['previous']
        return cls(
            RevisionRef(**record['ref']), record['reading_um'], record['category'],
            Origin(**record['origin']), RevisionRef(**previous) if previous else None,
        )


def validate_reading(unit: str, reading: int | None) -> None:
    if unit != 'um':
        raise ValueError('reading unit must be um')
    if reading is not None and type(reading) is not int:
        raise ValueError('reading must be an integer or None')
