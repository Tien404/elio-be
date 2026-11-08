"""Temporary-password delivery (contract gap API-G05).

The real channel (email, printed slip, ...) is not decided. Until then each issued temporary
password is written to a private file `<outbox>/<account-id>.txt` that only the operator can
read. Passwords are never logged, returned by the API, or stored in the database in clear.
Replace `deliver` once the team agrees on the channel.
"""

import os
from datetime import UTC, datetime
from pathlib import Path


class CredentialOutbox:
    def __init__(self, directory: Path):
        self.directory = directory

    def deliver(self, *, account_id: int, email: str, temporary_password: str) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        target = self.directory / f"{account_id}.txt"
        temp = target.with_suffix(".tmp")
        temp.write_text(
            f"email: {email}\ntemporary_password: {temporary_password}\n"
            f"issued_at: {datetime.now(UTC).isoformat()}\n"
            "The user must change this password at first sign-in.\n",
            encoding="utf-8",
        )
        os.replace(temp, target)
