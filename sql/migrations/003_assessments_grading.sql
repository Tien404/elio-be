-- MySQL 8.4 / UTC. Apply with python -m scripts.migrate.

CREATE TABLE activities (
    activity_id   INT AUTO_INCREMENT NOT NULL,
    offering_id   INT               NOT NULL,
    topic_id      INT               NULL,
    activity_type VARCHAR(10)       NOT NULL,
    title         VARCHAR(200)     NOT NULL,
    max_score     DECIMAL(6,2)      NOT NULL,
    weight_pct    DECIMAL(5,2)      NOT NULL DEFAULT 0,
    is_mandatory  BOOLEAN               NOT NULL DEFAULT 0,
    status        VARCHAR(10)       NOT NULL DEFAULT 'DRAFT',
    created_at    DATETIME(6) NOT NULL DEFAULT (UTC_TIMESTAMP(6)),
    version       INT               NOT NULL DEFAULT 1,
    CONSTRAINT PK_activities PRIMARY KEY (activity_id),
    CONSTRAINT UQ_activities_activity_type UNIQUE (activity_id, activity_type),
    CONSTRAINT CK_activities_activity_type CHECK (activity_type IN ('ASSIGNMENT', 'QUIZ')),
    CONSTRAINT CK_activities_title CHECK (CHAR_LENGTH(title) > 0),
    CONSTRAINT CK_activities_max_score CHECK (max_score > 0),
    CONSTRAINT CK_activities_weight_pct CHECK (weight_pct >= 0 AND weight_pct <= 100),
    CONSTRAINT CK_activities_status CHECK (status IN ('DRAFT', 'PUBLISHED', 'ARCHIVED')),
    CONSTRAINT CK_activities_version CHECK (version >= 1),
    CONSTRAINT FK_activities_offerings FOREIGN KEY (offering_id) REFERENCES course_offerings (offering_id),
    CONSTRAINT FK_activities_topics FOREIGN KEY (topic_id, offering_id) REFERENCES topics (topic_id, offering_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_as_ci;

CREATE INDEX IX_activities_offering ON activities (offering_id, activity_type, status);

CREATE TABLE assignments (
    activity_id   INT               NOT NULL,
    activity_type VARCHAR(10)       NOT NULL DEFAULT 'ASSIGNMENT',
    instructions  LONGTEXT     NOT NULL,
    open_at       DATETIME(6) NOT NULL,
    due_at        DATETIME(6) NOT NULL,
    cutoff_at     DATETIME(6) NOT NULL,
    is_group_work BOOLEAN               NOT NULL DEFAULT 0,
    CONSTRAINT PK_assignments PRIMARY KEY (activity_id),
    CONSTRAINT CK_assignments_activity_type CHECK (activity_type = 'ASSIGNMENT'),
    CONSTRAINT CK_assignments_schedule CHECK (open_at <= due_at AND due_at <= cutoff_at),
    CONSTRAINT FK_assignments_activities FOREIGN KEY (activity_id, activity_type) REFERENCES activities (activity_id, activity_type)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_as_ci;

ALTER TABLE file_assets
    ADD CONSTRAINT FK_file_assets_assignments FOREIGN KEY (assignment_id) REFERENCES assignments (activity_id);

CREATE TABLE quizzes (
    activity_id   INT               NOT NULL,
    activity_type VARCHAR(10)       NOT NULL DEFAULT 'QUIZ',
    open_at       DATETIME(6) NOT NULL,
    close_at      DATETIME(6) NOT NULL,
    duration_min  INT               NOT NULL,
    published_at  DATETIME(6) NULL,
    CONSTRAINT PK_quizzes PRIMARY KEY (activity_id),
    CONSTRAINT CK_quizzes_activity_type CHECK (activity_type = 'QUIZ'),
    CONSTRAINT CK_quizzes_window CHECK (open_at < close_at),
    CONSTRAINT CK_quizzes_duration CHECK (duration_min > 0 AND DATE_ADD(open_at, INTERVAL duration_min MINUTE) <= close_at),
    CONSTRAINT FK_quizzes_activities FOREIGN KEY (activity_id, activity_type) REFERENCES activities (activity_id, activity_type)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_as_ci;

CREATE TABLE assignment_attachments (
    assignment_id INT      NOT NULL,
    attachment_no SMALLINT NOT NULL,
    file_id       INT      NOT NULL,
    file_purpose VARCHAR(25) NOT NULL DEFAULT 'ASSIGNMENT_ATTACHMENT' CHECK (file_purpose = 'ASSIGNMENT_ATTACHMENT'),
    CONSTRAINT PK_assignment_attachments PRIMARY KEY (assignment_id, attachment_no),
    CONSTRAINT UQ_assignment_attachments_file UNIQUE (assignment_id, file_id),
    CONSTRAINT CK_assignment_attachments_no CHECK (attachment_no BETWEEN 1 AND 5),
    CONSTRAINT FK_assignment_attachments_assignments FOREIGN KEY (assignment_id) REFERENCES assignments (activity_id),
    CONSTRAINT FK_assignment_attachments_file_assets FOREIGN KEY (file_id, file_purpose) REFERENCES file_assets (file_id, purpose)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_as_ci;

CREATE TABLE assignment_groups (
    group_id      INT AUTO_INCREMENT NOT NULL,
    assignment_id INT           NOT NULL,
    name          VARCHAR(120) NOT NULL,
    version       INT           NOT NULL DEFAULT 1,
    CONSTRAINT PK_assignment_groups PRIMARY KEY (group_id),
    CONSTRAINT UQ_assignment_groups_group_assignment UNIQUE (group_id, assignment_id),
    CONSTRAINT UQ_assignment_groups_name UNIQUE (assignment_id, name),
    CONSTRAINT CK_assignment_groups_name CHECK (CHAR_LENGTH(name) > 0),
    CONSTRAINT CK_assignment_groups_version CHECK (version >= 1),
    CONSTRAINT FK_assignment_groups_assignments FOREIGN KEY (assignment_id) REFERENCES assignments (activity_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_as_ci;

CREATE TABLE group_members (
    group_id      INT NOT NULL,
    assignment_id INT NOT NULL,
    student_id    INT NOT NULL,
    CONSTRAINT PK_group_members PRIMARY KEY (group_id, student_id),

    CONSTRAINT UQ_group_members_assignment_student UNIQUE (assignment_id, student_id),
    CONSTRAINT FK_group_members_groups FOREIGN KEY (group_id, assignment_id) REFERENCES assignment_groups (group_id, assignment_id),
    CONSTRAINT FK_group_members_students FOREIGN KEY (student_id) REFERENCES students (user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_as_ci;

CREATE TABLE submissions (
    submission_id    INT AUTO_INCREMENT NOT NULL,
    assignment_id    INT               NOT NULL,
    owner_type       VARCHAR(10)       NOT NULL,
    student_id       INT               NULL,
    group_id         INT               NULL,
    roster_frozen_at DATETIME(6) NULL,
    status           VARCHAR(15)       NOT NULL DEFAULT 'NOT_SUBMITTED',
    created_at       DATETIME(6) NOT NULL DEFAULT (UTC_TIMESTAMP(6)),

    version          INT               NOT NULL DEFAULT 0,
    CONSTRAINT PK_submissions PRIMARY KEY (submission_id),
    CONSTRAINT CK_submissions_owner CHECK (
        (owner_type = 'INDIVIDUAL' AND student_id IS NOT NULL AND group_id IS NULL)
        OR (owner_type = 'GROUP' AND group_id IS NOT NULL AND student_id IS NULL)),
    CONSTRAINT CK_submissions_status CHECK (status IN ('NOT_SUBMITTED', 'SUBMITTED')),
    CONSTRAINT CK_submissions_version CHECK (version >= 0),
    CONSTRAINT CK_submissions_status_version CHECK ((status = 'NOT_SUBMITTED' AND version = 0) OR (status = 'SUBMITTED' AND version > 0)),
    CONSTRAINT CK_submissions_roster_frozen CHECK (roster_frozen_at IS NULL OR owner_type = 'GROUP'),
    CONSTRAINT FK_submissions_assignments FOREIGN KEY (assignment_id) REFERENCES assignments (activity_id),
    CONSTRAINT FK_submissions_students FOREIGN KEY (student_id) REFERENCES students (user_id),
    CONSTRAINT FK_submissions_groups FOREIGN KEY (group_id, assignment_id) REFERENCES assignment_groups (group_id, assignment_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_as_ci;

CREATE UNIQUE INDEX UX_submissions_individual ON submissions (assignment_id, student_id);
CREATE UNIQUE INDEX UX_submissions_group ON submissions (group_id);

CREATE TABLE submission_roster (
    submission_id INT NOT NULL,
    student_id    INT NOT NULL,
    CONSTRAINT PK_submission_roster PRIMARY KEY (submission_id, student_id),
    CONSTRAINT FK_submission_roster_submissions FOREIGN KEY (submission_id) REFERENCES submissions (submission_id),
    CONSTRAINT FK_submission_roster_students FOREIGN KEY (student_id) REFERENCES students (user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_as_ci;

CREATE INDEX IX_submission_roster_student ON submission_roster (student_id);

CREATE TABLE submission_versions (
    submission_id INT               NOT NULL,
    version_no    INT               NOT NULL,
    submitted_by  INT               NOT NULL,
    submitted_at  DATETIME(6) NOT NULL,
    is_late       BOOLEAN               NOT NULL,
    receipt_code  VARCHAR(40)  COLLATE utf8mb4_bin NOT NULL,
    request_key   VARCHAR(128) COLLATE utf8mb4_bin NOT NULL,
    request_hash  CHAR(64)     COLLATE utf8mb4_bin NOT NULL,
    CONSTRAINT PK_submission_versions PRIMARY KEY (submission_id, version_no),
    CONSTRAINT UQ_submission_versions_receipt UNIQUE (receipt_code),

    CONSTRAINT UQ_submission_versions_request UNIQUE (submitted_by, request_key),
    CONSTRAINT CK_submission_versions_version_no CHECK (version_no > 0),
    CONSTRAINT CK_submission_versions_request_key CHECK (CHAR_LENGTH(request_key) >= 16 AND REGEXP_LIKE(request_key, '^[A-Za-z0-9._:-]+$', 'c')),
    CONSTRAINT CK_submission_versions_request_hash CHECK (REGEXP_LIKE(request_hash, '^[0-9a-f]{64}$', 'c')),
    CONSTRAINT FK_submission_versions_submissions FOREIGN KEY (submission_id) REFERENCES submissions (submission_id),
    CONSTRAINT FK_submission_versions_students FOREIGN KEY (submitted_by) REFERENCES students (user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_as_ci;

CREATE TABLE submission_files (
    submission_id INT      NOT NULL,
    version_no    INT      NOT NULL,
    file_no       SMALLINT NOT NULL,
    file_id       INT      NOT NULL,
    file_purpose VARCHAR(25) NOT NULL DEFAULT 'SUBMISSION' CHECK (file_purpose = 'SUBMISSION'),
    CONSTRAINT PK_submission_files PRIMARY KEY (submission_id, version_no, file_no),
    CONSTRAINT UQ_submission_files_file UNIQUE (submission_id, version_no, file_id),
    CONSTRAINT CK_submission_files_file_no CHECK (file_no BETWEEN 1 AND 5),
    CONSTRAINT FK_submission_files_versions FOREIGN KEY (submission_id, version_no) REFERENCES submission_versions (submission_id, version_no),
    CONSTRAINT FK_submission_files_file_assets FOREIGN KEY (file_id, file_purpose) REFERENCES file_assets (file_id, purpose)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_as_ci;

CREATE TABLE grades (
    grade_id              INT AUTO_INCREMENT NOT NULL,
    submission_id         INT               NOT NULL,
    draft_revision_no     INT               NULL,
    published_revision_no INT               NULL,
    published_at          DATETIME(6) NULL,
    version               INT               NOT NULL DEFAULT 1,
    CONSTRAINT PK_grades PRIMARY KEY (grade_id),
    CONSTRAINT UQ_grades_submission UNIQUE (submission_id),
    CONSTRAINT UQ_grades_grade_submission UNIQUE (grade_id, submission_id),
    CONSTRAINT CK_grades_published CHECK ((published_revision_no IS NULL AND published_at IS NULL) OR (published_revision_no IS NOT NULL AND published_at IS NOT NULL)),
    CONSTRAINT CK_grades_version CHECK (version >= 1),
    CONSTRAINT FK_grades_submissions FOREIGN KEY (submission_id) REFERENCES submissions (submission_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_as_ci;

CREATE TABLE grade_revisions (
    grade_id          INT               NOT NULL,
    revision_no       INT               NOT NULL,
    submission_id     INT               NOT NULL,
    source_version_no INT               NULL,
    score             DECIMAL(6,2)      NOT NULL,
    feedback          LONGTEXT     NULL,
    is_missing_zero   BOOLEAN               NOT NULL DEFAULT 0,
    zero_reason       VARCHAR(1000)    NULL,
    reason            VARCHAR(1000)    NULL,
    revised_by        INT               NOT NULL,
    revised_at        DATETIME(6) NOT NULL DEFAULT (UTC_TIMESTAMP(6)),
    CONSTRAINT PK_grade_revisions PRIMARY KEY (grade_id, revision_no),
    CONSTRAINT CK_grade_revisions_revision_no CHECK (revision_no > 0),

    CONSTRAINT CK_grade_revisions_score CHECK (score >= 0),
    CONSTRAINT CK_grade_revisions_missing_zero CHECK (
        (is_missing_zero = 1 AND score = 0 AND source_version_no IS NULL AND zero_reason IS NOT NULL AND CHAR_LENGTH(zero_reason) > 0)
        OR (is_missing_zero = 0 AND source_version_no IS NOT NULL AND zero_reason IS NULL)),
    CONSTRAINT CK_grade_revisions_reason CHECK (reason IS NULL OR CHAR_LENGTH(reason) > 0),
    CONSTRAINT FK_grade_revisions_grades FOREIGN KEY (grade_id, submission_id) REFERENCES grades (grade_id, submission_id),
    CONSTRAINT FK_grade_revisions_source_version FOREIGN KEY (submission_id, source_version_no) REFERENCES submission_versions (submission_id, version_no),
    CONSTRAINT FK_grade_revisions_revised_by FOREIGN KEY (revised_by) REFERENCES instructors (user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_as_ci;

ALTER TABLE grades
    ADD CONSTRAINT FK_grades_draft_revision FOREIGN KEY (grade_id, draft_revision_no) REFERENCES grade_revisions (grade_id, revision_no),
        ADD CONSTRAINT FK_grades_published_revision FOREIGN KEY (grade_id, published_revision_no) REFERENCES grade_revisions (grade_id, revision_no);
