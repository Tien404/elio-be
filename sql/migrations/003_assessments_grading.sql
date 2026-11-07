/*
  003_assessments_grading  (logical model group 3 / EERD section 3 "Activities, submissions & grading")
  ---------------------------------------------------------------------------
  Tables       : activities, assignments, quizzes, assignment_attachments,
                 assignment_groups, group_members, submissions, submission_roster,
                 submission_versions, submission_files, grades, grade_revisions
  Also         : FK file_assets.assignment_id -> assignments (deferred from 002).
  Target DB    : elio_dev (or any isolated ELIO database).
  Prerequisite : 002_courses_content.
  Transaction  : single transaction, XACT_ABORT ON; skipped when already recorded.
  Rollback     : ALTER TABLE grades DROP CONSTRAINT FK_grades_draft_revision, FK_grades_published_revision;
                 ALTER TABLE file_assets DROP CONSTRAINT FK_file_assets_assignments;
                 drop the tables above in reverse order of creation;
                 DELETE dbo.schema_migrations WHERE migration_id = N'003_assessments_grading';
  Post-check   : SELECT name FROM sys.tables ORDER BY name;

  Notes
  - activities is the supertype of assignments/quizzes; (activity_id, activity_type) FK
    pins each subtype row to the right type. "Exactly one subtype" is a service rule.
  - Optional activities.topic_id must be a topic of the same offering: composite FK
    (topic_id, offering_id) -> topics (SQL Server skips the check when topic_id IS NULL).
  - grades <-> grade_revisions is circular. SQL Server has no deferred constraints, so the
    save-grade transaction is: insert grades with NULL pointers -> insert revision ->
    update pointers. Composite FKs are not checked while a pointer is NULL.
  - All FKs are NO ACTION (no cascades): academic history is never deleted implicitly.
*/
SET ANSI_NULLS ON;
SET QUOTED_IDENTIFIER ON;
SET XACT_ABORT ON;
SET NOCOUNT ON;

IF EXISTS (SELECT 1 FROM dbo.schema_migrations WHERE migration_id = N'003_assessments_grading')
BEGIN
    PRINT N'003_assessments_grading already applied; skipping.';
    RETURN;
END;

BEGIN TRANSACTION;

CREATE TABLE dbo.activities (
    activity_id   INT IDENTITY(1,1) NOT NULL,
    offering_id   INT               NOT NULL,
    topic_id      INT               NULL,
    activity_type VARCHAR(10)       NOT NULL,
    title         NVARCHAR(200)     NOT NULL,
    max_score     DECIMAL(6,2)      NOT NULL,
    weight_pct    DECIMAL(5,2)      NOT NULL CONSTRAINT DF_activities_weight_pct DEFAULT 0,
    is_mandatory  BIT               NOT NULL CONSTRAINT DF_activities_is_mandatory DEFAULT 0,
    status        VARCHAR(10)       NOT NULL CONSTRAINT DF_activities_status DEFAULT 'DRAFT',
    created_at    DATETIMEOFFSET(7) NOT NULL CONSTRAINT DF_activities_created_at DEFAULT SYSUTCDATETIME(),
    version       INT               NOT NULL CONSTRAINT DF_activities_version DEFAULT 1,
    CONSTRAINT PK_activities PRIMARY KEY (activity_id),
    CONSTRAINT UQ_activities_activity_type UNIQUE (activity_id, activity_type),
    CONSTRAINT CK_activities_activity_type CHECK (activity_type IN ('ASSIGNMENT', 'QUIZ')),
    CONSTRAINT CK_activities_title CHECK (LEN(title) > 0),
    CONSTRAINT CK_activities_max_score CHECK (max_score > 0),
    CONSTRAINT CK_activities_weight_pct CHECK (weight_pct >= 0 AND weight_pct <= 100),
    CONSTRAINT CK_activities_status CHECK (status IN ('DRAFT', 'PUBLISHED', 'ARCHIVED')),
    CONSTRAINT CK_activities_version CHECK (version >= 1),
    CONSTRAINT FK_activities_offerings FOREIGN KEY (offering_id) REFERENCES dbo.course_offerings (offering_id),
    CONSTRAINT FK_activities_topics FOREIGN KEY (topic_id, offering_id) REFERENCES dbo.topics (topic_id, offering_id)
);

CREATE INDEX IX_activities_offering ON dbo.activities (offering_id, activity_type, status);

