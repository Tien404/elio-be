/*
  002_courses_content  (logical model group 2 / EERD section 2 "Courses & content")
  ---------------------------------------------------------------------------
  Tables       : courses, course_offerings, course_memberships, topics, file_assets,
                 materials, file_materials, text_materials, link_materials,
                 material_completions
  Target DB    : elio_dev (or any isolated ELIO database).
  Prerequisite : 001_identity.
  Transaction  : single transaction, XACT_ABORT ON; skipped when already recorded.
  Rollback     : drop the tables above in reverse order of creation;
                 DELETE dbo.schema_migrations WHERE migration_id = N'002_courses_content';
  Post-check   : SELECT name FROM sys.tables ORDER BY name;

  Notes
  - file_assets.assignment_id -> assignments is added in 003 (assignments do not exist yet).
  - course_memberships.member_role is a persisted computed column so the composite FK
    (user_id, member_role) -> users (user_id, role) guarantees STUDENT memberships point
    at student accounts and instructor memberships at instructor accounts.
  - file_materials.file_purpose (always 'MATERIAL') + FK to file_assets (file_id, purpose)
    guarantees only MATERIAL uploads can back a file material. Same-offering is checked
    by ContentService.
  - "Exactly one ACTIVE PRIMARY_INSTRUCTOR per offering": the filtered unique index
    allows at most one; CourseService keeps at least one inside its transactions.
*/
SET ANSI_NULLS ON;
SET QUOTED_IDENTIFIER ON;
SET XACT_ABORT ON;
SET NOCOUNT ON;

IF EXISTS (SELECT 1 FROM dbo.schema_migrations WHERE migration_id = N'002_courses_content')
BEGIN
    PRINT N'002_courses_content already applied; skipping.';
    RETURN;
END;

BEGIN TRANSACTION;

CREATE TABLE dbo.courses (
    course_id   INT IDENTITY(1,1) NOT NULL,
    course_code NVARCHAR(40)  NOT NULL,
    course_name NVARCHAR(200) NOT NULL,
    credits     DECIMAL(4,1)  NOT NULL,
    description NVARCHAR(MAX) NULL,
    CONSTRAINT PK_courses PRIMARY KEY (course_id),
    CONSTRAINT UQ_courses_course_code UNIQUE (course_code),
    CONSTRAINT CK_courses_course_code CHECK (LEN(course_code) > 0),
    CONSTRAINT CK_courses_course_name CHECK (LEN(course_name) > 0),
    CONSTRAINT CK_courses_credits CHECK (credits > 0)
);

CREATE TABLE dbo.course_offerings (
    offering_id       INT IDENTITY(1,1) NOT NULL,
    course_id         INT               NOT NULL,
    semester          NVARCHAR(40)      NOT NULL,
    section_code      NVARCHAR(40)      NOT NULL,
    title             NVARCHAR(200)     NOT NULL,
    state             VARCHAR(10)       NOT NULL CONSTRAINT DF_course_offerings_state DEFAULT 'DRAFT',
    join_code         CHAR(6) COLLATE Latin1_General_100_BIN2 NULL,
    join_code_enabled BIT               NOT NULL CONSTRAINT DF_course_offerings_join_code_enabled DEFAULT 0,
    created_by        INT               NOT NULL,
    created_at        DATETIMEOFFSET(7) NOT NULL CONSTRAINT DF_course_offerings_created_at DEFAULT SYSUTCDATETIME(),
    archived_at       DATETIMEOFFSET(7) NULL,
    version           INT               NOT NULL CONSTRAINT DF_course_offerings_version DEFAULT 1,
    CONSTRAINT PK_course_offerings PRIMARY KEY (offering_id),
    CONSTRAINT UQ_course_offerings_section UNIQUE (course_id, semester, section_code),
    CONSTRAINT CK_course_offerings_semester CHECK (LEN(semester) > 0),
    CONSTRAINT CK_course_offerings_section_code CHECK (LEN(section_code) > 0),
    CONSTRAINT CK_course_offerings_title CHECK (LEN(title) > 0),
    CONSTRAINT CK_course_offerings_state CHECK (state IN ('DRAFT', 'OPEN', 'ARCHIVED')),
    -- six upper-case alphanumeric characters (BIN2 makes A-Z a code-point range)
    CONSTRAINT CK_course_offerings_join_code CHECK (join_code IS NULL OR (LEN(join_code) = 6 AND join_code NOT LIKE '%[^A-Z0-9]%')),
    CONSTRAINT CK_course_offerings_join_enabled CHECK (join_code_enabled = 0 OR join_code IS NOT NULL),
    CONSTRAINT CK_course_offerings_archived CHECK ((state = 'ARCHIVED' AND archived_at IS NOT NULL) OR (state <> 'ARCHIVED' AND archived_at IS NULL)),
    CONSTRAINT CK_course_offerings_version CHECK (version >= 1),
    CONSTRAINT FK_course_offerings_courses FOREIGN KEY (course_id) REFERENCES dbo.courses (course_id),
    CONSTRAINT FK_course_offerings_created_by FOREIGN KEY (created_by) REFERENCES dbo.instructors (user_id)
);

