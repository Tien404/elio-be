"""Groups for group assignments (class diagram: GroupService, AssignmentGroup).

The professor marks an assignment as group work with a largest group size. Groups are
made by the professor (name + members) or by students (create one and are put in it,
or join one with space). Any member hands in for the group; once the group has a
submission its members are fixed.
"""

from typing import Any

from app.core.errors import ApiError, conflict, forbidden, not_found
from app.domain.context import Actor
from app.domain.entities import AssignmentGroup
from app.infrastructure.db.repositories.assessment_repository import AssessmentRepository
from app.infrastructure.db.repositories.audit_repository import AuditRepository
from app.infrastructure.db.repositories.course_repository import CourseRepository
from app.infrastructure.db.repositories.grading_repository import GradingRepository
from app.infrastructure.db.repositories.group_repository import GroupRepository
from app.infrastructure.db.sql import Sql, is_unique_violation
from app.services.access import is_teacher, require_member, require_student, require_teacher


def group_view(row: dict[str, Any], max_size: int) -> dict[str, Any]:
    return {
        "id": row["group_id"],
        "assignmentId": row["assignment_id"],
        "name": row["name"],
        "members": [
            {"id": m["user_id"], "displayName": m["full_name"], "studentCode": m["student_code"]}
            for m in row["members"]
        ],
        "size": len(row["members"]),
        "maxSize": max_size,
        "locked": bool(row["locked"]),
        "version": row["version"],
    }


def group_from_row(row: dict[str, Any]) -> AssignmentGroup:
    return AssignmentGroup(
        group_id=row["group_id"],
        assignment_id=row["assignment_id"],
        name=row["name"],
        member_ids=[m["user_id"] for m in row["members"]],
        locked=bool(row["locked"]),
    )


