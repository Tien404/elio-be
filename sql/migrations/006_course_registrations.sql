/*
  006_course_registrations  (team MVP flow; not in logical-model.json)
  ---------------------------------------------------------------------------
  Changes      : CHECK on courses.course_code format; new table course_registrations.
  Target DB    : elio_dev (or any isolated ELIO database).
  Prerequisite : 005_communication_audit.
  Transaction  : single transaction, XACT_ABORT ON; skipped when already recorded.
  Rollback     : DROP TABLE dbo.course_registrations;
                 ALTER TABLE dbo.courses DROP CONSTRAINT CK_courses_course_code_format;
                 DELETE dbo.schema_migrations WHERE migration_id = N'006_course_registrations';

  Notes
  - Course code convention: faculty prefix (2-4 capital letters) + year level (1-9)
    + degree level (0 undergraduate, 1 masters, 2 PhD) + 2-digit course number,
    e.g. CS1001. The API generates the number; BIN2 makes [A-Z] mean capitals only.
  - course_registrations: a student asks to take a catalog course; an admin approves or
    rejects it. At most one PENDING/APPROVED request per student and course; after a
    rejection the student may ask again.
*/
SET ANSI_NULLS ON;
SET QUOTED_IDENTIFIER ON;
SET XACT_ABORT ON;
SET NOCOUNT ON;

IF EXISTS (SELECT 1 FROM dbo.schema_migrations WHERE migration_id = N'006_course_registrations')
BEGIN
    PRINT N'006_course_registrations already applied; skipping.';
    RETURN;
END;

BEGIN TRANSACTION;

ALTER TABLE dbo.courses WITH CHECK ADD CONSTRAINT CK_courses_course_code_format CHECK (
       course_code COLLATE Latin1_General_100_BIN2 LIKE N'[A-Z][A-Z][1-9][0-2][0-9][0-9]'
    OR course_code COLLATE Latin1_General_100_BIN2 LIKE N'[A-Z][A-Z][A-Z][1-9][0-2][0-9][0-9]'
    OR course_code COLLATE Latin1_General_100_BIN2 LIKE N'[A-Z][A-Z][A-Z][A-Z][1-9][0-2][0-9][0-9]'
);

CREATE TABLE dbo.course_registrations (
    registration_id INT IDENTITY(1,1) NOT NULL,
    course_id       INT               NOT NULL,
    student_id      INT               NOT NULL,
    status          VARCHAR(10)       NOT NULL CONSTRAINT DF_course_registrations_status DEFAULT 'PENDING',
    requested_at    DATETIMEOFFSET(7) NOT NULL CONSTRAINT DF_course_registrations_requested_at DEFAULT SYSUTCDATETIME(),
    decided_by      INT               NULL,
    decided_at      DATETIMEOFFSET(7) NULL,
    version         INT               NOT NULL CONSTRAINT DF_course_registrations_version DEFAULT 1,
    CONSTRAINT PK_course_registrations PRIMARY KEY (registration_id),
    CONSTRAINT CK_course_registrations_status CHECK (status IN ('PENDING', 'APPROVED', 'REJECTED')),
    CONSTRAINT CK_course_registrations_decision CHECK (
           (status = 'PENDING' AND decided_by IS NULL AND decided_at IS NULL)
        OR (status <> 'PENDING' AND decided_by IS NOT NULL AND decided_at IS NOT NULL)),
    CONSTRAINT CK_course_registrations_version CHECK (version >= 1),
    CONSTRAINT FK_course_registrations_courses FOREIGN KEY (course_id) REFERENCES dbo.courses (course_id),
    CONSTRAINT FK_course_registrations_students FOREIGN KEY (student_id) REFERENCES dbo.students (user_id),
    CONSTRAINT FK_course_registrations_decided_by FOREIGN KEY (decided_by) REFERENCES dbo.admins (user_id)
);

CREATE UNIQUE INDEX UX_course_registrations_open
    ON dbo.course_registrations (course_id, student_id)
    WHERE status IN ('PENDING', 'APPROVED');
CREATE INDEX IX_course_registrations_status ON dbo.course_registrations (status, course_id);
CREATE INDEX IX_course_registrations_student ON dbo.course_registrations (student_id, status);

INSERT dbo.schema_migrations (migration_id) VALUES (N'006_course_registrations');

COMMIT TRANSACTION;
PRINT N'006_course_registrations applied.';