CREATE TABLE dbo.assignments (
    activity_id   INT               NOT NULL,
    activity_type VARCHAR(10)       NOT NULL CONSTRAINT DF_assignments_activity_type DEFAULT 'ASSIGNMENT',
    instructions  NVARCHAR(MAX)     NOT NULL,
    open_at       DATETIMEOFFSET(7) NOT NULL,
    due_at        DATETIMEOFFSET(7) NOT NULL,
    cutoff_at     DATETIMEOFFSET(7) NOT NULL,
    is_group_work BIT               NOT NULL CONSTRAINT DF_assignments_is_group_work DEFAULT 0,
    CONSTRAINT PK_assignments PRIMARY KEY (activity_id),
    CONSTRAINT CK_assignments_activity_type CHECK (activity_type = 'ASSIGNMENT'),
    CONSTRAINT CK_assignments_schedule CHECK (open_at <= due_at AND due_at <= cutoff_at),
    CONSTRAINT FK_assignments_activities FOREIGN KEY (activity_id, activity_type) REFERENCES dbo.activities (activity_id, activity_type)
);

ALTER TABLE dbo.file_assets
    ADD CONSTRAINT FK_file_assets_assignments FOREIGN KEY (assignment_id) REFERENCES dbo.assignments (activity_id);

CREATE TABLE dbo.quizzes (
    activity_id   INT               NOT NULL,
    activity_type VARCHAR(10)       NOT NULL CONSTRAINT DF_quizzes_activity_type DEFAULT 'QUIZ',
    open_at       DATETIMEOFFSET(7) NOT NULL,
    close_at      DATETIMEOFFSET(7) NOT NULL,
    duration_min  INT               NOT NULL,
    published_at  DATETIMEOFFSET(7) NULL,
    CONSTRAINT PK_quizzes PRIMARY KEY (activity_id),
    CONSTRAINT CK_quizzes_activity_type CHECK (activity_type = 'QUIZ'),
    CONSTRAINT CK_quizzes_window CHECK (open_at < close_at),
    CONSTRAINT CK_quizzes_duration CHECK (duration_min > 0 AND DATEADD(MINUTE, duration_min, open_at) <= close_at),
    CONSTRAINT FK_quizzes_activities FOREIGN KEY (activity_id, activity_type) REFERENCES dbo.activities (activity_id, activity_type)
);

CREATE TABLE dbo.assignment_attachments (
    assignment_id INT      NOT NULL,
    attachment_no SMALLINT NOT NULL,
    file_id       INT      NOT NULL,
    file_purpose  AS CAST('ASSIGNMENT_ATTACHMENT' AS VARCHAR(25)) PERSISTED NOT NULL,
    CONSTRAINT PK_assignment_attachments PRIMARY KEY (assignment_id, attachment_no),
    CONSTRAINT UQ_assignment_attachments_file UNIQUE (assignment_id, file_id),
    CONSTRAINT CK_assignment_attachments_no CHECK (attachment_no BETWEEN 1 AND 5),
    CONSTRAINT FK_assignment_attachments_assignments FOREIGN KEY (assignment_id) REFERENCES dbo.assignments (activity_id),
    CONSTRAINT FK_assignment_attachments_file_assets FOREIGN KEY (file_id, file_purpose) REFERENCES dbo.file_assets (file_id, purpose)
);

CREATE TABLE dbo.assignment_groups (
    group_id      INT IDENTITY(1,1) NOT NULL,
    assignment_id INT           NOT NULL,
    name          NVARCHAR(120) NOT NULL,
    version       INT           NOT NULL CONSTRAINT DF_assignment_groups_version DEFAULT 1,
    CONSTRAINT PK_assignment_groups PRIMARY KEY (group_id),
    CONSTRAINT UQ_assignment_groups_group_assignment UNIQUE (group_id, assignment_id),
    CONSTRAINT UQ_assignment_groups_name UNIQUE (assignment_id, name),
    CONSTRAINT CK_assignment_groups_name CHECK (LEN(name) > 0),
    CONSTRAINT CK_assignment_groups_version CHECK (version >= 1),
    CONSTRAINT FK_assignment_groups_assignments FOREIGN KEY (assignment_id) REFERENCES dbo.assignments (activity_id)
);

CREATE TABLE dbo.group_members (
    group_id      INT NOT NULL,
    assignment_id INT NOT NULL,
    student_id    INT NOT NULL,
    CONSTRAINT PK_group_members PRIMARY KEY (group_id, student_id),
    -- a student is in at most one group per assignment
    CONSTRAINT UQ_group_members_assignment_student UNIQUE (assignment_id, student_id),
    CONSTRAINT FK_group_members_groups FOREIGN KEY (group_id, assignment_id) REFERENCES dbo.assignment_groups (group_id, assignment_id),
    CONSTRAINT FK_group_members_students FOREIGN KEY (student_id) REFERENCES dbo.students (user_id)
);