CREATE UNIQUE INDEX UX_course_offerings_join_code ON dbo.course_offerings (join_code) WHERE join_code IS NOT NULL;

CREATE TABLE dbo.course_memberships (
    membership_id INT IDENTITY(1,1) NOT NULL,
    offering_id   INT               NOT NULL,
    user_id       INT               NOT NULL,
    course_role   VARCHAR(20)       NOT NULL,
    status        VARCHAR(10)       NOT NULL CONSTRAINT DF_course_memberships_status DEFAULT 'ACTIVE',
    joined_at     DATETIMEOFFSET(7) NOT NULL CONSTRAINT DF_course_memberships_joined_at DEFAULT SYSUTCDATETIME(),
    version       INT               NOT NULL CONSTRAINT DF_course_memberships_version DEFAULT 1,
    member_role AS CAST(CASE WHEN course_role = 'STUDENT' THEN 'STUDENT' ELSE 'INSTRUCTOR' END AS VARCHAR(10)) PERSISTED NOT NULL,
    CONSTRAINT PK_course_memberships PRIMARY KEY (membership_id),
    CONSTRAINT UQ_course_memberships_member UNIQUE (offering_id, user_id),
    CONSTRAINT CK_course_memberships_course_role CHECK (course_role IN ('STUDENT', 'PRIMARY_INSTRUCTOR', 'CO_INSTRUCTOR')),
    CONSTRAINT CK_course_memberships_status CHECK (status IN ('ACTIVE', 'REMOVED')),
    CONSTRAINT CK_course_memberships_version CHECK (version >= 1),
    CONSTRAINT FK_course_memberships_offerings FOREIGN KEY (offering_id) REFERENCES dbo.course_offerings (offering_id),
    CONSTRAINT FK_course_memberships_users FOREIGN KEY (user_id, member_role) REFERENCES dbo.users (user_id, role)
);

CREATE UNIQUE INDEX UX_course_memberships_one_lead
    ON dbo.course_memberships (offering_id)
    WHERE course_role = 'PRIMARY_INSTRUCTOR' AND status = 'ACTIVE';
CREATE INDEX IX_course_memberships_user ON dbo.course_memberships (user_id, status) INCLUDE (offering_id, course_role);

CREATE TABLE dbo.topics (
    topic_id    INT IDENTITY(1,1) NOT NULL,
    offering_id INT           NOT NULL,
    title       NVARCHAR(200) NOT NULL,
    position    INT           NOT NULL,
    version     INT           NOT NULL CONSTRAINT DF_topics_version DEFAULT 1,
    CONSTRAINT PK_topics PRIMARY KEY (topic_id),
    CONSTRAINT UQ_topics_position UNIQUE (offering_id, position),
    CONSTRAINT UQ_topics_topic_offering UNIQUE (topic_id, offering_id),
    CONSTRAINT CK_topics_title CHECK (LEN(title) > 0),
    CONSTRAINT CK_topics_position CHECK (position > 0),
    CONSTRAINT CK_topics_version CHECK (version >= 1),
    CONSTRAINT FK_topics_offerings FOREIGN KEY (offering_id) REFERENCES dbo.course_offerings (offering_id)
);

