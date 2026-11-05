"""Read-only SQL Server check. Never creates a database, table or user."""

import json
import sys

from app.core.config import Settings
from app.infrastructure.db.connection import DatabaseUnavailable, PyodbcDatabase, load_driver


def main():
    database = PyodbcDatabase(Settings())
    try:
        driver = load_driver()
        database.check_connection()
        with database.read_connection() as connection:
            cursor = connection.cursor()
            try:
                name = cursor.execute("SELECT DB_NAME()").fetchone()[0]
                count = cursor.execute(
                    "SELECT COUNT(*) FROM sys.tables WHERE is_ms_shipped=0"
                ).fetchone()[0]
            finally:
                cursor.close()
    except DatabaseUnavailable:
        print(
            json.dumps(
                {
                    "connection": "NOT_READY",
                    "hint": "Check ODBC runtime/driver, ELIO_ODBC_CONNECTION_STRING and SQL Server access. No schema applied.",
                }
            )
        )
        return 1
    except driver.Error:
        print(
            json.dumps(
                {
                    "connection": "CHECK_FAILED",
                    "hint": "Check database permissions/ODBC configuration locally; diagnostics are not printed to protect credentials.",
                }
            )
        )
        return 1
    print(
        json.dumps(
            {
                "connection": "PASS",
                "database": name,
                "user_table_count": count,
                "business_schema_applied_by_check": False,
            }
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
