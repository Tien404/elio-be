-- MySQL 8.4 / UTC. Apply with python -m scripts.migrate.
-- Quiz settings chosen by the professor:
--   max_attempts   how many attempts a student gets (0 = unlimited)
--   grading_method which attempt counts: HIGHEST_SCORE, LATEST_ATTEMPT or AVERAGE
-- Question points: by default every question gets an equal share of the quiz total;
-- a question whose points the professor set by hand is flagged is_custom_points.

--   set_total      the total the professor typed; questions share it. The quiz total
--                  (activities.max_score) equals it, except when every question's
--                  points are set by hand: then it is their sum.

ALTER TABLE quizzes
    ADD COLUMN max_attempts INT NOT NULL DEFAULT 1,
    ADD COLUMN grading_method VARCHAR(15) NOT NULL DEFAULT 'HIGHEST_SCORE',
    ADD COLUMN set_total DECIMAL(6,2) NOT NULL DEFAULT 1;

ALTER TABLE quizzes
    ADD CONSTRAINT CK_quizzes_set_total CHECK (set_total > 0),
    ADD CONSTRAINT CK_quizzes_max_attempts CHECK (max_attempts >= 0),
    ADD CONSTRAINT CK_quizzes_grading_method CHECK (grading_method IN ('HIGHEST_SCORE', 'LATEST_ATTEMPT', 'AVERAGE'));

ALTER TABLE quiz_questions
    ADD COLUMN is_custom_points BOOLEAN NOT NULL DEFAULT 0;

-- Several attempts per student, numbered 1, 2, 3 ...
ALTER TABLE quiz_attempts
    ADD COLUMN attempt_no INT NOT NULL DEFAULT 1 AFTER student_id;

ALTER TABLE quiz_attempts
    ADD CONSTRAINT UQ_quiz_attempts_student_attempt UNIQUE (quiz_id, student_id, attempt_no),
    ADD CONSTRAINT CK_quiz_attempts_attempt_no CHECK (attempt_no > 0);

ALTER TABLE quiz_attempts DROP INDEX UQ_quiz_attempts_student;
