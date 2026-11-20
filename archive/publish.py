from collections.abc import Callable, Iterable
from sqlite3 import OperationalError

from archive.prepare import bind_request, make_request_binding, prepare_report
from archive.readback import read
from archive.store import (RequestBinding, Stores, archive_transaction, load_request_binding,
                           open_delivery)
from ledger.claims import available_evidence, claim_assignment
from ledger.recovery import recover_custody
from ledger.settlement import acknowledge_delivery
from ledger.store import UnconfirmedCustody, custody_transaction
from review.batches import load_frozen_batch
from review.candidates import CandidateGraph, RequestSlot, build_candidate_graph, restrict_graph
from review.matching import find_assignment

BEFORE_CLAIM = 'before_claim'
AFTER_PREPARE = 'after_prepare'
BEFORE_COMMIT = 'before_commit'
AFTER_COMMIT = 'after_commit'


class ConfirmationInterrupted(RuntimeError):
    """The caller did not receive a confirmed result for this attempt."""


def _plan(stores: Stores, binding: RequestBinding, graph: CandidateGraph):
    with custody_transaction(stores.ledger) as db:
        custody = recover_custody(db, binding.request_id, binding.batch_id, binding.parameters)
        if custody is not None:
            return custody, None, False
        free, held = available_evidence(db, (key for _, options in graph for key in options))
    assignment = find_assignment(restrict_graph(graph, free))
    blocked_by_hold = bool(held) and assignment is None and (
        find_assignment(restrict_graph(graph, free | held)) is not None
    )
    return None, assignment, blocked_by_hold


def sign(stores: Stores, batch_id: str, request_id: str, slots: Iterable[RequestSlot], *,
         checkpoint: Callable[[str], None] | None = None) -> dict:
    requested = tuple(slots)
    binding = make_request_binding(batch_id, request_id, requested)

    def notify(stage: str) -> None:
        if checkpoint is not None:
            checkpoint(stage)

    try:
        with archive_transaction(stores.archive) as db:
            existing = load_request_binding(db, request_id)
            if existing is not None and existing != binding:
                return {'status': 'request_conflict'}
            batch = load_frozen_batch(db, batch_id)
        if batch is None:
            return {'status': 'unknown_batch'}
        graph = build_candidate_graph(batch, requested)
        if existing is None and bind_request(stores.archive, binding) != binding:
            return {'status': 'request_conflict'}

        custody, assignment, blocked = _plan(stores, binding, graph)
        if custody is None and assignment is not None:
            notify(BEFORE_CLAIM)
            custody = claim_assignment(stores.ledger, request_id, batch_id, binding.parameters, assignment)
            if custody is None:
                custody, assignment, blocked = _plan(stores, binding, graph)
                if custody is None and assignment is not None:
                    return {'status': 'pending', 'request_id': request_id}
        if custody is None:
            return {'status': 'pending' if blocked else 'not_enough', 'request_id': request_id}
        if custody.state == 'cancelled':
            return {'status': 'cancelled', 'request_id': request_id}
        if custody.state == 'issued':
            return read(stores, binding.report_id)

        material = prepare_report(stores.archive, binding, batch, custody.assignment)
        notify(AFTER_PREPARE)
        with archive_transaction(stores.archive, write=True) as db:
            opened = open_delivery(db, material.report_id)
            if opened:
                notify(BEFORE_COMMIT)
        if opened:
            notify(AFTER_COMMIT)
        state = acknowledge_delivery(stores, binding)
        if state != 'issued':
            return {'status': state, 'request_id': request_id}
        return read(stores, material.report_id)
    except (OperationalError, UnconfirmedCustody, ConfirmationInterrupted):
        return {'status': 'pending', 'request_id': request_id}
