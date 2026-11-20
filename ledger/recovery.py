from sqlite3 import Connection

from ledger.claims import verify_claims
from ledger.store import CustodyRecord, UnconfirmedCustody, load_custody_record


def recover_custody(db: Connection, request_id: str, batch_id: str,
                    parameters: str) -> CustodyRecord | None:
    record = load_custody_record(db, request_id)
    if record is None:
        return None
    if not record.matches(batch_id, parameters):
        raise UnconfirmedCustody('request binding differs across stores')
    verify_claims(db, record)
    return record


def list_unconfirmed_requests(db: Connection, batch_id: str) -> list[str]:
    rows = db.execute('''SELECT request_id FROM custody_requests
                         WHERE batch_id = ? AND state = 'held' ORDER BY request_id''', (batch_id,))
    return [row['request_id'] for row in rows]
