from collections.abc import Iterable

BALANCE_STATES = ('used', 'available', 'held', 'missing', 'ineligible', 'unconfirmed')


def count_balance(evidence: Iterable[dict]) -> dict[str, int]:
    counts = dict.fromkeys(BALANCE_STATES, 0)
    seen = {}
    for row in evidence:
        key, state = row['evidence_id'], row['status']
        if key in seen:
            if seen[key] != state:
                raise ValueError('conflicting states for the same evidence')
            continue
        seen[key] = state
        counts[state] += 1
    return counts
