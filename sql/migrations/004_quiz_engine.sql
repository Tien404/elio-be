/*
  004_quiz_engine  (logical model group 4 / EERD section 4 "Quiz engine")
  ---------------------------------------------------------------------------
  Tables       : question_banks, questions, question_options, quiz_questions,
                 quiz_snapshot_questions, quiz_snapshot_options, quiz_attempts,
                 attempt_answers
  Target DB    : elio_dev (or any isolated ELIO database).
  Prerequisite : 003_assessments_grading.
  Transaction  : single transaction, XACT_ABORT ON; skipped when already recorded.
  Rollback     : drop the tables above in reverse order of creation;
                 DELETE dbo.schema_migrations WHERE migration_id = N'004_quiz_engine';
  Post-check   : SELECT name FROM sys.tables ORDER BY name;

  Notes
  - questions / question_options / quiz_questions are the editable bank + draft selection.
  - quiz_snapshot_* are the immutable copies made when a quiz is published; attempts and
    scoring only ever reference the snapshot (selected_key must be a copied option key).
  - Option keys: TRUE_FALSE -> 'true' / 'false'; SINGLE_CHOICE -> stringified option_no.
  - "Exactly one correct option and at least two options" is validated by QuizService;
    the filtered unique index only guarantees at most one correct option.
*/
SET ANSI_NULLS ON;
SET QUOTED_IDENTIFIER ON;
SET XACT_ABORT ON;
SET NOCOUNT ON;

IF EXISTS (SELECT 1 FROM dbo.schema_migrations WHERE migration_id = N'004_quiz_engine')
BEGIN
    PRINT N'004_quiz_engine already applied; skipping.';
    RETURN;
END;

BEGIN TRANSACTION;

CREATE TABLE dbo.question_banks (
    bank_id     INT IDENTITY(1,1) NOT NULL,
    offering_id INT           NOT NULL,
    title       NVARCHAR(200) NOT NULL,
    CONSTRAINT PK_question_banks PRIMARY KEY (bank_id),
    CONSTRAINT CK_question_banks_title CHECK (LEN(title) > 0),
    CONSTRAINT FK_question_banks_offerings FOREIGN KEY (offering_id) REFERENCES dbo.course_offerings (offering_id)
);

CREATE INDEX IX_question_banks_offering ON dbo.question_banks (offering_id);

CREATE TABLE dbo.questions (
    question_id       INT IDENTITY(1,1) NOT NULL,
    bank_id           INT               NOT NULL,
    question_type     VARCHAR(15)       NOT NULL,
    question_text     NVARCHAR(MAX)     NOT NULL,
    points            DECIMAL(5,2)      NOT NULL,
    tf_correct_answer BIT               NULL,
    explanation       NVARCHAR(MAX)     NULL,
    created_at        DATETIMEOFFSET(7) NOT NULL CONSTRAINT DF_questions_created_at DEFAULT SYSUTCDATETIME(),
    version           INT               NOT NULL CONSTRAINT DF_questions_version DEFAULT 1,
    CONSTRAINT PK_questions PRIMARY KEY (question_id),
    CONSTRAINT UQ_questions_question_type UNIQUE (question_id, question_type),
    CONSTRAINT CK_questions_question_type CHECK (question_type IN ('SINGLE_CHOICE', 'TRUE_FALSE')),
    CONSTRAINT CK_questions_question_text CHECK (LEN(question_text) > 0),
    CONSTRAINT CK_questions_points CHECK (points > 0),
    CONSTRAINT CK_questions_tf_answer CHECK (
        (question_type = 'TRUE_FALSE' AND tf_correct_answer IS NOT NULL)
        OR (question_type = 'SINGLE_CHOICE' AND tf_correct_answer IS NULL)),
    CONSTRAINT CK_questions_version CHECK (version >= 1),
    CONSTRAINT FK_questions_banks FOREIGN KEY (bank_id) REFERENCES dbo.question_banks (bank_id)
);

CREATE INDEX IX_questions_bank ON dbo.questions (bank_id);

