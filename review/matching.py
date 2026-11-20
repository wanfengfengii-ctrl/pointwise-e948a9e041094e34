from collections import deque

from review.candidates import Assignment, CandidateGraph


def _augment(graph: CandidateGraph, root: int, unavailable: set[str],
             occupied: dict[str, int], selected: dict[int, str]) -> bool:
    queue = deque([root])
    visited = {root}
    via = {}
    while queue:
        slot = queue.popleft()
        for evidence in graph[slot][1]:
            if evidence in unavailable or evidence in via:
                continue
            via[evidence] = slot
            owner = occupied.get(evidence)
            if owner is None:
                while evidence is not None:
                    slot = via[evidence]
                    previous = selected.get(slot)
                    occupied[evidence] = slot
                    selected[slot] = evidence
                    evidence = previous
                return True
            if owner not in visited:
                visited.add(owner)
                queue.append(owner)
    return False


def _can_cover(graph: CandidateGraph, start: int, unavailable: set[str]) -> bool:
    occupied = {}
    selected = {}
    return all(_augment(graph, slot, unavailable, occupied, selected)
               for slot in range(start, len(graph)))


def find_assignment(graph: CandidateGraph) -> Assignment | None:
    """Choose each earliest option that can still extend to a complete assignment."""
    chosen = []
    used = set()
    for index, (slot, options) in enumerate(graph):
        for evidence in options:
            if evidence not in used and _can_cover(graph, index + 1, used | {evidence}):
                chosen.append((slot, evidence))
                used.add(evidence)
                break
        else:
            return None
    return tuple(chosen)
