-- Keep quiz-local editable copies linked to their reusable bank source.
ALTER TABLE questions
    ADD COLUMN source_question_id INT NULL,
    ADD COLUMN source_version INT NULL;
ALTER TABLE questions ADD CONSTRAINT CK_questions_source_version CHECK (source_version IS NULL OR source_version >= 1);
