"MySQL SQL for assignment groups and their members. Never commits."

from typing import Any

from app.infrastructure.db.sql import Sql

# A group is locked once it has a submission (handed in, or a grade given for missing work).
_GROUP_SELECT = """SELECT g.group_id, g.assignment_id, g.name, g.version,
        (SELECT MIN(roster_frozen_at) FROM submissions s WHERE s.group_id=g.group_id) AS locked_at,
        EXISTS (SELECT 1 FROM submissions AS s WHERE s.group_id = g.group_id) AS locked
    FROM assignment_groups AS g"""


class GroupRepository:
    def __init__(self, sql: Sql):
        self.sql = sql

    def list_groups(self, assignment_id: int) -> list[dict[str, Any]]:
        groups = self.sql.all(
            f"{_GROUP_SELECT} WHERE g.assignment_id = %s ORDER BY g.name, g.group_id",
            assignment_id,
        )
        members = self.sql.all(
            """SELECT m.group_id, u.user_id, u.full_name, st.student_code, u.status AS account_status
               FROM group_members AS m
               JOIN users AS u ON u.user_id = m.student_id
               JOIN students AS st ON st.user_id = m.student_id
               WHERE m.assignment_id = %s ORDER BY u.full_name, u.user_id""",
            assignment_id,
        )
        for group in groups:
            group["members"] = [m for m in members if m["group_id"] == group["group_id"]]
        return groups

    def get_group(self, group_id: int, *, lock: bool = False) -> dict[str, Any] | None:
        if lock:
            self.sql.execute(
                "SELECT 1 FROM assignment_groups WHERE group_id = %s FOR UPDATE", group_id
            )
        group = self.sql.one(f"{_GROUP_SELECT} WHERE g.group_id = %s", group_id)
        if group is not None:
            group["members"] = self.sql.all(
                """SELECT m.group_id, u.user_id, u.full_name, st.student_code, u.status AS account_status
                   FROM group_members AS m
                   JOIN users AS u ON u.user_id = m.student_id
                   JOIN students AS st ON st.user_id = m.student_id
                   WHERE m.group_id = %s ORDER BY u.full_name, u.user_id""",
                group_id,
            )
        return group

    def group_of(self, assignment_id: int, student_id: int) -> int | None:
        """The student's group for this assignment, if any."""
        return self.sql.scalar(
            "SELECT group_id FROM group_members WHERE assignment_id = %s AND student_id = %s",
            assignment_id,
            student_id,
        )

    def insert_group(self, assignment_id: int, name: str) -> int:
        return self.sql.insert(
            "INSERT INTO assignment_groups (assignment_id, name) VALUES (%s, %s)",
            assignment_id,
            name,
        )

    def rename(self, group_id: int, name: str) -> None:
        self.sql.execute(
            "UPDATE assignment_groups SET name = %s, version = version + 1 WHERE group_id = %s",
            name,
            group_id,
        )

    def set_members(self, group_id: int, assignment_id: int, member_ids: list[int]) -> None:
        self.sql.execute("DELETE FROM group_members WHERE group_id = %s", group_id)
        for student_id in member_ids:
            self.sql.execute(
                """INSERT INTO group_members (group_id, assignment_id, student_id)
                   VALUES (%s, %s, %s)""",
                group_id,
                assignment_id,
                student_id,
            )
        self.sql.execute(
            "UPDATE assignment_groups SET version = version + 1 WHERE group_id = %s", group_id
        )

    def delete_group(self, group_id: int) -> None:
        self.sql.execute("DELETE FROM group_members WHERE group_id = %s", group_id)
        self.sql.execute("DELETE FROM assignment_groups WHERE group_id = %s", group_id)

    def lock_group_submission(self, group_id: int) -> dict[str, Any] | None:
        return self.sql.one(
            """SELECT submission_id, status, version FROM submissions
               WHERE group_id = %s FOR UPDATE""",
            group_id,
        )

    def insert_group_submission(self, assignment_id: int, group_id: int) -> int:
        return self.sql.insert(
            """INSERT INTO submissions (assignment_id, owner_type, group_id)
               VALUES (%s, 'GROUP', %s)""",
            assignment_id,
            group_id,
        )

    def freeze_roster(self, submission_id: int, group_id: int) -> None:
        """First hand-in: record who was in the group."""
        self.sql.execute(
            "UPDATE submissions SET roster_frozen_at = UTC_TIMESTAMP(6) WHERE submission_id = %s",
            submission_id,
        )
        self.sql.execute(
            """INSERT INTO submission_roster (submission_id, student_id)
               SELECT %s, student_id FROM group_members WHERE group_id = %s""",
            submission_id,
            group_id,
        )

    def submission_members(self, submission_id: int) -> list[int]:
        """Who a submission belongs to: the student, or the group's members."""
        return [
            r["student_id"]
            for r in self.sql.all(
                """SELECT s.student_id FROM submissions AS s
                   WHERE s.submission_id = %s AND s.student_id IS NOT NULL
                   UNION
                   SELECT m.student_id FROM submissions AS s
                   JOIN submission_roster AS m ON m.submission_id = s.submission_id
                   WHERE s.submission_id = %s""",
                submission_id,
                submission_id,
            )
        ]