CREATE TABLE dbo.file_assets (
    file_id       INT IDENTITY(1,1) NOT NULL,
    offering_id   INT               NOT NULL,
    uploaded_by   INT               NOT NULL,
    purpose       VARCHAR(25)       NOT NULL,
    assignment_id INT               NULL,
    file_key      VARCHAR(255) COLLATE Latin1_General_100_BIN2 NOT NULL,
    file_name     NVARCHAR(255)     NOT NULL,
    mime_type     NVARCHAR(127)     NOT NULL,
    size_bytes    INT               NOT NULL,
    sha256        CHAR(64) COLLATE Latin1_General_100_BIN2 NOT NULL,
    state         VARCHAR(10)       NOT NULL CONSTRAINT DF_file_assets_state DEFAULT 'STAGING',
    uploaded_at   DATETIMEOFFSET(7) NOT NULL,
    expires_at    DATETIMEOFFSET(7) NOT NULL,
    CONSTRAINT PK_file_assets PRIMARY KEY (file_id),
    CONSTRAINT UQ_file_assets_file_key UNIQUE (file_key),
    CONSTRAINT UQ_file_assets_file_purpose UNIQUE (file_id, purpose),
    CONSTRAINT CK_file_assets_purpose CHECK (purpose IN ('MATERIAL', 'ASSIGNMENT_ATTACHMENT', 'SUBMISSION')),
    CONSTRAINT CK_file_assets_state CHECK (state IN ('STAGING', 'ATTACHED', 'EXPIRED')),
    CONSTRAINT CK_file_assets_file_name CHECK (LEN(file_name) > 0),
    CONSTRAINT CK_file_assets_size CHECK (size_bytes >= 1 AND size_bytes <= CASE WHEN purpose = 'MATERIAL' THEN 50000000 ELSE 20000000 END),
    CONSTRAINT CK_file_assets_sha256 CHECK (sha256 NOT LIKE '%[^0-9a-f]%'),
    CONSTRAINT CK_file_assets_assignment CHECK (
        (purpose = 'MATERIAL' AND assignment_id IS NULL)
        OR (purpose = 'SUBMISSION' AND assignment_id IS NOT NULL)
        OR purpose = 'ASSIGNMENT_ATTACHMENT'),
    CONSTRAINT CK_file_assets_expiry CHECK (expires_at = DATEADD(HOUR, 24, uploaded_at)),
    CONSTRAINT FK_file_assets_offerings FOREIGN KEY (offering_id) REFERENCES dbo.course_offerings (offering_id),
    CONSTRAINT FK_file_assets_uploaded_by FOREIGN KEY (uploaded_by) REFERENCES dbo.users (user_id)
);

-- Staging cleanup worker: unattached uploads past expiry.
CREATE INDEX IX_file_assets_staging_expiry ON dbo.file_assets (expires_at) WHERE state = 'STAGING';
CREATE INDEX IX_file_assets_offering ON dbo.file_assets (offering_id, purpose);

CREATE TABLE dbo.materials (
    material_id  INT IDENTITY(1,1) NOT NULL,
    topic_id     INT               NOT NULL,
    kind         VARCHAR(4)        NOT NULL,
    title        NVARCHAR(200)     NOT NULL,
    status       VARCHAR(10)       NOT NULL CONSTRAINT DF_materials_status DEFAULT 'DRAFT',
    is_mandatory BIT               NOT NULL CONSTRAINT DF_materials_is_mandatory DEFAULT 0,
    created_at   DATETIMEOFFSET(7) NOT NULL CONSTRAINT DF_materials_created_at DEFAULT SYSUTCDATETIME(),
    version      INT               NOT NULL CONSTRAINT DF_materials_version DEFAULT 1,
    CONSTRAINT PK_materials PRIMARY KEY (material_id),
    CONSTRAINT UQ_materials_material_kind UNIQUE (material_id, kind),
    CONSTRAINT CK_materials_kind CHECK (kind IN ('FILE', 'TEXT', 'LINK')),
    CONSTRAINT CK_materials_status CHECK (status IN ('DRAFT', 'PUBLISHED', 'ARCHIVED')),
    CONSTRAINT CK_materials_title CHECK (LEN(title) > 0),
    CONSTRAINT CK_materials_version CHECK (version >= 1),
    CONSTRAINT FK_materials_topics FOREIGN KEY (topic_id) REFERENCES dbo.topics (topic_id)
);