CREATE TABLE dbo.question_options (
    question_id   INT           NOT NULL,
    question_type VARCHAR(15)   NOT NULL CONSTRAINT DF_question_options_question_type DEFAULT 'SINGLE_CHOICE',
    option_no     SMALLINT      NOT NULL,
    option_text   NVARCHAR(MAX) NOT NULL,
    is_correct    BIT           NOT NULL CONSTRAINT DF_question_options_is_correct DEFAULT 0,
    CONSTRAINT PK_question_options PRIMARY KEY (question_id, option_no),
    CONSTRAINT CK_question_options_question_type CHECK (question_type = 'SINGLE_CHOICE'),
    CONSTRAINT CK_question_options_option_no CHECK (option_no > 0),
    CONSTRAINT CK_question_options_option_text CHECK (LEN(option_text) > 0),
    CONSTRAINT FK_question_options_questions FOREIGN KEY (question_id, question_type) REFERENCES dbo.questions (question_id, question_type)
);

CREATE UNIQUE INDEX UX_question_options_one_correct ON dbo.question_options (question_id) WHERE is_correct = 1;

CREATE TABLE dbo.quiz_questions (
    quiz_id     INT          NOT NULL,
    question_id INT          NOT NULL,
    position    INT          NOT NULL,
    points      DECIMAL(5,2) NOT NULL,
    CONSTRAINT PK_quiz_questions PRIMARY KEY (quiz_id, question_id),
    CONSTRAINT UQ_quiz_questions_position UNIQUE (quiz_id, position),
    CONSTRAINT CK_quiz_questions_position CHECK (position > 0),
    CONSTRAINT CK_quiz_questions_points CHECK (points > 0),
    CONSTRAINT FK_quiz_questions_quizzes FOREIGN KEY (quiz_id) REFERENCES dbo.quizzes (activity_id),
    CONSTRAINT FK_quiz_questions_questions FOREIGN KEY (question_id) REFERENCES dbo.questions (question_id)
);

CREATE INDEX IX_quiz_questions_question ON dbo.quiz_questions (question_id);

CREATE TABLE dbo.quiz_snapshot_questions (
    quiz_question_id   INT IDENTITY(1,1) NOT NULL,
    quiz_id            INT           NOT NULL,
    source_question_id INT           NOT NULL,
    position           INT           NOT NULL,
    question_type      VARCHAR(15)   NOT NULL,
    prompt             NVARCHAR(MAX) NOT NULL,
    correct_key        VARCHAR(50) COLLATE Latin1_General_100_BIN2 NOT NULL,
    explanation        NVARCHAR(MAX) NULL,
    points             DECIMAL(5,2)  NOT NULL,
    CONSTRAINT PK_quiz_snapshot_questions PRIMARY KEY (quiz_question_id),
    CONSTRAINT UQ_quiz_snapshot_questions_quiz UNIQUE (quiz_id, quiz_question_id),
    CONSTRAINT UQ_quiz_snapshot_questions_position UNIQUE (quiz_id, position),
    CONSTRAINT CK_quiz_snapshot_questions_position CHECK (position > 0),
    CONSTRAINT CK_quiz_snapshot_questions_type CHECK (question_type IN ('SINGLE_CHOICE', 'TRUE_FALSE')),
    CONSTRAINT CK_quiz_snapshot_questions_prompt CHECK (LEN(prompt) > 0),
    CONSTRAINT CK_quiz_snapshot_questions_correct_key CHECK (LEN(correct_key) > 0),
    CONSTRAINT CK_quiz_snapshot_questions_points CHECK (points > 0),
    CONSTRAINT FK_quiz_snapshot_questions_quizzes FOREIGN KEY (quiz_id) REFERENCES dbo.quizzes (activity_id),
    -- provenance only; bank questions referenced here must not be hard-deleted
    CONSTRAINT FK_quiz_snapshot_questions_source FOREIGN KEY (source_question_id) REFERENCES dbo.questions (question_id)
);

CREATE TABLE dbo.quiz_snapshot_options (
    quiz_question_id INT           NOT NULL,
    option_key       VARCHAR(50) COLLATE Latin1_General_100_BIN2 NOT NULL,
    option_text      NVARCHAR(MAX) NOT NULL,
    CONSTRAINT PK_quiz_snapshot_options PRIMARY KEY (quiz_question_id, option_key),
    CONSTRAINT CK_quiz_snapshot_options_key CHECK (LEN(option_key) > 0),
    CONSTRAINT FK_quiz_snapshot_options_questions FOREIGN KEY (quiz_question_id) REFERENCES dbo.quiz_snapshot_questions (quiz_question_id)
);

