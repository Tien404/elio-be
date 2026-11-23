import argparse
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.core.config import Settings
from app.core.security import hash_password
from app.domain.entities import CourseRole
from app.infrastructure.db.connection import MySQLDatabase, connection_options
from app.infrastructure.db.repositories.assessment_repository import AssessmentRepository
from app.infrastructure.db.repositories.audit_repository import AuditRepository
from app.infrastructure.db.repositories.content_repository import ContentRepository
from app.infrastructure.db.repositories.course_repository import CourseRepository
from app.infrastructure.db.repositories.identity_repository import IdentityRepository
from app.infrastructure.db.sql import Sql

# Deliberately weak credentials are confined to the development seed.
PASSWORD = "12345678"
DEMO_ACCOUNTS = [
    ("admin@gmail.com", "admin@elio.local", "Quản trị viên", "ADMIN"),
    ("teacher@gmail.com", "teacher@elio.local", "Giảng viên mẫu", "INSTRUCTOR"),
    ("student@gmail.com", "student@elio.local", "Sinh viên mẫu", "STUDENT"),
    ("teacher2@gmail.com", "teacher2@elio.local", "Demo Co-instructor", "INSTRUCTOR"),
    ("student2@gmail.com", "student2@elio.local", "Demo Student B", "STUDENT"),
]


def _seed_accounts(sql, *, reset_demo_credentials=False):
    repo = IdentityRepository(sql)
    accounts = {}
    for email, legacy, display_name, role in DEMO_ACCOUNTS:
        existing = repo.find_by_email(email)
        old = repo.find_by_email(legacy)
        if existing and old and reset_demo_credentials:
            raise RuntimeError(
                f"Both {email} and {legacy} exist; resolve the duplicate before reset."
            )
        existing = existing or old
        if existing:
            if existing["role"] != role:
                raise RuntimeError(f"Sample account {email} has a different role.")
            user_id = existing["user_id"]
            if reset_demo_credentials:
                sql.execute("UPDATE users SET email=%s WHERE user_id=%s", email, user_id)
                repo.update_password(user_id, hash_password(PASSWORD), must_change=False)
                repo.revoke_all_sessions(user_id)
                AuditRepository(sql).record(
                    actor_id=repo.first_admin_id(),
                    action="DEMO_CREDENTIALS_RESET",
                    target_type="ACCOUNT",
                    target_id=user_id,
                    reason="Operator reset of named development sample credentials",
                )
        else:
            # Seed-only insertion avoids weakening ordinary signup/change-password rules.
            user_id = repo.insert_user(
                email=email,
                full_name=display_name,
                password_hash=hash_password(PASSWORD),
                role=role,
                must_change_pwd=False,
                created_by=repo.first_admin_id(),
            )
            if role == "ADMIN":
                repo.insert_admin(user_id)
            elif role == "INSTRUCTOR":
                repo.insert_instructor(user_id, email == "teacher@gmail.com")
            else:
                repo.insert_student(user_id)
            AuditRepository(sql).record(
                actor_id=repo.first_admin_id(),
                action="ACCOUNT_CREATED",
                target_type="ACCOUNT",
                target_id=user_id,
                details={"via": "development_seed"},
            )
        accounts.setdefault(role, user_id)
    return accounts


def seed(database: MySQLDatabase, *, reset_demo_credentials=False):
    name = connection_options(database.settings.database_url.get_secret_value())["database"]
    if not name.endswith("_dev") or database.settings.environment != "development":
        raise RuntimeError("Sample data requires development mode and a database ending in _dev.")
    with database.transaction() as connection:
        accounts = _seed_accounts(Sql(connection), reset_demo_credentials=reset_demo_credentials)
    with database.transaction() as connection:
        sql = Sql(connection)
        courses = CourseRepository(sql)
        content = ContentRepository(sql)
        for code, course_name, title, join_code in (
            ("CS1001", "Nhập môn công nghệ phần mềm", "Lớp học mẫu ELIO", "ELIO26"),
            ("CS2001", "Cơ sở dữ liệu", "Cơ sở dữ liệu · 01", "SQL261"),
            ("CS2002", "Lập trình Web", "Lập trình Web · 01", "WEB261"),
            ("CS2003", "Kiểm thử phần mềm", "Kiểm thử phần mềm · 01", "TST261"),
        ):
            course = courses.find_course_by_code(code)
            if course is None:
                course = courses.insert_course(
                    course_code=code,
                    course_name=course_name,
                    credits=Decimal("3"),
                    description="Học phần mẫu ELIO",
                )
            offering_id = sql.scalar(
                "SELECT offering_id FROM course_offerings WHERE course_id=%s AND semester='HK261' AND section_code='01'",
                course.course_id,
            )
            if offering_id is None:
                offering = courses.insert_offering(
                    course_id=course.course_id,
                    semester="HK261",
                    section_code="01",
                    title=title,
                    created_by=accounts["INSTRUCTOR"],
                )
                offering_id = offering.offering_id
                sql.execute(
                    "UPDATE course_offerings SET state='OPEN',join_code=%s,join_code_enabled=1,learning_information=%s WHERE offering_id=%s",
                    join_code,
                    "Lớp mẫu để thử các luồng MVP.",
                    offering_id,
                )
                courses.insert_membership(
                    offering_id=offering_id,
                    user_id=accounts["INSTRUCTOR"],
                    course_role=CourseRole.PRIMARY_INSTRUCTOR,
                )
                courses.insert_membership(
                    offering_id=offering_id,
                    user_id=accounts["STUDENT"],
                    course_role=CourseRole.STUDENT,
                )
                topic = content.insert_topic(offering_id=offering_id, title="Tuần 1", position=1)
                content.insert_material(
                    data={
                        "topicId": topic.topic_id,
                        "kind": "TEXT",
                        "title": "Giới thiệu học phần",
                        "status": "PUBLISHED",
                        "mandatory": True,
                        "body": "Đọc hướng dẫn và nộp bài tập đầu tiên.",
                    }
                )
                now = datetime.now(UTC)
                AssessmentRepository(sql).insert_assignment(
                    offering_id=offering_id,
                    data={
                        "topicId": topic.topic_id,
                        "mode": "INDIVIDUAL",
                        "maxGroupSize": None,
                        "title": "Bài tập đầu tiên",
                        "maxScore": 10,
                        "weight": 20,
                        "mandatory": True,
                        "status": "PUBLISHED",
                        "instructions": "Tải tệp bài làm và xác nhận nộp bài.",
                        "openAt": now - timedelta(days=1),
                        "dueAt": now + timedelta(days=7),
                        "cutoffAt": now + timedelta(days=8),
                    },
                )
    print(
        "Five sample accounts and four classes are available. See README for local demo credentials."
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed development sample accounts/classes.")
    parser.add_argument(
        "--reset-demo-credentials",
        action="store_true",
        help="Rename the five named legacy sample emails and reset their passwords; revokes their sessions.",
    )
    args = parser.parse_args()
    seed(MySQLDatabase(Settings()), reset_demo_credentials=args.reset_demo_credentials)
