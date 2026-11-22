import argparse
import sys


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Inspect without running jobs")
    parser.add_argument("--process-quizzes", action="store_true")
    parser.add_argument("--cleanup-staging", action="store_true")
    args = parser.parse_args()
    if args.process_quizzes:
        from app.core.config import Settings
        from app.infrastructure.db.connection import MySQLDatabase
        from app.services.quiz_service import QuizService

        print(
            f"Processed {QuizService(MySQLDatabase(Settings())).finalize_expired_attempts()} course batches."
        )
        return 0
    if args.cleanup_staging:
        print(f"Removed {cleanup_staging()} staging files.")
        return 0
    if args.check:
        print("Quiz finalizer and staging cleanup are available.")
        return 0
    print("NOT IMPLEMENTED: no jobs started; not working.")
    return 2


def cleanup_staging():
    from app.core.config import Settings
    from app.infrastructure.db.connection import MySQLDatabase
    from app.infrastructure.db.sql import Sql
    from app.infrastructure.file_storage import FileStorage

    settings = Settings()
    with MySQLDatabase(settings).transaction() as connection:
        sql = Sql(connection)
        rows = sql.all(
            "SELECT file_id,file_key FROM file_assets WHERE state='STAGING' AND expires_at<=UTC_TIMESTAMP(6) ORDER BY file_id LIMIT 100 FOR UPDATE"
        )
        for row in rows:
            FileStorage(settings.private_files_dir).delete(row["file_key"])
            sql.execute(
                "DELETE FROM file_assets WHERE file_id=%s AND state='STAGING'", row["file_id"]
            )
        return len(rows)


if __name__ == "__main__":
    sys.exit(main())
