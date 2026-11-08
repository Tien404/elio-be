/*
  smoke_test — exercises the schema end to end inside ONE transaction and rolls back.
  Leaves no data behind. Prints "ok:" for each check and a final PASS/FAIL line.
  Run:  sqlcmd -S localhost -E -C -I -b -d elio_dev -i sql/tests/smoke_test.sql
*/
SET ANSI_NULLS ON;
SET QUOTED_IDENTIFIER ON;
SET XACT_ABORT OFF;   -- constraint errors must stay statement-level so TRY/CATCH can assert them
SET NOCOUNT ON;

DECLARE @fail INT = 0, @now DATETIMEOFFSET(7) = SYSUTCDATETIME();
DECLARE @admin INT, @inst INT, @stu INT, @stu2 INT, @course INT, @off INT, @topic INT,
        @act INT, @quizAct INT, @asset INT, @sub INT, @grade INT, @q INT, @qq INT, @att INT;

BEGIN TRANSACTION;

------------------------------------------------------------------ happy path
INSERT dbo.users (email, full_name, password_hash, role, must_change_pwd)
VALUES (N'admin@elio.test', N'Admin', N'x', 'ADMIN', 0);
SET @admin = SCOPE_IDENTITY();
INSERT dbo.admins (user_id) VALUES (@admin);

INSERT dbo.users (email, full_name, password_hash, role, created_by) VALUES (N'teacher@elio.test', N'Teacher', N'x', 'INSTRUCTOR', @admin);
SET @inst = SCOPE_IDENTITY();
INSERT dbo.instructors (user_id, can_create_course) VALUES (@inst, 1);

INSERT dbo.users (email, full_name, password_hash, role, created_by) VALUES (N'student@elio.test', N'Student', N'x', 'STUDENT', @admin);
SET @stu = SCOPE_IDENTITY();
INSERT dbo.students (user_id, student_code) VALUES (@stu, N'S001');
INSERT dbo.users (email, full_name, password_hash, role, created_by) VALUES (N'student2@elio.test', N'Student Two', N'x', 'STUDENT', @admin);
SET @stu2 = SCOPE_IDENTITY();
INSERT dbo.students (user_id, student_code) VALUES (@stu2, N'S002');

INSERT dbo.user_sessions (user_id, token_hash, expires_at)
VALUES (@stu, REPLICATE('ab', 32), DATEADD(HOUR, 8, @now));

INSERT dbo.courses (course_code, course_name, credits) VALUES (N'CS1001', N'Intro to CS', 3);
SET @course = SCOPE_IDENTITY();
INSERT dbo.course_offerings (course_id, semester, section_code, title, state, join_code, join_code_enabled, created_by)
VALUES (@course, N'2026A', N'01', N'CS101 - 01', 'OPEN', 'ABC123', 1, @inst);
SET @off = SCOPE_IDENTITY();
INSERT dbo.course_memberships (offering_id, user_id, course_role) VALUES (@off, @inst, 'PRIMARY_INSTRUCTOR');
INSERT dbo.course_memberships (offering_id, user_id, course_role) VALUES (@off, @stu, 'STUDENT');
INSERT dbo.course_memberships (offering_id, user_id, course_role) VALUES (@off, @stu2, 'STUDENT');

INSERT dbo.topics (offering_id, title, position) VALUES (@off, N'Week 1', 1);
SET @topic = SCOPE_IDENTITY();

INSERT dbo.activities (offering_id, topic_id, activity_type, title, max_score, weight_pct, status)
VALUES (@off, @topic, 'ASSIGNMENT', N'Lab 1', 10, 30, 'PUBLISHED');
SET @act = SCOPE_IDENTITY();
INSERT dbo.assignments (activity_id, instructions, open_at, due_at, cutoff_at)
VALUES (@act, N'Do it', DATEADD(DAY, -7, @now), DATEADD(DAY, -2, @now), DATEADD(DAY, -1, @now));

