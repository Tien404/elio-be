"MySQL SQL for topics, file assets and materials. Never commits; caller owns the transaction."

from typing import Any

from app.domain.entities import FileAsset, Material, MaterialKind, PublishStatus, Topic
from app.infrastructure.db.sql import Sql

_TOPIC_COLUMNS = "t.topic_id, t.offering_id, t.title, t.position, t.version"
_FILE_COLUMNS = """f.file_id, f.offering_id, f.uploaded_by, f.purpose, f.assignment_id,
    f.file_key, f.file_name, f.mime_type, f.size_bytes, f.sha256, f.state, f.expires_at"""
_MATERIAL_SELECT = """SELECT m.material_id, m.topic_id, m.kind, m.title, m.status, m.version, m.is_mandatory,
        t.offering_id, lm.url, fm.file_id, tm.body
    FROM materials AS m
    JOIN topics AS t ON t.topic_id = m.topic_id
    LEFT JOIN link_materials AS lm ON lm.material_id = m.material_id
    LEFT JOIN file_materials AS fm ON fm.material_id = m.material_id
    LEFT JOIN text_materials AS tm ON tm.material_id = m.material_id"""


class ContentRepository:
    def __init__(self, sql: Sql):
        self.sql = sql

    # ------------------------------------------------------------------ topics
    def next_topic_position(self, offering_id: int) -> int:
        """Next free position; locks the range so concurrent creates queue up."""
        current = self.sql.scalar(
            "SELECT MAX(position) FROM topics  WHERE offering_id = %s FOR UPDATE",
            offering_id,
        )
        return (current or 0) + 1

    def insert_topic(self, *, offering_id: int, title: str, position: int) -> Topic:
        inserted_id = self.sql.insert(
            """INSERT INTO topics (offering_id, title, position)

               VALUES (%s, %s, %s)""",
            offering_id,
            title,
            position,
        )
        row = self.sql.one(
            """SELECT topic_id, offering_id, title,
                      position, version FROM topics WHERE topic_id = %s""",
            inserted_id,
        )
        return topic_from_row(row)

    def get_topic(self, topic_id: int) -> Topic | None:
        row = self.sql.one(
            f"SELECT {_TOPIC_COLUMNS} FROM topics AS t WHERE t.topic_id = %s", topic_id
        )
        return topic_from_row(row) if row else None

    def list_topics(self, offering_id: int, *, offset: int, limit: int) -> tuple[list[Topic], int]:
        total = self.sql.scalar("SELECT COUNT(*) FROM topics WHERE offering_id = %s", offering_id)
        rows = self.sql.all(
            f"""SELECT {_TOPIC_COLUMNS} FROM topics AS t WHERE t.offering_id = %s
                ORDER BY t.position LIMIT %s, %s""",
            offering_id,
            offset,
            limit,
        )
        return [topic_from_row(row) for row in rows], total

    # ------------------------------------------------------------- file assets
    def insert_file_asset(
        self,
        *,
        offering_id: int,
        uploaded_by: int,
        purpose: str,
        assignment_id: int | None,
        file_key: str,
        file_name: str,
        mime_type: str,
        size_bytes: int,
        sha256: str,
    ) -> dict[str, Any]:
        """New STAGING file; it expires 24h after upload unless attached."""
        inserted_id = self.sql.insert(
            """
               INSERT INTO file_assets (offering_id, uploaded_by, purpose, assignment_id,
                   file_key, file_name, mime_type, size_bytes, sha256, uploaded_at, expires_at)

               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, UTC_TIMESTAMP(6), DATE_ADD(UTC_TIMESTAMP(6), INTERVAL 24 HOUR))""",
            offering_id,
            uploaded_by,
            purpose,
            assignment_id,
            file_key,
            file_name,
            mime_type,
            size_bytes,
            sha256,
        )
        return self.sql.one(
            """SELECT file_id, offering_id, uploaded_by,
                      purpose, assignment_id, file_key,
                      file_name, mime_type, size_bytes,
                      sha256, state, expires_at FROM file_assets WHERE file_id = %s""",
            inserted_id,
        )

    def get_file(self, file_id: int, *, lock: bool = False) -> dict[str, Any] | None:
        hint = "FOR UPDATE" if lock else ""
        return self.sql.one(
            f"SELECT {_FILE_COLUMNS} FROM file_assets AS f WHERE f.file_id = %s {hint}",
            file_id,
        )

    def attach_file(self, file_id: int) -> None:
        self.sql.execute("UPDATE file_assets SET state = 'ATTACHED' WHERE file_id = %s", file_id)

    # --------------------------------------------------------------- materials
    def insert_material(self, *, data):
        material_id = self.sql.insert(
            """INSERT INTO materials (topic_id,kind,title,status,is_mandatory)
                VALUES (%s,%s,%s,%s,%s)""",
            data["topicId"],
            data["kind"],
            data["title"],
            data["status"],
            data["mandatory"],
        )
        self.set_material_body(material_id, data)
        return material_id

    def set_material_body(self, material_id, data):
        for table in ("file_materials", "link_materials", "text_materials"):
            self.sql.execute(f"DELETE FROM {table} WHERE material_id=%s", material_id)
        if data["kind"] == "FILE":
            self.sql.execute(
                "INSERT INTO file_materials (material_id,file_id) VALUES (%s,%s)",
                material_id,
                data["fileIds"][0],
            )
        elif data["kind"] == "LINK":
            self.sql.execute(
                "INSERT INTO link_materials (material_id,url) VALUES (%s,%s)",
                material_id,
                data["externalUrl"],
            )
        else:
            self.sql.execute(
                "INSERT INTO text_materials (material_id,body) VALUES (%s,%s)",
                material_id,
                data["body"],
            )

    def get_material(self, material_id: int, *, lock: bool = False) -> dict[str, Any] | None:
        """Material + its class (offering_id) + link url or file id."""
        if lock:
            self.sql.execute(
                "SELECT 1 FROM materials  WHERE material_id = %s FOR UPDATE",
                material_id,
            )
        return self.sql.one(f"{_MATERIAL_SELECT} WHERE m.material_id = %s", material_id)

    def material_for_file(self, file_id: int) -> dict[str, Any] | None:
        return self.sql.one(f"{_MATERIAL_SELECT} WHERE fm.file_id = %s", file_id)

    def list_materials(
        self, offering_id: int, *, published_only: bool, offset: int, limit: int
    ) -> tuple[list[dict[str, Any]], int]:
        """Materials of a class in topic order, then oldest first."""
        where = "t.offering_id = %s" + (" AND m.status = 'PUBLISHED'" if published_only else "")
        total = self.sql.scalar(
            f"""SELECT COUNT(*) FROM materials AS m
                JOIN topics AS t ON t.topic_id = m.topic_id WHERE {where}""",
            offering_id,
        )
        rows = self.sql.all(
            f"""{_MATERIAL_SELECT} WHERE {where}
                ORDER BY t.position, m.created_at, m.material_id
                LIMIT %s, %s""",
            offering_id,
            offset,
            limit,
        )
        return rows, total

    def update_material(self, material_id, data):
        for table in ("file_materials", "link_materials", "text_materials"):
            self.sql.execute(f"DELETE FROM {table} WHERE material_id=%s", material_id)
        self.sql.execute(
            "UPDATE materials SET title=%s,topic_id=%s,kind=%s,status=%s,is_mandatory=%s,version=version+1 WHERE material_id=%s",
            data["title"],
            data["topicId"],
            data["kind"],
            data["status"],
            data["mandatory"],
            material_id,
        )
        self.set_material_body(material_id, data)

    def reorder_topic(self, topic_id, title, position):
        topic = self.get_topic(topic_id)
        rows = self.sql.all(
            "SELECT topic_id,position FROM topics  WHERE offering_id=%s ORDER BY position FOR UPDATE",
            topic.offering_id,
        )
        ordered = [r["topic_id"] for r in rows if r["topic_id"] != topic_id]
        ordered.insert(position - 1, topic_id)
        old = {r["topic_id"]: r["position"] for r in rows}
        moved = [(number, id) for number, id in enumerate(ordered, 1) if old[id] != number]
        temporary = max(old.values()) + 1
        for offset, (_, id) in enumerate(moved):
            self.sql.execute(
                "UPDATE topics SET position=%s WHERE topic_id=%s", temporary + offset, id
            )
        for number, id in moved:
            self.sql.execute(
                "UPDATE topics SET position=%s,version=version+1 WHERE topic_id=%s", number, id
            )
        self.sql.execute(
            "UPDATE topics SET title=%s,version=version+%s WHERE topic_id=%s",
            title,
            0 if topic_id in {id for _, id in moved} else 1,
            topic_id,
        )

    def completed(self, student_id, material_id):
        return bool(
            self.sql.scalar(
                "SELECT COUNT(*) FROM material_completions WHERE student_id=%s AND material_id=%s",
                student_id,
                material_id,
            )
        )

    def set_completion(self, student_id, material_id, complete):
        self.sql.execute(
            "DELETE FROM material_completions WHERE student_id=%s AND material_id=%s",
            student_id,
            material_id,
        )
        if complete:
            self.sql.execute(
                "INSERT INTO material_completions (student_id,material_id) VALUES (%s,%s)",
                student_id,
                material_id,
            )


def topic_from_row(row: dict[str, Any]) -> Topic:
    return Topic(
        topic_id=row["topic_id"],
        offering_id=row["offering_id"],
        title=row["title"],
        position=row["position"],
        version=row["version"],
    )


def file_from_row(row: dict[str, Any]) -> FileAsset:
    return FileAsset(
        file_id=row["file_id"],
        file_name=row["file_name"],
        mime_type=row["mime_type"],
        size_bytes=row["size_bytes"],
        sha256=row["sha256"],
        storage_key=row["file_key"],
    )


def material_from_row(row: dict[str, Any]) -> Material:
    return Material(
        material_id=row["material_id"],
        topic_id=row["topic_id"],
        title=row["title"],
        kind=MaterialKind(row["kind"]),
        status=PublishStatus(row["status"]),
        url=row["url"],
        version=row["version"],
    )
