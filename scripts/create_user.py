"""Create a test account with a password you choose (no temporary password, can log in at once).

    python -m scripts.create_user --email stu1@elio.local --name "Student One" --role STUDENT
    python -m scripts.create_user --email prof1@elio.local --name "Prof One" --role INSTRUCTOR --can-create-course

The password is asked for interactively (min 12 characters) and never printed.
For automation set ELIO_NEW_USER_PASSWORD instead. Needs at least one admin to exist.
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
    parser = argparse.ArgumentParser(
        description="Create a STUDENT, INSTRUCTOR or ADMIN account with a chosen password."
    )
    parser.add_argument("--email", required=True)
    parser.add_argument("--name", required=True, help="display name")
    parser.add_argument(
        "--role", required=True, type=str.upper, choices=["STUDENT", "INSTRUCTOR", "ADMIN"]
    )
    parser.add_argument(
        "--can-create-course",
        action="store_true",
        help="instructors only: allow creating courses",
    )
    args = parser.parse_args()

    password = os.environ.get("ELIO_NEW_USER_PASSWORD")
    if not password:
        password = getpass.getpass("Password (min 12 chars): ")
        if password != getpass.getpass("Repeat password: "):
            print("Passwords do not match.", file=sys.stderr)
            return 1

    settings = Settings()
    service = AuthService(MySQLDatabase(settings), settings)
    try:
        user_id = service.create_account_with_password(
            email=args.email,
            display_name=args.name,
            role=args.role,
            password=password,
            can_create_course=args.can_create_course,
        )
    except ApiError as error:
        print(f"{error.code}: {error.detail}", file=sys.stderr)
        return 1
    except DatabaseUnavailable as error:
        print(str(error), file=sys.stderr)
        return 1
    print(f"Created {args.role} {args.email} with id {user_id}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
