import pytest

from app.infrastructure.db.sql import Sql
from scripts.migrate import apply_migrations


def test_existing_policy_objects_can_be_recorded_and_rerun(database):
    with database.transaction() as connection:
        Sql(connection).execute(
            "DELETE FROM schema_migrations WHERE migration_id IN ('011_main_release_policies','012_bank_copy_sources')"
        )
    apply_migrations(database)
    apply_migrations(database)
    with database.read_connection() as connection:
        assert (
            Sql(connection).scalar(
                "SELECT COUNT(*) FROM schema_migrations WHERE migration_id IN ('011_main_release_policies','012_bank_copy_sources')"
            )
            == 2
        )


def test_partially_present_question_columns_resume(database):
    with database.transaction() as connection:
        sql = Sql(connection)
        sql.execute("ALTER TABLE questions DROP CHECK CK_questions_source_version")
        sql.execute("ALTER TABLE questions DROP COLUMN source_version")
        sql.execute("DELETE FROM schema_migrations WHERE migration_id='012_bank_copy_sources'")
    try:
        apply_migrations(database)
        with database.read_connection() as connection:
            sql = Sql(connection)
            assert (
                sql.scalar(
                    "SELECT COUNT(*) FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='questions' AND column_name IN ('source_question_id','source_version')"
                )
                == 2
            )
    finally:
        apply_migrations(database)


def test_incompatible_column_is_rejected_not_marked_complete(database):
    with database.transaction() as connection:
        sql = Sql(connection)
        sql.execute("ALTER TABLE questions MODIFY COLUMN source_version BIGINT NULL")
        sql.execute("DELETE FROM schema_migrations WHERE migration_id='012_bank_copy_sources'")
    try:
        with pytest.raises(
            RuntimeError, match="incompatible existing column questions.source_version"
        ):
            apply_migrations(database)
        with database.read_connection() as connection:
            assert (
                Sql(connection).scalar(
                    "SELECT COUNT(*) FROM schema_migrations WHERE migration_id='012_bank_copy_sources'"
                )
                == 0
            )
    finally:
        with database.transaction() as connection:
            Sql(connection).execute("ALTER TABLE questions MODIFY COLUMN source_version INT NULL")
        apply_migrations(database)
