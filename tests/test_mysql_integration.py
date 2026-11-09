from concurrent.futures import ThreadPoolExecutor
from datetime import UTC
from decimal import Decimal
from threading import Barrier

import pymysql
import pytest

from app.domain.context import Actor
from app.domain.entities import CourseRole, DegreeLevel, SystemRole
from app.infrastructure.db.repositories.content_repository import ContentRepository
from app.infrastructure.db.repositories.course_repository import CourseRepository
from app.infrastructure.db.sql import Sql
from app.services.content_service import ContentService
from app.services.course_service import CourseService
from scripts.migrate import apply_migrations
from tests.helpers import class_with_student


def test_mysql_migrations_can_be_repeated_and_reads_are_read_only(database):
    apply_migrations(database)
    apply_migrations(database)
    with database.read_connection() as connection:
        sql = Sql(connection)
        assert sql.scalar("SELECT COUNT(*) FROM schema_migrations") == 8
        assert sql.scalar("SELECT @@session.time_zone") == "+00:00"
        assert sql.scalar("SELECT @@session.transaction_isolation") == "READ-COMMITTED"
        assert sql.scalar("SELECT UTC_TIMESTAMP(6)").tzinfo == UTC
        with pytest.raises(pymysql.MySQLError) as error:
            sql.execute("DELETE FROM audit_entries")
        assert error.value.args[0] == 1792


def test_mysql_conditional_unique_role_and_schedule_constraints(api):
    c = class_with_student(api)
    db = api.app.state.database
    with db.transaction() as connection:
        sql = Sql(connection)
        courses = CourseRepository(sql)
        with pytest.raises(pymysql.MySQLError) as error:
            courses.insert_membership(
                offering_id=c.offering_id,
                user_id=c.outsider.account_id,
                course_role=CourseRole.PRIMARY_INSTRUCTOR,
            )
        assert error.value.args[0] == 1452  # Student cannot be an instructor member.
        with pytest.raises(pymysql.MySQLError) as error:
            courses.insert_membership(
                offering_id=c.offering_id,
                user_id=c.admin.account_id,
                course_role=CourseRole.PRIMARY_INSTRUCTOR,
            )
        assert error.value.args[0] == 1452
        # A second active lead is rejected, but a removed lead no longer reserves the key.
        teacher = sql.insert(
            "INSERT INTO users (email,full_name,password_hash,role,must_change_pwd) VALUES (%s,%s,'x','INSTRUCTOR',0)",
            "second@elio.test",
            "Giảng viên thứ hai",
        )
        sql.execute("INSERT INTO instructors (user_id) VALUES (%s)", teacher)
        with pytest.raises(pymysql.MySQLError) as error:
            courses.insert_membership(
                offering_id=c.offering_id,
                user_id=teacher,
                course_role=CourseRole.PRIMARY_INSTRUCTOR,
            )
        assert error.value.args[0] == 1062
        sql.execute(
            "UPDATE course_memberships SET status='REMOVED' WHERE offering_id=%s AND user_id=%s",
            c.offering_id,
            c.prof.account_id,
        )
        courses.insert_membership(
            offering_id=c.offering_id, user_id=teacher, course_role=CourseRole.PRIMARY_INSTRUCTOR
        )
        activity = sql.insert(
            "INSERT INTO activities (offering_id,activity_type,title,max_score) VALUES (%s,'ASSIGNMENT','Invalid dates',10)",
            c.offering_id,
        )
        with pytest.raises(pymysql.MySQLError) as error:
            sql.execute(
                "INSERT INTO assignments (activity_id,instructions,open_at,due_at,cutoff_at) VALUES (%s,'', '2026-11-10','2026-11-09','2026-11-11')",
                activity,
            )
        assert error.value.args[0] == 3819


def test_mysql_literal_search_and_unicode(api):
    class_with_student(api)
    with api.app.state.database.transaction() as connection:
        repo = CourseRepository(Sql(connection))
        repo.insert_course(
            course_code="CS1098",
            course_name="Tiếng Việt 100%_[]!",
            credits=Decimal("3"),
            description=None,
        )
        repo.insert_course(
            course_code="CS1099",
            course_name="Tiếng Việt 100xyz",
            credits=Decimal("3"),
            description=None,
        )
        rows, total = repo.search_courses(code_prefix=None, name_part="%_[]!", offset=0, limit=10)
        assert total == 1 and rows[0].course_name == "Tiếng Việt 100%_[]!"


def test_mysql_concurrent_topic_creation_preserves_positions(api):
    c = class_with_student(api)
    db = api.app.state.database
    actor = Actor(user_id=c.prof.account_id, role=SystemRole.INSTRUCTOR)
    start = Barrier(2)

    def create(number):
        start.wait(timeout=5)
        return ContentService(db).create_topic(
            actor=actor, offering_id=c.offering_id, title=f"Topic {number}"
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        topics = list(pool.map(create, [1, 2]))
    assert sorted(t["position"] for t in topics) == [1, 2]
    with db.read_connection() as connection:
        assert (
            len(
                ContentRepository(Sql(connection)).list_topics(c.offering_id, offset=0, limit=10)[0]
            )
            == 2
        )


def test_mysql_concurrent_catalog_code_allocation(api):
    c = class_with_student(api)
    actor = Actor(user_id=c.admin.account_id, role=SystemRole.ADMIN)
    start = Barrier(2)

    def create(number):
        start.wait(timeout=5)
        return CourseService(api.app.state.database).create_course(
            actor=actor,
            faculty="CS",
            year=1,
            degree=DegreeLevel.UNDERGRADUATE,
            name=f"Course {number}",
            credits=Decimal("3"),
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        courses = list(pool.map(create, [1, 2]))
    assert len({c["courseCode"] for c in courses}) == 2
