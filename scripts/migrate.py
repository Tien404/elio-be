import re
from pathlib import Path

from app.core.config import Settings
from app.infrastructure.db.connection import MySQLDatabase
from app.infrastructure.db.sql import Sql

MIGRATIONS = Path(__file__).resolve().parents[1] / "sql" / "migrations"


# These additive policy upgrades can meet schemas upgraded under older migration
# names, or resume after MySQL's implicit DDL commits. Never ignore duplicate DDL
# blindly: an existing object must match the expected definition.
def _resume_policy_upgrade(sql: Sql, migration_id: str) -> bool:
    if migration_id == "011_main_release_policies":
        columns = [
            (
                "assignments",
                "group_formation",
                "VARCHAR(12) NOT NULL DEFAULT 'SELF'",
                "varchar(12)",
                "NO",
                "SELF",
            ),
            (
                "quizzes",
                "release_policy",
                "VARCHAR(12) NOT NULL DEFAULT 'IMMEDIATE'",
                "varchar(12)",
                "NO",
                "IMMEDIATE",
            ),
            ("quiz_snapshot_questions", "source_version", "INT NULL", "int", "YES", None),
        ]
        checks = [
            ("assignments", "CK_group_formation", "group_formation IN ('SELF','INSTRUCTOR')"),
            ("quizzes", "CK_quiz_release_policy", "release_policy IN ('AFTER_CLOSE','IMMEDIATE')"),
        ]
    elif migration_id == "012_bank_copy_sources":
        columns = [
            ("questions", "source_question_id", "INT NULL", "int", "YES", None),
            ("questions", "source_version", "INT NULL", "int", "YES", None),
        ]
        checks = [
            (
                "questions",
                "CK_questions_source_version",
                "source_version IS NULL OR source_version >= 1",
            )
        ]
    else:
        return False
    # Read/validate every existing object before executing any DDL in this upgrade.
    pending = []
    for table, column, definition, kind, nullable, default in columns:
        actual = sql.one(
            "SELECT COLUMN_TYPE AS kind,IS_NULLABLE AS nullable,COLUMN_DEFAULT AS default_value "
            "FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name=%s AND column_name=%s",
            table,
            column,
        )
        if actual is None:
            pending.append(f"ALTER TABLE `{table}` ADD COLUMN `{column}` {definition}")
        elif (actual["kind"].lower(), actual["nullable"], actual["default_value"]) != (
            kind,
            nullable,
            default,
        ):
            raise RuntimeError(
                f"{migration_id}: incompatible existing column {table}.{column}; inspect schema before retrying."
            )
    for table, name, expression in checks:
        actual = sql.one(
            "SELECT cc.CHECK_CLAUSE AS clause,tc.ENFORCED AS enforced "
            "FROM information_schema.table_constraints tc JOIN information_schema.check_constraints cc "
            "ON tc.CONSTRAINT_SCHEMA=cc.CONSTRAINT_SCHEMA AND tc.CONSTRAINT_NAME=cc.CONSTRAINT_NAME "
            "WHERE tc.CONSTRAINT_SCHEMA=DATABASE() AND tc.TABLE_NAME=%s AND tc.CONSTRAINT_NAME=%s AND tc.CONSTRAINT_TYPE='CHECK'",
            table,
            name,
        )
        if actual is None:
            pending.append(f"ALTER TABLE `{table}` ADD CONSTRAINT `{name}` CHECK ({expression})")
        elif actual["enforced"] != "YES" or _check_expression(
            actual["clause"]
        ) != _check_expression(expression):
            raise RuntimeError(
                f"{migration_id}: incompatible existing check {table}.{name}; inspect schema before retrying."
            )
    for statement in pending:
        sql.execute(statement)
    if migration_id == "011_main_release_policies":
        sql.execute(
            "INSERT IGNORE INTO submission_roster (submission_id,student_id) "
            "SELECT s.submission_id,m.student_id FROM submissions s JOIN group_members m ON m.group_id=s.group_id"
        )
        sql.execute(
            "UPDATE submissions SET roster_frozen_at=COALESCE(roster_frozen_at,UTC_TIMESTAMP(6)) WHERE group_id IS NOT NULL"
        )
    return True


def _check_expression(value: str) -> str:
    # MySQL adds identifier quotes, charset introducers and escaping when storing
    # these simple IN / IS NULL checks in information_schema.
    value = re.sub(r"_[a-zA-Z0-9]+(?=\\?'|')", "", value)
    return re.sub(r"[\s`()\\]", "", value).lower()


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
                if path != bootstrap and not _resume_policy_upgrade(sql, path.stem):
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
