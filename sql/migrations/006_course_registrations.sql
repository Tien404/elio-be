-- MySQL 8.4 / UTC. Apply with python -m scripts.migrate.

CREATE TABLE course_registrations (
    registration_id INT AUTO_INCREMENT NOT NULL,
    course_id       INT               NOT NULL,
    student_id      INT               NOT NULL,
    status          VARCHAR(10)       NOT NULL DEFAULT 'PENDING',
    requested_at    DATETIME(6) NOT NULL DEFAULT (UTC_TIMESTAMP(6)),
    decided_by      INT               NULL,
    decided_at      DATETIME(6) NULL,
    version         INT               NOT NULL DEFAULT 1,
    CONSTRAINT PK_course_registrations PRIMARY KEY (registration_id),
    CONSTRAINT CK_course_registrations_status CHECK (status IN ('PENDING', 'APPROVED', 'REJECTED')),
    CONSTRAINT CK_course_registrations_decision CHECK (
           (status = 'PENDING' AND decided_by IS NULL AND decided_at IS NULL)
        OR (status <> 'PENDING' AND decided_by IS NOT NULL AND decided_at IS NOT NULL)),
    CONSTRAINT CK_course_registrations_version CHECK (version >= 1),
    CONSTRAINT FK_course_registrations_courses FOREIGN KEY (course_id) REFERENCES courses (course_id),
    CONSTRAINT FK_course_registrations_students FOREIGN KEY (student_id) REFERENCES students (user_id),
    CONSTRAINT FK_course_registrations_decided_by FOREIGN KEY (decided_by) REFERENCES admins (user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_as_ci;

ALTER TABLE course_registrations ADD open_student_id INT GENERATED ALWAYS AS (CASE WHEN status IN ('PENDING', 'APPROVED') THEN student_id END) STORED;
CREATE UNIQUE INDEX UX_course_registrations_open ON course_registrations (course_id, open_student_id);
CREATE INDEX IX_course_registrations_status ON course_registrations (status, course_id);
CREATE INDEX IX_course_registrations_student ON course_registrations (student_id, status);