CREATE TABLE dbo.submissions (
    submission_id    INT IDENTITY(1,1) NOT NULL,
    assignment_id    INT               NOT NULL,
    owner_type       VARCHAR(10)       NOT NULL,
    student_id       INT               NULL,
    group_id         INT               NULL,
    roster_frozen_at DATETIMEOFFSET(7) NULL,
    status           VARCHAR(15)       NOT NULL CONSTRAINT DF_submissions_status DEFAULT 'NOT_SUBMITTED',
    created_at       DATETIMEOFFSET(7) NOT NULL CONSTRAINT DF_submissions_created_at DEFAULT SYSUTCDATETIME(),
    -- accepted stream version count; 0 until the first confirmation
    version          INT               NOT NULL CONSTRAINT DF_submissions_version DEFAULT 0,
    CONSTRAINT PK_submissions PRIMARY KEY (submission_id),
    CONSTRAINT CK_submissions_owner CHECK (
        (owner_type = 'INDIVIDUAL' AND student_id IS NOT NULL AND group_id IS NULL)
        OR (owner_type = 'GROUP' AND group_id IS NOT NULL AND student_id IS NULL)),
    CONSTRAINT CK_submissions_status CHECK (status IN ('NOT_SUBMITTED', 'SUBMITTED')),
    CONSTRAINT CK_submissions_version CHECK (version >= 0),
    CONSTRAINT CK_submissions_status_version CHECK ((status = 'NOT_SUBMITTED' AND version = 0) OR (status = 'SUBMITTED' AND version > 0)),
    CONSTRAINT CK_submissions_roster_frozen CHECK (roster_frozen_at IS NULL OR owner_type = 'GROUP'),
    CONSTRAINT FK_submissions_assignments FOREIGN KEY (assignment_id) REFERENCES dbo.assignments (activity_id),
    CONSTRAINT FK_submissions_students FOREIGN KEY (student_id) REFERENCES dbo.students (user_id),
    CONSTRAINT FK_submissions_groups FOREIGN KEY (group_id, assignment_id) REFERENCES dbo.assignment_groups (group_id, assignment_id)
);

CREATE UNIQUE INDEX UX_submissions_individual ON dbo.submissions (assignment_id, student_id) WHERE student_id IS NOT NULL;
CREATE UNIQUE INDEX UX_submissions_group ON dbo.submissions (group_id) WHERE group_id IS NOT NULL;

CREATE TABLE dbo.submission_roster (
    submission_id INT NOT NULL,
    student_id    INT NOT NULL,
    CONSTRAINT PK_submission_roster PRIMARY KEY (submission_id, student_id),
    CONSTRAINT FK_submission_roster_submissions FOREIGN KEY (submission_id) REFERENCES dbo.submissions (submission_id),
    CONSTRAINT FK_submission_roster_students FOREIGN KEY (student_id) REFERENCES dbo.students (user_id)
);

CREATE INDEX IX_submission_roster_student ON dbo.submission_roster (student_id);

CREATE TABLE dbo.submission_versions (
    submission_id INT               NOT NULL,
    version_no    INT               NOT NULL,
    submitted_by  INT               NOT NULL,
    submitted_at  DATETIMEOFFSET(7) NOT NULL,
    is_late       BIT               NOT NULL,
    receipt_code  VARCHAR(40)  COLLATE Latin1_General_100_BIN2 NOT NULL,
    request_key   VARCHAR(128) COLLATE Latin1_General_100_BIN2 NOT NULL,
    request_hash  CHAR(64)     COLLATE Latin1_General_100_BIN2 NOT NULL,
    CONSTRAINT PK_submission_versions PRIMARY KEY (submission_id, version_no),
    CONSTRAINT UQ_submission_versions_receipt UNIQUE (receipt_code),
    -- Idempotency-Key replay lookup: same actor + key returns the original receipt
    CONSTRAINT UQ_submission_versions_request UNIQUE (submitted_by, request_key),
    CONSTRAINT CK_submission_versions_version_no CHECK (version_no > 0),
    CONSTRAINT CK_submission_versions_request_key CHECK (LEN(request_key) >= 16 AND request_key NOT LIKE '%[^A-Za-z0-9._:-]%'),
    CONSTRAINT CK_submission_versions_request_hash CHECK (request_hash NOT LIKE '%[^0-9a-f]%'),
    CONSTRAINT FK_submission_versions_submissions FOREIGN KEY (submission_id) REFERENCES dbo.submissions (submission_id),
    CONSTRAINT FK_submission_versions_students FOREIGN KEY (submitted_by) REFERENCES dbo.students (user_id)
);