INSERT dbo.file_assets (offering_id, uploaded_by, purpose, assignment_id, file_key, file_name, mime_type, size_bytes, sha256, state, uploaded_at, expires_at)
VALUES (@off, @stu, 'SUBMISSION', @act, 'k/sub-1', N'lab1.pdf', N'application/pdf', 1000, REPLICATE('0', 64), 'ATTACHED', @now, DATEADD(HOUR, 24, @now));
SET @asset = SCOPE_IDENTITY();

INSERT dbo.submissions (assignment_id, owner_type, student_id, status, version) VALUES (@act, 'INDIVIDUAL', @stu, 'SUBMITTED', 1);
SET @sub = SCOPE_IDENTITY();
INSERT dbo.submission_versions (submission_id, version_no, submitted_by, submitted_at, is_late, receipt_code, request_key, request_hash)
VALUES (@sub, 1, @stu, DATEADD(DAY, -3, @now), 0, 'RCPT-0001', 'key-0123456789abcdef', REPLICATE('f', 64));
INSERT dbo.submission_files (submission_id, version_no, file_no, file_id) VALUES (@sub, 1, 1, @asset);

-- grade save flow: grade with NULL pointers -> revision -> pointers
INSERT dbo.grades (submission_id) VALUES (@sub);
SET @grade = SCOPE_IDENTITY();
INSERT dbo.grade_revisions (grade_id, revision_no, submission_id, source_version_no, score, feedback, revised_by)
VALUES (@grade, 1, @sub, 1, 8.5, N'Good', @inst);
UPDATE dbo.grades SET draft_revision_no = 1, published_revision_no = 1, published_at = @now, version = version + 1 WHERE grade_id = @grade;
PRINT N'ok: happy path (identity, offering, submission, grade) inserted';

-- quiz flow
INSERT dbo.activities (offering_id, activity_type, title, max_score) VALUES (@off, 'QUIZ', N'Quiz 1', 2);
SET @quizAct = SCOPE_IDENTITY();
INSERT dbo.quizzes (activity_id, open_at, close_at, duration_min, published_at)
VALUES (@quizAct, DATEADD(HOUR, -1, @now), DATEADD(HOUR, 1, @now), 30, @now);
INSERT dbo.question_banks (offering_id, title) VALUES (@off, N'Bank');
INSERT dbo.questions (bank_id, question_type, question_text, points, tf_correct_answer)
VALUES (SCOPE_IDENTITY(), 'TRUE_FALSE', N'1+1=2?', 2, 1);
SET @q = SCOPE_IDENTITY();
INSERT dbo.quiz_questions (quiz_id, question_id, position, points) VALUES (@quizAct, @q, 1, 2);
INSERT dbo.quiz_snapshot_questions (quiz_id, source_question_id, position, question_type, prompt, correct_key, points)
VALUES (@quizAct, @q, 1, 'TRUE_FALSE', N'1+1=2?', 'true', 2);
SET @qq = SCOPE_IDENTITY();
INSERT dbo.quiz_snapshot_options (quiz_question_id, option_key, option_text) VALUES (@qq, 'true', N'True'), (@qq, 'false', N'False');
INSERT dbo.quiz_attempts (quiz_id, student_id, started_at, ends_at) VALUES (@quizAct, @stu, @now, DATEADD(MINUTE, 30, @now));
SET @att = SCOPE_IDENTITY();
INSERT dbo.attempt_answers (attempt_id, quiz_id, quiz_question_id, selected_key, saved_at) VALUES (@att, @quizAct, @qq, 'true', @now);
PRINT N'ok: quiz snapshot + attempt + answer inserted';

INSERT dbo.notifications (recipient_id, actor_id, offering_id, event_type, message, target_type, target_id, event_key)
VALUES (@stu, @inst, @off, 'GRADE_PUBLISHED', N'Your grade is available', 'ASSIGNMENT', @act, 'grade-published:1');
INSERT dbo.audit_entries (actor_id, action_type, target_type, target_id, details)
VALUES (@admin, 'ACCOUNT_CREATED', 'USER', @stu, N'{"role":"STUDENT"}');
PRINT N'ok: notification + audit inserted';

