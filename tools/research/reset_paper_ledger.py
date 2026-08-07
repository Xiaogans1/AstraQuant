"""Reset the paper ledger: drop all records and recreate the default account."""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from decimal import Decimal

from astraquant_api.config import RuntimeConfig
from astraquant_api.database import create_database, migrate_database
from astraquant_api.paper_repository import PaperRepository
from astraquant_domain import AccountMode, PaperAccount


def reset_ledger() -> str:
    config = RuntimeConfig.from_environment()
    database_url = f"sqlite:///{config.database_path}"
    migrate_database(database_url)
    repository = PaperRepository(create_database(database_url))
    accounts = repository.list_accounts()
    for account in accounts:
        repository.delete_account(account.account_id)
    now = datetime.now(UTC)
    repository.create_account(
        PaperAccount(
            account_id="default-paper-account",
            name="主模拟账户",
            mode=AccountMode.PAPER,
            initial_cash=Decimal("100000"),
            cash=Decimal("100000"),
            created_at=now,
            updated_at=now,
        )
    )
    return str(len(accounts))


if __name__ == "__main__":
    removed = reset_ledger()
    print(f"reset: removed {removed} account(s), recreated default paper account (cash 100000)")
    sys.exit(0)
