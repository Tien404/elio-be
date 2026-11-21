-- MySQL 8.4 / UTC. Apply with python -m scripts.migrate.
-- Special grades (school codes): 11 = ABSENT (absent from the test/assignment),
-- 12 = BANNED (banned from the exam). Both always count as a score of 0.

ALTER TABLE grade_revisions
    ADD COLUMN special_mark VARCHAR(10) NULL AFTER score;

ALTER TABLE grade_revisions
    ADD CONSTRAINT CK_grade_revisions_special_mark CHECK (
        special_mark IS NULL OR (special_mark IN ('ABSENT', 'BANNED') AND score = 0));