------------------------------------------------------------------ must be rejected
BEGIN TRY INSERT dbo.users (email, full_name, password_hash, role, created_by) VALUES (N'STUDENT@ELIO.TEST', N'Dup', N'x', 'STUDENT', @admin);
    PRINT N'FAIL: duplicate email (different case) accepted'; SET @fail += 1; END TRY
BEGIN CATCH PRINT N'ok: case-insensitive duplicate email rejected'; END CATCH;

BEGIN TRY INSERT dbo.students (user_id, student_code) VALUES (@inst, N'S999');
    PRINT N'FAIL: instructor inserted as student subtype'; SET @fail += 1; END TRY
BEGIN CATCH PRINT N'ok: subtype must match user role'; END CATCH;

BEGIN TRY INSERT dbo.course_memberships (offering_id, user_id, course_role) VALUES (@off, @admin, 'CO_INSTRUCTOR');
    PRINT N'FAIL: admin added as co-instructor'; SET @fail += 1; END TRY
BEGIN CATCH PRINT N'ok: membership role must match account role'; END CATCH;

BEGIN TRY
    INSERT dbo.users (email, full_name, password_hash, role, created_by) VALUES (N't2@elio.test', N'T2', N'x', 'INSTRUCTOR', @admin);
    INSERT dbo.instructors (user_id) VALUES (SCOPE_IDENTITY());
    INSERT dbo.course_memberships (offering_id, user_id, course_role) VALUES (@off, (SELECT user_id FROM dbo.users WHERE email = N't2@elio.test'), 'PRIMARY_INSTRUCTOR');
    PRINT N'FAIL: second active lead accepted'; SET @fail += 1; END TRY
BEGIN CATCH PRINT N'ok: only one active primary instructor per offering'; END CATCH;

BEGIN TRY INSERT dbo.course_offerings (course_id, semester, section_code, title, created_by) VALUES (@course, N'2026A', N'01', N'dup', @inst);
    PRINT N'FAIL: duplicate course/semester/section accepted'; SET @fail += 1; END TRY
BEGIN CATCH PRINT N'ok: UNIQUE (course, semester, section)'; END CATCH;

BEGIN TRY INSERT dbo.course_offerings (course_id, semester, section_code, title, created_by, join_code) VALUES (@course, N'2026A', N'02', N'x', @inst, 'abc123');
    PRINT N'FAIL: lowercase join code accepted'; SET @fail += 1; END TRY
BEGIN CATCH PRINT N'ok: join code must be 6 upper-case alphanumerics'; END CATCH;

BEGIN TRY INSERT dbo.assignments (activity_id, instructions, open_at, due_at, cutoff_at) VALUES (@quizAct, N'x', @now, @now, @now);
    PRINT N'FAIL: quiz activity used as assignment'; SET @fail += 1; END TRY
BEGIN CATCH PRINT N'ok: assignment subtype must match activity type'; END CATCH;

BEGIN TRY
    INSERT dbo.activities (offering_id, activity_type, title, max_score) VALUES (@off, 'ASSIGNMENT', N'Bad', 10);
    INSERT dbo.assignments (activity_id, instructions, open_at, due_at, cutoff_at) VALUES (SCOPE_IDENTITY(), N'x', @now, DATEADD(DAY, 2, @now), DATEADD(DAY, 1, @now));
    PRINT N'FAIL: cutoff before due accepted'; SET @fail += 1; END TRY
BEGIN CATCH PRINT N'ok: open <= due <= cutoff'; END CATCH;

BEGIN TRY INSERT dbo.file_assets (offering_id, uploaded_by, purpose, assignment_id, file_key, file_name, mime_type, size_bytes, sha256, uploaded_at, expires_at)
    VALUES (@off, @stu, 'SUBMISSION', @act, 'k/big', N'big.zip', N'application/zip', 20000001, REPLICATE('0', 64), @now, DATEADD(HOUR, 24, @now));
    PRINT N'FAIL: 20MB+1 submission file accepted'; SET @fail += 1; END TRY
BEGIN CATCH PRINT N'ok: submission file size limit'; END CATCH;

