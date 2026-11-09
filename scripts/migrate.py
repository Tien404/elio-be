from pathlib import Path

from app.core.config import Settings
from app.infrastructure.db.connection import MySQLDatabase
from app.infrastructure.db.sql import Sql

MIGRATIONS = Path(__file__).resolve().parents[1] / "sql" / "migrations"


def apply_migrations(database: MySQLDatabase):
    with database.transaction() as connection:
        sql = Sql(connection)
        if sql.scalar("SELECT GET_LOCK('elio_schema_migrations', 30)") != 1:
            raise RuntimeError("Another migration process is running.")
        try:
            bootstrap = MIGRATIONS / "000_schema_migrations.sql"
            sql.execute(bootstrap.read_text())
            applied = {
                r["migration_id"] for r in sql.all("SELECT migration_id FROM schema_migrations")
            }
            for path in sorted(MIGRATIONS.glob("*.sql")):
                if path.stem in applied:
                    continue
                if path != bootstrap:
                    # Migration files contain plain statements, without routines or DELIMITER blocks.
                    source = "\n".join(
                        line
                        for line in path.read_text().splitlines()
                        if not line.lstrip().startswith("--")
                    )
                    for statement in source.split(";"):
                        if statement.strip():
                            sql.execute(statement)
                sql.execute("INSERT INTO schema_migrations (migration_id) VALUES (%s)", path.stem)
                connection.commit()
                print(path.stem)
        finally:
            sql.scalar("SELECT RELEASE_LOCK('elio_schema_migrations')")


if __name__ == "__main__":
    apply_migrations(MySQLDatabase(Settings()))
