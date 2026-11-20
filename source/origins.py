from dataclasses import dataclass


def require_label(value: str, field: str) -> None:
    if not isinstance(value, str) or not value.strip() or '\x00' in value:
        raise ValueError(f'{field} requires a nonempty label')
    try:
        value.encode('utf-8')
    except UnicodeEncodeError as error:
        raise ValueError(f'{field} requires a UTF-8 label') from error


@dataclass(frozen=True)
class Origin:
    probe_batch: str
    document: str
    line: int


def validate_origin(origin: Origin) -> None:
    if not isinstance(origin, Origin):
        raise ValueError('origin requires a probe batch and document location')
    require_label(origin.probe_batch, 'probe batch')
    require_label(origin.document, 'document')
    if type(origin.line) is not int or origin.line < 1:
        raise ValueError('origin line must be a positive integer')
