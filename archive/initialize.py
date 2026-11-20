from pathlib import Path

from archive.store import Stores, archive_transaction, initialize_archive_store
from ledger.store import custody_transaction, initialize_ledger_store
from review.batches import initialize_batch_store
from source.store import initialize_source_store


def initialize(directory: str | Path) -> Stores:
    root = Path(directory).resolve()
    root.mkdir(parents=True, exist_ok=True)
    stores = Stores(root / 'archive.sqlite3', root / 'ledger.sqlite3')
    with archive_transaction(stores.archive, write=True, create=True) as db:
        initialize_source_store(db)
        initialize_batch_store(db)
        initialize_archive_store(db)
    with custody_transaction(stores.ledger, write=True, create=True) as db:
        initialize_ledger_store(db)
    return stores
