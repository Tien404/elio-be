"""Create the first administrator account (only works while no admin exists).

    python -m scripts.create_admin --email admin@example.edu --name "System Admin"

The password is read interactively (or from ELIO_BOOTSTRAP_PASSWORD for automation)
and never printed.
"""

import argparse
import getpass
import os
import sys

from app.core.config import Settings
from app.core.errors import ApiError
from app.infrastructure.db.connection import DatabaseUnavailable, MySQLDatabase
from app.services.auth_service import AuthService


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", required=True)
    parser.add_argument("--name", required=True)
    args = parser.parse_args()

    password = os.environ.get("ELIO_BOOTSTRAP_PASSWORD")
    if not password:
        password = getpass.getpass("Admin password (min 12 chars): ")
        if password != getpass.getpass("Repeat password: "):
            print("Passwords do not match.", file=sys.stderr)
            return 1

    settings = Settings()
    service = AuthService(MySQLDatabase(settings), settings)
    try:
        user_id = service.bootstrap_admin(
            email=args.email, display_name=args.name, password=password
        )
    except ApiError as error:
        print(f"{error.code}: {error.detail}", file=sys.stderr)
        return 1
    except DatabaseUnavailable as error:
        print(str(error), file=sys.stderr)
        return 1
    print(f"Administrator created with id {user_id}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