CREATE TABLE dbo.submission_files (
    submission_id INT      NOT NULL,
    version_no    INT      NOT NULL,
    file_no       SMALLINT NOT NULL,
    file_id       INT      NOT NULL,
    file_purpose  AS CAST('SUBMISSION' AS VARCHAR(25)) PERSISTED NOT NULL,
    CONSTRAINT PK_submission_files PRIMARY KEY (submission_id, version_no, file_no),
    CONSTRAINT UQ_submission_files_file UNIQUE (submission_id, version_no, file_id),
    CONSTRAINT CK_submission_files_file_no CHECK (file_no BETWEEN 1 AND 5),
    CONSTRAINT FK_submission_files_versions FOREIGN KEY (submission_id, version_no) REFERENCES dbo.submission_versions (submission_id, version_no),
    CONSTRAINT FK_submission_files_file_assets FOREIGN KEY (file_id, file_purpose) REFERENCES dbo.file_assets (file_id, purpose)
);

CREATE TABLE dbo.grades (
    grade_id              INT IDENTITY(1,1) NOT NULL,
    submission_id         INT               NOT NULL,
    draft_revision_no     INT               NULL,
    published_revision_no INT               NULL,
    published_at          DATETIMEOFFSET(7) NULL,
    version               INT               NOT NULL CONSTRAINT DF_grades_version DEFAULT 1,
    CONSTRAINT PK_grades PRIMARY KEY (grade_id),
    CONSTRAINT UQ_grades_submission UNIQUE (submission_id),
    CONSTRAINT UQ_grades_grade_submission UNIQUE (grade_id, submission_id),
    CONSTRAINT CK_grades_published CHECK ((published_revision_no IS NULL AND published_at IS NULL) OR (published_revision_no IS NOT NULL AND published_at IS NOT NULL)),
    CONSTRAINT CK_grades_version CHECK (version >= 1),
    CONSTRAINT FK_grades_submissions FOREIGN KEY (submission_id) REFERENCES dbo.submissions (submission_id)
);

CREATE TABLE dbo.grade_revisions (
    grade_id          INT               NOT NULL,
    revision_no       INT               NOT NULL,
    submission_id     INT               NOT NULL,
    source_version_no INT               NULL,
    score             DECIMAL(6,2)      NOT NULL,
    feedback          NVARCHAR(MAX)     NULL,
    is_missing_zero   BIT               NOT NULL CONSTRAINT DF_grade_revisions_is_missing_zero DEFAULT 0,
    zero_reason       NVARCHAR(1000)    NULL,
    reason            NVARCHAR(1000)    NULL,
    revised_by        INT               NOT NULL,
    revised_at        DATETIMEOFFSET(7) NOT NULL CONSTRAINT DF_grade_revisions_revised_at DEFAULT SYSUTCDATETIME(),
    CONSTRAINT PK_grade_revisions PRIMARY KEY (grade_id, revision_no),
    CONSTRAINT CK_grade_revisions_revision_no CHECK (revision_no > 0),
    -- upper bound (activity max_score) is validated by GradingService
    CONSTRAINT CK_grade_revisions_score CHECK (score >= 0),
    CONSTRAINT CK_grade_revisions_missing_zero CHECK (
        (is_missing_zero = 1 AND score = 0 AND source_version_no IS NULL AND zero_reason IS NOT NULL AND LEN(zero_reason) > 0)
        OR (is_missing_zero = 0 AND source_version_no IS NOT NULL AND zero_reason IS NULL)),
    CONSTRAINT CK_grade_revisions_reason CHECK (reason IS NULL OR LEN(reason) > 0),
    CONSTRAINT FK_grade_revisions_grades FOREIGN KEY (grade_id, submission_id) REFERENCES dbo.grades (grade_id, submission_id),
    CONSTRAINT FK_grade_revisions_source_version FOREIGN KEY (submission_id, source_version_no) REFERENCES dbo.submission_versions (submission_id, version_no),
    CONSTRAINT FK_grade_revisions_revised_by FOREIGN KEY (revised_by) REFERENCES dbo.instructors (user_id)
);

ALTER TABLE dbo.grades
    ADD CONSTRAINT FK_grades_draft_revision FOREIGN KEY (grade_id, draft_revision_no) REFERENCES dbo.grade_revisions (grade_id, revision_no),
        CONSTRAINT FK_grades_published_revision FOREIGN KEY (grade_id, published_revision_no) REFERENCES dbo.grade_revisions (grade_id, revision_no);

INSERT dbo.schema_migrations (migration_id) VALUES (N'003_assessments_grading');

COMMIT TRANSACTION;
PRINT N'003_assessments_grading applied.';