CREATE INDEX IX_materials_topic ON dbo.materials (topic_id, status);

CREATE TABLE dbo.file_materials (
    material_id  INT        NOT NULL,
    kind         VARCHAR(4) NOT NULL CONSTRAINT DF_file_materials_kind DEFAULT 'FILE',
    file_id      INT        NOT NULL,
    file_purpose AS CAST('MATERIAL' AS VARCHAR(25)) PERSISTED NOT NULL,
    CONSTRAINT PK_file_materials PRIMARY KEY (material_id),
    CONSTRAINT UQ_file_materials_file UNIQUE (file_id),
    CONSTRAINT CK_file_materials_kind CHECK (kind = 'FILE'),
    CONSTRAINT FK_file_materials_materials FOREIGN KEY (material_id, kind) REFERENCES dbo.materials (material_id, kind),
    CONSTRAINT FK_file_materials_file_assets FOREIGN KEY (file_id, file_purpose) REFERENCES dbo.file_assets (file_id, purpose)
);

CREATE TABLE dbo.text_materials (
    material_id INT           NOT NULL,
    kind        VARCHAR(4)    NOT NULL CONSTRAINT DF_text_materials_kind DEFAULT 'TEXT',
    body        NVARCHAR(MAX) NOT NULL,
    CONSTRAINT PK_text_materials PRIMARY KEY (material_id),
    CONSTRAINT CK_text_materials_kind CHECK (kind = 'TEXT'),
    CONSTRAINT CK_text_materials_body CHECK (LEN(TRIM(body)) > 0),
    CONSTRAINT FK_text_materials_materials FOREIGN KEY (material_id, kind) REFERENCES dbo.materials (material_id, kind)
);

CREATE TABLE dbo.link_materials (
    material_id INT            NOT NULL,
    kind        VARCHAR(4)     NOT NULL CONSTRAINT DF_link_materials_kind DEFAULT 'LINK',
    url         NVARCHAR(2048) NOT NULL,
    CONSTRAINT PK_link_materials PRIMARY KEY (material_id),
    CONSTRAINT CK_link_materials_kind CHECK (kind = 'LINK'),
    CONSTRAINT CK_link_materials_url CHECK (url LIKE N'http://_%' OR url LIKE N'https://_%'),
    CONSTRAINT FK_link_materials_materials FOREIGN KEY (material_id, kind) REFERENCES dbo.materials (material_id, kind)
);

CREATE TABLE dbo.material_completions (
    student_id   INT               NOT NULL,
    material_id  INT               NOT NULL,
    completed_at DATETIMEOFFSET(7) NOT NULL CONSTRAINT DF_material_completions_completed_at DEFAULT SYSUTCDATETIME(),
    CONSTRAINT PK_material_completions PRIMARY KEY (student_id, material_id),
    CONSTRAINT FK_material_completions_students FOREIGN KEY (student_id) REFERENCES dbo.students (user_id),
    CONSTRAINT FK_material_completions_materials FOREIGN KEY (material_id) REFERENCES dbo.materials (material_id)
);

CREATE INDEX IX_material_completions_material ON dbo.material_completions (material_id);

INSERT dbo.schema_migrations (migration_id) VALUES (N'002_courses_content');

COMMIT TRANSACTION;
PRINT N'002_courses_content applied.';
