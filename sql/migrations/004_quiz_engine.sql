-- MySQL 8.4 / UTC. Apply with python -m scripts.migrate.

CREATE TABLE question_banks (
    bank_id     INT AUTO_INCREMENT NOT NULL,
    offering_id INT           NOT NULL,
    title       VARCHAR(200) NOT NULL,
    CONSTRAINT PK_question_banks PRIMARY KEY (bank_id),
    CONSTRAINT CK_question_banks_title CHECK (CHAR_LENGTH(title) > 0),
    CONSTRAINT FK_question_banks_offerings FOREIGN KEY (offering_id) REFERENCES course_offerings (offering_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_as_ci;

CREATE INDEX IX_question_banks_offering ON question_banks (offering_id);

CREATE TABLE questions (
    question_id       INT AUTO_INCREMENT NOT NULL,
    bank_id           INT               NOT NULL,
    question_type     VARCHAR(15)       NOT NULL,
    question_text     LONGTEXT     NOT NULL,
    points            DECIMAL(5,2)      NOT NULL,
    tf_correct_answer BOOLEAN               NULL,
    explanation       LONGTEXT     NULL,
    created_at        DATETIME(6) NOT NULL DEFAULT (UTC_TIMESTAMP(6)),
    version           INT               NOT NULL DEFAULT 1,
    CONSTRAINT PK_questions PRIMARY KEY (question_id),
    CONSTRAINT UQ_questions_question_type UNIQUE (question_id, question_type),
    CONSTRAINT CK_questions_question_type CHECK (question_type IN ('SINGLE_CHOICE', 'TRUE_FALSE')),
    CONSTRAINT CK_questions_question_text CHECK (CHAR_LENGTH(question_text) > 0),
    CONSTRAINT CK_questions_points CHECK (points > 0),
    CONSTRAINT CK_questions_tf_answer CHECK (
        (question_type = 'TRUE_FALSE' AND tf_correct_answer IS NOT NULL)
        OR (question_type = 'SINGLE_CHOICE' AND tf_correct_answer IS NULL)),
    CONSTRAINT CK_questions_version CHECK (version >= 1),
    CONSTRAINT FK_questions_banks FOREIGN KEY (bank_id) REFERENCES question_banks (bank_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_as_ci;

CREATE INDEX IX_questions_bank ON questions (bank_id);

CREATE TABLE question_options (
    question_id   INT           NOT NULL,
    question_type VARCHAR(15)   NOT NULL DEFAULT 'SINGLE_CHOICE',
    option_no     SMALLINT      NOT NULL,
    option_text   LONGTEXT NOT NULL,
    is_correct    BOOLEAN           NOT NULL DEFAULT 0,
    CONSTRAINT PK_question_options PRIMARY KEY (question_id, option_no),
    CONSTRAINT CK_question_options_question_type CHECK (question_type = 'SINGLE_CHOICE'),
    CONSTRAINT CK_question_options_option_no CHECK (option_no > 0),
    CONSTRAINT CK_question_options_option_text CHECK (CHAR_LENGTH(option_text) > 0),
    CONSTRAINT FK_question_options_questions FOREIGN KEY (question_id, question_type) REFERENCES questions (question_id, question_type)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_as_ci;

ALTER TABLE question_options ADD correct_question_id INT GENERATED ALWAYS AS (CASE WHEN is_correct = 1 THEN question_id END) STORED;
CREATE UNIQUE INDEX UX_question_options_one_correct ON question_options (correct_question_id);

CREATE TABLE quiz_questions (
    quiz_id     INT          NOT NULL,
    question_id INT          NOT NULL,
    position    INT          NOT NULL,
    points      DECIMAL(5,2) NOT NULL,
    CONSTRAINT PK_quiz_questions PRIMARY KEY (quiz_id, question_id),
    CONSTRAINT UQ_quiz_questions_position UNIQUE (quiz_id, position),
    CONSTRAINT CK_quiz_questions_position CHECK (position > 0),
    CONSTRAINT CK_quiz_questions_points CHECK (points > 0),
    CONSTRAINT FK_quiz_questions_quizzes FOREIGN KEY (quiz_id) REFERENCES quizzes (activity_id),
    CONSTRAINT FK_quiz_questions_questions FOREIGN KEY (question_id) REFERENCES questions (question_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_as_ci;

CREATE INDEX IX_quiz_questions_question ON quiz_questions (question_id);

CREATE TABLE quiz_snapshot_questions (
    quiz_question_id   INT AUTO_INCREMENT NOT NULL,
    quiz_id            INT           NOT NULL,
    source_question_id INT           NOT NULL,
    position           INT           NOT NULL,
    question_type      VARCHAR(15)   NOT NULL,
    prompt             LONGTEXT NOT NULL,
    correct_key        VARCHAR(50) COLLATE utf8mb4_bin NOT NULL,
    explanation        LONGTEXT NULL,
    points             DECIMAL(5,2)  NOT NULL,
    CONSTRAINT PK_quiz_snapshot_questions PRIMARY KEY (quiz_question_id),
    CONSTRAINT UQ_quiz_snapshot_questions_quiz UNIQUE (quiz_id, quiz_question_id),
    CONSTRAINT UQ_quiz_snapshot_questions_position UNIQUE (quiz_id, position),
    CONSTRAINT CK_quiz_snapshot_questions_position CHECK (position > 0),
    CONSTRAINT CK_quiz_snapshot_questions_type CHECK (question_type IN ('SINGLE_CHOICE', 'TRUE_FALSE')),
    CONSTRAINT CK_quiz_snapshot_questions_prompt CHECK (CHAR_LENGTH(prompt) > 0),
    CONSTRAINT CK_quiz_snapshot_questions_correct_key CHECK (CHAR_LENGTH(correct_key) > 0),
    CONSTRAINT CK_quiz_snapshot_questions_points CHECK (points > 0),
    CONSTRAINT FK_quiz_snapshot_questions_quizzes FOREIGN KEY (quiz_id) REFERENCES quizzes (activity_id),

    CONSTRAINT FK_quiz_snapshot_questions_source FOREIGN KEY (source_question_id) REFERENCES questions (question_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_as_ci;

CREATE TABLE quiz_snapshot_options (
    quiz_question_id INT           NOT NULL,
    option_key       VARCHAR(50) COLLATE utf8mb4_bin NOT NULL,
    option_text      LONGTEXT NOT NULL,
    CONSTRAINT PK_quiz_snapshot_options PRIMARY KEY (quiz_question_id, option_key),
    CONSTRAINT CK_quiz_snapshot_options_key CHECK (CHAR_LENGTH(option_key) > 0),
    CONSTRAINT FK_quiz_snapshot_options_questions FOREIGN KEY (quiz_question_id) REFERENCES quiz_snapshot_questions (quiz_question_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_as_ci;

CREATE TABLE quiz_attempts (
    attempt_id       INT AUTO_INCREMENT NOT NULL,
    quiz_id          INT               NOT NULL,
    student_id       INT               NOT NULL,
    started_at       DATETIME(6) NOT NULL,
    ends_at          DATETIME(6) NOT NULL,
    submitted_at     DATETIME(6) NULL,
    finalized_by     VARCHAR(10)       NULL,
    score            DECIMAL(6,2)      NULL,
    released_at      DATETIME(6) NULL,
    processing_error VARCHAR(1000)    NULL,
    version          INT               NOT NULL DEFAULT 1,
    CONSTRAINT PK_quiz_attempts PRIMARY KEY (attempt_id),
    CONSTRAINT UQ_quiz_attempts_student UNIQUE (quiz_id, student_id),
    CONSTRAINT UQ_quiz_attempts_attempt_quiz UNIQUE (attempt_id, quiz_id),
    CONSTRAINT CK_quiz_attempts_ends CHECK (ends_at > started_at),

    CONSTRAINT CK_quiz_attempts_finalized_by CHECK (finalized_by IS NULL OR finalized_by IN ('STUDENT', 'SYSTEM')),
    CONSTRAINT CK_quiz_attempts_score CHECK (score IS NULL OR score >= 0),
    CONSTRAINT CK_quiz_attempts_finalized CHECK ((finalized_by IS NULL AND score IS NULL) OR (finalized_by IS NOT NULL AND score IS NOT NULL)),
    CONSTRAINT CK_quiz_attempts_released CHECK (released_at IS NULL OR finalized_by IS NOT NULL),
    CONSTRAINT CK_quiz_attempts_version CHECK (version >= 1),
    CONSTRAINT FK_quiz_attempts_quizzes FOREIGN KEY (quiz_id) REFERENCES quizzes (activity_id),
    CONSTRAINT FK_quiz_attempts_students FOREIGN KEY (student_id) REFERENCES students (user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_as_ci;


CREATE INDEX IX_quiz_attempts_unfinalized ON quiz_attempts (ends_at);
CREATE INDEX IX_quiz_attempts_student ON quiz_attempts (student_id);

CREATE TABLE attempt_answers (
    attempt_id       INT               NOT NULL,
    quiz_id          INT               NOT NULL,
    quiz_question_id INT               NOT NULL,
    selected_key     VARCHAR(50) COLLATE utf8mb4_bin NOT NULL,
    saved_at         DATETIME(6) NOT NULL,
    is_correct       BOOLEAN               NULL,
    CONSTRAINT PK_attempt_answers PRIMARY KEY (attempt_id, quiz_question_id),
    CONSTRAINT FK_attempt_answers_attempts FOREIGN KEY (attempt_id, quiz_id) REFERENCES quiz_attempts (attempt_id, quiz_id),
    CONSTRAINT FK_attempt_answers_snapshot_questions FOREIGN KEY (quiz_id, quiz_question_id) REFERENCES quiz_snapshot_questions (quiz_id, quiz_question_id),
    CONSTRAINT FK_attempt_answers_snapshot_options FOREIGN KEY (quiz_question_id, selected_key) REFERENCES quiz_snapshot_options (quiz_question_id, option_key)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_as_ci;