class GroupService:
    def __init__(self, database=None):
        self.database = database

    # ------------------------------------------------------------------ reading
    def list_groups(self, *, actor: Actor, assignment_id: int) -> dict[str, Any]:
        """All groups of the assignment (students need them to pick one), and mine."""
        with self.database.transaction() as connection:
            sql = Sql(connection)
            assignment, _ = self._group_assignment(sql, actor, assignment_id)
            groups = GroupRepository(sql)
            return {
                "assignmentId": assignment_id,
                "maxGroupSize": assignment["max_group_size"],
                "myGroupId": groups.group_of(assignment_id, actor.user_id),
                "items": [
                    group_view(g, assignment["max_group_size"])
                    for g in groups.list_groups(assignment_id)
                ],
            }

    def get_group(self, *, actor: Actor, group_id: int) -> dict[str, Any]:
        with self.database.transaction() as connection:
            sql = Sql(connection)
            row = self._existing_group(sql, group_id)
            assignment, _ = self._group_assignment(sql, actor, row["assignment_id"])
            return group_view(row, assignment["max_group_size"])

    # ------------------------------------------------------------------ writing
    def create_group(
        self, *, actor: Actor, assignment_id: int, name: str, member_ids: list[int] | None
    ) -> dict[str, Any]:
        """Professor: a named group with chosen members (may be empty).
        Student: a named group that they are put in."""
        name = name.strip()
        if not name:
            raise ApiError(400, "INVALID_REQUEST", "Name must not be blank.")
        with self.database.transaction() as connection:
            sql = Sql(connection)
            assignment, teacher = self._group_assignment(sql, actor, assignment_id, write=True)
            groups = GroupRepository(sql)
            if teacher:
                members = member_ids or []
                self._check_members(sql, assignment, members)
            else:
                if member_ids:
                    raise ApiError(
                        400, "INVALID_REQUEST", "Students create a group for themselves."
                    )
                self._check_free(sql, assignment_id, actor.user_id)
                members = [actor.user_id]
            try:
                group_id = groups.insert_group(assignment_id, name)
            except Exception as error:
                if is_unique_violation(error):
                    raise conflict("GROUP_NAME_TAKEN", "Another group has this name.") from None
                raise
            groups.set_members(group_id, assignment_id, members)
            AuditRepository(sql).record(
                actor_id=actor.user_id,
                action="GROUP_CREATED",
                target_type="GROUP",
                target_id=group_id,
                details={"members": len(members)},
            )
            return group_view(groups.get_group(group_id), assignment["max_group_size"])

    def update_group(
        self, *, actor: Actor, group_id: int, name: str | None, member_ids: list[int] | None
    ) -> dict[str, Any]:
        """Professor renames a group or sets its members."""
        with self.database.transaction() as connection:
            sql = Sql(connection)
            groups = GroupRepository(sql)
            row = self._existing_group(sql, group_id)
            assignment = AssessmentRepository(sql).get_assignment(row["assignment_id"])
            require_teacher(CourseRepository(sql), actor, assignment["offering_id"])
            row = groups.get_group(group_id, lock=True)
            if name is not None:
                if not name.strip():
                    raise ApiError(400, "INVALID_REQUEST", "Name must not be blank.")
                try:
                    groups.rename(group_id, name.strip())
                except Exception as error:
                    if is_unique_violation(error):
                        raise conflict("GROUP_NAME_TAKEN", "Another group has this name.") from None
                    raise
            if member_ids is not None:
                if row["locked"]:
                    raise conflict("GROUP_LOCKED", "This group has submitted; members are fixed.")
                self._check_members(sql, assignment, member_ids, group_id=group_id)
                groups.set_members(group_id, row["assignment_id"], member_ids)
            return group_view(groups.get_group(group_id), assignment["max_group_size"])

    def join_group(self, *, actor: Actor, group_id: int) -> dict[str, Any]:
        """Student joins a group that still has space (AssignmentGroup.join)."""
        with self.database.transaction() as connection:
            sql = Sql(connection)
            groups = GroupRepository(sql)
            row = self._existing_group(sql, group_id)
            assignment, teacher = self._group_assignment(
                sql, actor, row["assignment_id"], write=True
            )
            if teacher:
                raise forbidden("Professors set members with the group's edit.")
            row = groups.get_group(group_id, lock=True)
            self._check_free(sql, row["assignment_id"], actor.user_id)
            group = group_from_row(row)
            try:
                group.join(actor.user_id, assignment["max_group_size"])
            except ValueError as error:
                raise conflict("GROUP_NOT_JOINABLE", str(error)) from None
            groups.set_members(group_id, row["assignment_id"], group.member_ids)
            return group_view(groups.get_group(group_id), assignment["max_group_size"])

    def leave_group(self, *, actor: Actor, group_id: int) -> None:
        """Student leaves their group (AssignmentGroup.leave); an emptied group is removed."""
        with self.database.transaction() as connection:
            sql = Sql(connection)
            groups = GroupRepository(sql)
            row = self._existing_group(sql, group_id)
            _, teacher = self._group_assignment(sql, actor, row["assignment_id"], write=True)
            if teacher:
                raise forbidden("Professors set members with the group's edit.")
            row = groups.get_group(group_id, lock=True)
            group = group_from_row(row)
            try:
                group.leave(actor.user_id)
            except ValueError as error:
                raise conflict("GROUP_NOT_LEAVABLE", str(error)) from None
            if group.member_ids:
                groups.set_members(group_id, row["assignment_id"], group.member_ids)
            else:
                groups.delete_group(group_id)

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _existing_group(sql: Sql, group_id: int) -> dict[str, Any]:
        row = GroupRepository(sql).get_group(group_id)
        if row is None:
            raise not_found("Group")
        return row

    @staticmethod
    def _group_assignment(sql: Sql, actor: Actor, assignment_id: int, *, write=False):
        """The group assignment, visible to the actor. write=True: the professor of a
        writable class, or a student of an open class (published assignment)."""
        assignment = AssessmentRepository(sql).get_assignment(assignment_id)
        if assignment is None:
            raise not_found("Assignment")
        courses = CourseRepository(sql)
        teacher = is_teacher(require_member(courses, actor, assignment["offering_id"]))
        if not teacher and assignment["status"] != "PUBLISHED":
            raise not_found("Assignment")
        if not assignment["is_group_work"]:
            raise conflict("NOT_GROUP_WORK", "This assignment is not group work.")
        if write:
            if teacher:
                require_teacher(courses, actor, assignment["offering_id"])
            else:
                require_student(courses, actor, assignment["offering_id"])
        return assignment, teacher

    @staticmethod
    def _check_free(sql: Sql, assignment_id: int, student_id: int) -> None:
        """The student is in no group yet and has no grade of their own for this work."""
        if GroupRepository(sql).group_of(assignment_id, student_id) is not None:
            raise conflict("ALREADY_IN_GROUP", "Leave your current group first.")
        if AssessmentRepository(sql).student_has_grade(assignment_id, student_id):
            raise conflict("ALREADY_GRADED", "You already have a grade for this assignment.")

    @staticmethod
    def _check_members(sql, assignment, member_ids: list[int], group_id: int | None = None):
        if len(set(member_ids)) != len(member_ids):
            raise ApiError(400, "INVALID_REQUEST", "A student is listed twice.")
        if len(member_ids) > assignment["max_group_size"]:
            raise ApiError(
                422, "GROUP_TOO_LARGE", f"At most {assignment['max_group_size']} members."
            )
        groups = GroupRepository(sql)
        for student_id in member_ids:
            if GradingRepository(sql).find_student(assignment["offering_id"], student_id) is None:
                raise ApiError(422, "STUDENT_NOT_FOUND", "Members must be students of the class.")
            current = groups.group_of(assignment["activity_id"], student_id)
            if current is not None and current != group_id:
                raise conflict("ALREADY_IN_GROUP", "A student is already in another group.")
            if current is None and AssessmentRepository(sql).student_has_grade(
                assignment["activity_id"], student_id
            ):
                raise conflict("ALREADY_GRADED", "A student already has their own grade.")