BEGIN TRY INSERT dbo.file_materials (material_id, file_id) VALUES (1, @asset);
    PRINT N'FAIL: SUBMISSION asset used as material'; SET @fail += 1; END TRY
BEGIN CATCH PRINT N'ok: file purpose enforced for materials'; END CATCH;

BEGIN TRY INSERT dbo.submissions (assignment_id, owner_type, student_id, status) VALUES (@act, 'INDIVIDUAL', @stu, 'NOT_SUBMITTED');
    PRINT N'FAIL: second submission for same student/assignment'; SET @fail += 1; END TRY
BEGIN CATCH PRINT N'ok: one submission per student per assignment'; END CATCH;

BEGIN TRY INSERT dbo.submission_versions (submission_id, version_no, submitted_by, submitted_at, is_late, receipt_code, request_key, request_hash)
    VALUES (@sub, 2, @stu, @now, 0, 'RCPT-0002', 'key-0123456789abcdef', REPLICATE('e', 64));
    PRINT N'FAIL: reused idempotency key accepted'; SET @fail += 1; END TRY
BEGIN CATCH PRINT N'ok: UNIQUE (submitted_by, request_key)'; END CATCH;

BEGIN TRY INSERT dbo.grade_revisions (grade_id, revision_no, submission_id, source_version_no, score, is_missing_zero, zero_reason, revised_by)
    VALUES (@grade, 2, @sub, NULL, 5, 1, N'No work', @inst);
    PRINT N'FAIL: missing-zero with score 5 accepted'; SET @fail += 1; END TRY
BEGIN CATCH PRINT N'ok: missing zero must score 0'; END CATCH;

BEGIN TRY UPDATE dbo.grades SET published_at = NULL WHERE grade_id = @grade;
    PRINT N'FAIL: published pointer without timestamp'; SET @fail += 1; END TRY
BEGIN CATCH PRINT N'ok: published pointer and timestamp go together'; END CATCH;

BEGIN TRY INSERT dbo.quiz_attempts (quiz_id, student_id, started_at, ends_at) VALUES (@quizAct, @stu, @now, DATEADD(MINUTE, 30, @now));
    PRINT N'FAIL: second quiz attempt accepted'; SET @fail += 1; END TRY
BEGIN CATCH PRINT N'ok: one attempt per student per quiz'; END CATCH;

BEGIN TRY UPDATE dbo.attempt_answers SET selected_key = 'maybe' WHERE attempt_id = @att;
    PRINT N'FAIL: answer key outside snapshot options'; SET @fail += 1; END TRY
BEGIN CATCH PRINT N'ok: answers must use a snapshot option key'; END CATCH;

BEGIN TRY INSERT dbo.notifications (recipient_id, actor_id, event_type, message, target_type, target_id, event_key)
    VALUES (@stu, @inst, 'GRADE_PUBLISHED', N'dup', 'ASSIGNMENT', @act, 'grade-published:1');
    PRINT N'FAIL: duplicate notification event accepted'; SET @fail += 1; END TRY
BEGIN CATCH PRINT N'ok: notification event is idempotent per recipient'; END CATCH;

BEGIN TRY INSERT dbo.notifications (recipient_id, actor_id, event_type, message, target_type, target_id, event_key)
    VALUES (@inst, @inst, 'X', N'self', 'ASSIGNMENT', @act, 'self:1');
    PRINT N'FAIL: actor notified about own action'; SET @fail += 1; END TRY
BEGIN CATCH PRINT N'ok: actor excluded from audience'; END CATCH;

BEGIN TRY INSERT dbo.audit_entries (actor_id, action_type, target_type, target_id, details) VALUES (@admin, 'X', 'USER', 1, N'not json');
    PRINT N'FAIL: invalid JSON audit details accepted'; SET @fail += 1; END TRY
BEGIN CATCH PRINT N'ok: audit details must be JSON'; END CATCH;

ROLLBACK TRANSACTION;

IF @fail = 0 PRINT N'PASS: schema smoke test (all changes rolled back)';
ELSE RAISERROR(N'FAIL: %d schema check(s) failed', 16, 1, @fail);
