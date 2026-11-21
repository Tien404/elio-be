-- Additive upgrade from main 000-010. Preserve attempts, special marks and groups.
ALTER TABLE assignments ADD COLUMN group_formation VARCHAR(12) NOT NULL DEFAULT 'SELF';
ALTER TABLE assignments ADD CONSTRAINT CK_group_formation CHECK (group_formation IN ('SELF','INSTRUCTOR'));
ALTER TABLE quizzes ADD COLUMN release_policy VARCHAR(12) NOT NULL DEFAULT 'IMMEDIATE';
ALTER TABLE quizzes ADD CONSTRAINT CK_quiz_release_policy CHECK (release_policy IN ('AFTER_CLOSE','IMMEDIATE'));
ALTER TABLE quiz_snapshot_questions ADD COLUMN source_version INT NULL;
-- Existing groups whose missing-work decision already exists need a historical roster.
INSERT IGNORE INTO submission_roster (submission_id,student_id)
SELECT s.submission_id,m.student_id FROM submissions s JOIN group_members m ON m.group_id=s.group_id;
UPDATE submissions SET roster_frozen_at=COALESCE(roster_frozen_at,UTC_TIMESTAMP(6)) WHERE group_id IS NOT NULL;