CREATE TABLE dbo.quiz_attempts (
    attempt_id       INT IDENTITY(1,1) NOT NULL,
    quiz_id          INT               NOT NULL,
    student_id       INT               NOT NULL,
    started_at       DATETIMEOFFSET(7) NOT NULL,
    ends_at          DATETIMEOFFSET(7) NOT NULL,
    submitted_at     DATETIMEOFFSET(7) NULL,
    finalized_by     VARCHAR(10)       NULL,
    score            DECIMAL(6,2)      NULL,
    released_at      DATETIMEOFFSET(7) NULL,
    processing_error NVARCHAR(1000)    NULL,
    version          INT               NOT NULL CONSTRAINT DF_quiz_attempts_version DEFAULT 1,
    CONSTRAINT PK_quiz_attempts PRIMARY KEY (attempt_id),
    CONSTRAINT UQ_quiz_attempts_student UNIQUE (quiz_id, student_id),
    CONSTRAINT UQ_quiz_attempts_attempt_quiz UNIQUE (attempt_id, quiz_id),
    CONSTRAINT CK_quiz_attempts_ends CHECK (ends_at > started_at),
    -- STUDENT = sealed by the student; SYSTEM = finalized by the worker after ends_at
    CONSTRAINT CK_quiz_attempts_finalized_by CHECK (finalized_by IS NULL OR finalized_by IN ('STUDENT', 'SYSTEM')),
    CONSTRAINT CK_quiz_attempts_score CHECK (score IS NULL OR score >= 0),
    CONSTRAINT CK_quiz_attempts_finalized CHECK ((finalized_by IS NULL AND score IS NULL) OR (finalized_by IS NOT NULL AND score IS NOT NULL)),
    CONSTRAINT CK_quiz_attempts_released CHECK (released_at IS NULL OR finalized_by IS NOT NULL),
    CONSTRAINT CK_quiz_attempts_version CHECK (version >= 1),
    CONSTRAINT FK_quiz_attempts_quizzes FOREIGN KEY (quiz_id) REFERENCES dbo.quizzes (activity_id),
    CONSTRAINT FK_quiz_attempts_students FOREIGN KEY (student_id) REFERENCES dbo.students (user_id)
);

-- Worker catch-up: attempts past their end that are not finalized yet.
CREATE INDEX IX_quiz_attempts_unfinalized ON dbo.quiz_attempts (ends_at) WHERE finalized_by IS NULL;
CREATE INDEX IX_quiz_attempts_student ON dbo.quiz_attempts (student_id);

CREATE TABLE dbo.attempt_answers (
    attempt_id       INT               NOT NULL,
    quiz_id          INT               NOT NULL,
    quiz_question_id INT               NOT NULL,
    selected_key     VARCHAR(50) COLLATE Latin1_General_100_BIN2 NOT NULL,
    saved_at         DATETIMEOFFSET(7) NOT NULL,
    is_correct       BIT               NULL,
    CONSTRAINT PK_attempt_answers PRIMARY KEY (attempt_id, quiz_question_id),
    CONSTRAINT FK_attempt_answers_attempts FOREIGN KEY (attempt_id, quiz_id) REFERENCES dbo.quiz_attempts (attempt_id, quiz_id),
    CONSTRAINT FK_attempt_answers_snapshot_questions FOREIGN KEY (quiz_id, quiz_question_id) REFERENCES dbo.quiz_snapshot_questions (quiz_id, quiz_question_id),
    CONSTRAINT FK_attempt_answers_snapshot_options FOREIGN KEY (quiz_question_id, selected_key) REFERENCES dbo.quiz_snapshot_options (quiz_question_id, option_key)
);

INSERT dbo.schema_migrations (migration_id) VALUES (N'004_quiz_engine');

COMMIT TRANSACTION;
PRINT N'004_quiz_engine applied.';
