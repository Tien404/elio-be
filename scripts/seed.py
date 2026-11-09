from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.core.config import Settings
from app.domain.entities import CourseRole
from app.infrastructure.db.connection import MySQLDatabase, connection_options
from app.infrastructure.db.repositories.assessment_repository import AssessmentRepository
from app.infrastructure.db.repositories.content_repository import ContentRepository
from app.infrastructure.db.repositories.course_repository import CourseRepository
from app.infrastructure.db.repositories.identity_repository import IdentityRepository
from app.infrastructure.db.sql import Sql
from app.services.auth_service import AuthService

PASSWORD = "ElioDemo@2026"


def seed(database: MySQLDatabase):
    name = connection_options(database.settings.database_url.get_secret_value())["database"]
    if not name.endswith("_dev"):
        raise RuntimeError("Sample data requires a database name ending in _dev.")
    auth = AuthService(database, database.settings)
    accounts = {}
    for email, display_name, role in [
        ("admin@elio.local", "Quản trị viên", "ADMIN"),
        ("teacher@elio.local", "Giảng viên mẫu", "INSTRUCTOR"),
        ("student@elio.local", "Sinh viên mẫu", "STUDENT"),
    ]:
        with database.read_connection() as connection:
            existing = IdentityRepository(Sql(connection)).find_by_email(email)
            admin_id = IdentityRepository(Sql(connection)).first_admin_id()
        if existing:
            if existing["role"] != role:
                raise RuntimeError(f"Sample account {email} has a different role.")
            accounts[role] = existing["user_id"]
        elif role == "ADMIN" and admin_id is None:
            accounts[role] = auth.bootstrap_admin(
                email=email, display_name=display_name, password=PASSWORD
            )
        else:
            accounts[role] = auth.create_account_with_password(
                email=email,
                display_name=display_name,
                role=role,
                password=PASSWORD,
                can_create_course=role == "INSTRUCTOR",
            )
    with database.transaction() as connection:
        sql = Sql(connection)
        courses = CourseRepository(sql)
        content = ContentRepository(sql)
        course = courses.find_course_by_code("CS1001")
        if course is None:
            course = courses.insert_course(
                course_code="CS1001",
                course_name="Nhập môn công nghệ phần mềm",
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
                title="Lớp học mẫu ELIO",
                created_by=accounts["INSTRUCTOR"],
            )
            offering_id = offering.offering_id
            sql.execute(
                "UPDATE course_offerings SET state='OPEN',join_code='ELIO26',join_code_enabled=1,learning_information=%s WHERE offering_id=%s",
                "Lớp mẫu để thử các luồng MVP.",
                offering_id,
            )
            courses.insert_membership(
                offering_id=offering_id,
                user_id=accounts["INSTRUCTOR"],
                course_role=CourseRole.PRIMARY_INSTRUCTOR,
            )
            courses.insert_membership(
                offering_id=offering_id, user_id=accounts["STUDENT"], course_role=CourseRole.STUDENT
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
    print("Sample accounts and class are available. See README for local demo credentials.")


if __name__ == "__main__":
    seed(MySQLDatabase(Settings()))
