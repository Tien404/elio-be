import json
import sys

from app.core.config import Settings
from app.infrastructure.db.connection import DatabaseUnavailable, MySQLDatabase
from app.infrastructure.db.sql import Sql


def main():
    database = MySQLDatabase(Settings())
    try:
        database.check_connection()
        with database.read_connection() as connection:
            sql = Sql(connection)
            name = sql.scalar("SELECT DATABASE()")
            count = sql.scalar(
                "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = DATABASE()"
            )
    except DatabaseUnavailable:
        print("Check ELIO_DATABASE_URL and MySQL availability.", file=sys.stderr)
        return 1
    print(json.dumps({"database": name, "tables": count}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
