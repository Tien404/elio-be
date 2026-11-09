"""T-SQL for topics, file assets and materials. Never commits; caller owns the transaction."""

from typing import Any

from app.domain.entities import FileAsset, Material, MaterialKind, PublishStatus, Topic
from app.infrastructure.db.sql import Sql

_TOPIC_COLUMNS = "t.topic_id, t.offering_id, t.title, t.position, t.version"
_FILE_COLUMNS = """f.file_id, f.offering_id, f.uploaded_by, f.purpose, f.assignment_id,
    f.file_key, f.file_name, f.mime_type, f.size_bytes, f.sha256, f.state, f.expires_at"""
_MATERIAL_SELECT = """SELECT m.material_id, m.topic_id, m.kind, m.title, m.status, m.version, m.is_mandatory,
        t.offering_id, lm.url, fm.file_id, tm.body
    FROM dbo.materials AS m
    JOIN dbo.topics AS t ON t.topic_id = m.topic_id
    LEFT JOIN dbo.link_materials AS lm ON lm.material_id = m.material_id
    LEFT JOIN dbo.file_materials AS fm ON fm.material_id = m.material_id
    LEFT JOIN dbo.text_materials AS tm ON tm.material_id = m.material_id"""


class ContentRepository:
    def __init__(self, sql: Sql):
        self.sql = sql

    # ------------------------------------------------------------------ topics
    def next_topic_position(self, offering_id: int) -> int:
        """Next free position; locks the range so concurrent creates queue up."""
        current = self.sql.scalar(
            "SELECT MAX(position) FROM dbo.topics WITH (UPDLOCK, HOLDLOCK) WHERE offering_id = ?",
            offering_id,
        )
        return (current or 0) + 1

    def insert_topic(self, *, offering_id: int, title: str, position: int) -> Topic:
        row = self.sql.one(
            """INSERT dbo.topics (offering_id, title, position)
               OUTPUT INSERTED.topic_id, INSERTED.offering_id, INSERTED.title,
                      INSERTED.position, INSERTED.version
               VALUES (?, ?, ?)""",
            offering_id,
            title,
            position,
        )
        return topic_from_row(row)

    def get_topic(self, topic_id: int) -> Topic | None:
        row = self.sql.one(
            f"SELECT {_TOPIC_COLUMNS} FROM dbo.topics AS t WHERE t.topic_id = ?", topic_id
        )
        return topic_from_row(row) if row else None

    def list_topics(self, offering_id: int, *, offset: int, limit: int) -> tuple[list[Topic], int]:
        total = self.sql.scalar(
            "SELECT COUNT(*) FROM dbo.topics WHERE offering_id = ?", offering_id
        )
        rows = self.sql.all(
            f"""SELECT {_TOPIC_COLUMNS} FROM dbo.topics AS t WHERE t.offering_id = ?
                ORDER BY t.position OFFSET ? ROWS FETCH NEXT ? ROWS ONLY""",
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
        return self.sql.one(
            """DECLARE @now DATETIMEOFFSET(7) = SYSUTCDATETIME();
               INSERT dbo.file_assets (offering_id, uploaded_by, purpose, assignment_id,
                   file_key, file_name, mime_type, size_bytes, sha256, uploaded_at, expires_at)
               OUTPUT INSERTED.file_id, INSERTED.offering_id, INSERTED.uploaded_by,
                      INSERTED.purpose, INSERTED.assignment_id, INSERTED.file_key,
                      INSERTED.file_name, INSERTED.mime_type, INSERTED.size_bytes,
                      INSERTED.sha256, INSERTED.state, INSERTED.expires_at
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, @now, DATEADD(HOUR, 24, @now))""",
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

    def get_file(self, file_id: int, *, lock: bool = False) -> dict[str, Any] | None:
        hint = "WITH (UPDLOCK, ROWLOCK)" if lock else ""
        return self.sql.one(
            f"SELECT {_FILE_COLUMNS} FROM dbo.file_assets AS f {hint} WHERE f.file_id = ?",
            file_id,
        )

    def attach_file(self, file_id: int) -> None:
        self.sql.execute("UPDATE dbo.file_assets SET state = 'ATTACHED' WHERE file_id = ?", file_id)

    # --------------------------------------------------------------- materials
    def insert_material(self, *, data):
        material_id = self.sql.scalar(
            """INSERT dbo.materials (topic_id,kind,title,status,is_mandatory)
               OUTPUT INSERTED.material_id VALUES (?,?,?,?,?)""",
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
            self.sql.execute(f"DELETE dbo.{table} WHERE material_id=?", material_id)
        if data["kind"] == "FILE":
            self.sql.execute(
                "INSERT dbo.file_materials (material_id,file_id) VALUES (?,?)",
                material_id,
                data["fileIds"][0],
            )
        elif data["kind"] == "LINK":
            self.sql.execute(
                "INSERT dbo.link_materials (material_id,url) VALUES (?,?)",
                material_id,
                data["externalUrl"],
            )
        else:
            self.sql.execute(
                "INSERT dbo.text_materials (material_id,body) VALUES (?,?)",
                material_id,
                data["body"],
            )

    def get_material(self, material_id: int, *, lock: bool = False) -> dict[str, Any] | None:
        """Material + its class (offering_id) + link url or file id."""
        if lock:
            self.sql.execute(
                "SELECT 1 FROM dbo.materials WITH (UPDLOCK, ROWLOCK) WHERE material_id = ?",
                material_id,
            )
        return self.sql.one(f"{_MATERIAL_SELECT} WHERE m.material_id = ?", material_id)

    def material_for_file(self, file_id: int) -> dict[str, Any] | None:
        return self.sql.one(f"{_MATERIAL_SELECT} WHERE fm.file_id = ?", file_id)

    def list_materials(
        self, offering_id: int, *, published_only: bool, offset: int, limit: int
    ) -> tuple[list[dict[str, Any]], int]:
        """Materials of a class in topic order, then oldest first."""
        where = "t.offering_id = ?" + (" AND m.status = 'PUBLISHED'" if published_only else "")
        total = self.sql.scalar(
            f"""SELECT COUNT(*) FROM dbo.materials AS m
                JOIN dbo.topics AS t ON t.topic_id = m.topic_id WHERE {where}""",
            offering_id,
        )
        rows = self.sql.all(
            f"""{_MATERIAL_SELECT} WHERE {where}
                ORDER BY t.position, m.created_at, m.material_id
                OFFSET ? ROWS FETCH NEXT ? ROWS ONLY""",
            offering_id,
            offset,
            limit,
        )
        return rows, total

    def update_material(self, material_id, data):
        for table in ("file_materials", "link_materials", "text_materials"):
            self.sql.execute(f"DELETE dbo.{table} WHERE material_id=?", material_id)
        self.sql.execute(
            "UPDATE dbo.materials SET title=?,topic_id=?,kind=?,status=?,is_mandatory=?,version=version+1 WHERE material_id=?",
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
            "SELECT topic_id,position FROM dbo.topics WITH (UPDLOCK,HOLDLOCK) WHERE offering_id=? ORDER BY position",
            topic.offering_id,
        )
        ordered = [r["topic_id"] for r in rows if r["topic_id"] != topic_id]
        ordered.insert(position - 1, topic_id)
        old = {r["topic_id"]: r["position"] for r in rows}
        moved = [(number, id) for number, id in enumerate(ordered, 1) if old[id] != number]
        temporary = max(old.values()) + 1
        for offset, (_, id) in enumerate(moved):
            self.sql.execute(
                "UPDATE dbo.topics SET position=? WHERE topic_id=?", temporary + offset, id
            )
        for number, id in moved:
            self.sql.execute(
                "UPDATE dbo.topics SET position=?,version=version+1 WHERE topic_id=?", number, id
            )
        self.sql.execute(
            "UPDATE dbo.topics SET title=?,version=version+? WHERE topic_id=?",
            title,
            0 if topic_id in {id for _, id in moved} else 1,
            topic_id,
        )

    def completed(self, student_id, material_id):
        return bool(
            self.sql.scalar(
                "SELECT COUNT(*) FROM dbo.material_completions WHERE student_id=? AND material_id=?",
                student_id,
                material_id,
            )
        )

    def set_completion(self, student_id, material_id, complete):
        self.sql.execute(
            "DELETE dbo.material_completions WHERE student_id=? AND material_id=?",
            student_id,
            material_id,
        )
        if complete:
            self.sql.execute(
                "INSERT dbo.material_completions (student_id,material_id) VALUES (?,?)",
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
