-- MySQL 8.4 / UTC. Apply with python -m scripts.migrate.

CREATE TABLE users (
    user_id         INT AUTO_INCREMENT NOT NULL,
    email           VARCHAR(254) COLLATE utf8mb4_0900_as_ci NOT NULL,
    full_name       VARCHAR(150)     NOT NULL,
    password_hash   VARCHAR(255)     NOT NULL,
    role            VARCHAR(10)       NOT NULL,
    status          VARCHAR(10)       NOT NULL DEFAULT 'ACTIVE',
    must_change_pwd BOOLEAN               NOT NULL DEFAULT 1,
    created_by      INT               NULL,
    created_at      DATETIME(6) NOT NULL DEFAULT (UTC_TIMESTAMP(6)),
    version         INT               NOT NULL DEFAULT 1,
    CONSTRAINT PK_users PRIMARY KEY (user_id),
    CONSTRAINT UQ_users_email UNIQUE (email),
    CONSTRAINT UQ_users_user_role UNIQUE (user_id, role),
    CONSTRAINT CK_users_email CHECK (email LIKE '%_@_%' AND email NOT LIKE '% %'),
    CONSTRAINT CK_users_full_name CHECK (CHAR_LENGTH(full_name) > 0),
    CONSTRAINT CK_users_role CHECK (role IN ('STUDENT', 'INSTRUCTOR', 'ADMIN')),
    CONSTRAINT CK_users_status CHECK (status IN ('ACTIVE', 'LOCKED')),
    CONSTRAINT CK_users_version CHECK (version >= 1)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_as_ci;

CREATE TABLE students (
    user_id      INT          NOT NULL,
    role         VARCHAR(10)  NOT NULL DEFAULT 'STUDENT',
    student_code VARCHAR(20) NOT NULL,
    CONSTRAINT PK_students PRIMARY KEY (user_id),
    CONSTRAINT UQ_students_student_code UNIQUE (student_code),
    CONSTRAINT CK_students_role CHECK (role = 'STUDENT'),
    CONSTRAINT CK_students_student_code CHECK (CHAR_LENGTH(student_code) > 0),
    CONSTRAINT FK_students_users FOREIGN KEY (user_id, role) REFERENCES users (user_id, role)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_as_ci;

CREATE TABLE instructors (
    user_id           INT           NOT NULL,
    role              VARCHAR(10)   NOT NULL DEFAULT 'INSTRUCTOR',
    can_create_course BOOLEAN           NOT NULL DEFAULT 0,
    department        VARCHAR(100) NULL,
    CONSTRAINT PK_instructors PRIMARY KEY (user_id),
    CONSTRAINT CK_instructors_role CHECK (role = 'INSTRUCTOR'),
    CONSTRAINT FK_instructors_users FOREIGN KEY (user_id, role) REFERENCES users (user_id, role)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_as_ci;

CREATE TABLE admins (
    user_id INT         NOT NULL,
    role    VARCHAR(10) NOT NULL DEFAULT 'ADMIN',
    CONSTRAINT PK_admins PRIMARY KEY (user_id),
    CONSTRAINT CK_admins_role CHECK (role = 'ADMIN'),
    CONSTRAINT FK_admins_users FOREIGN KEY (user_id, role) REFERENCES users (user_id, role)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_as_ci;

ALTER TABLE users
    ADD CONSTRAINT FK_users_created_by FOREIGN KEY (created_by) REFERENCES admins (user_id);

CREATE TABLE user_sessions (
    session_id INT AUTO_INCREMENT NOT NULL,
    user_id    INT               NOT NULL,
    token_hash CHAR(64) COLLATE utf8mb4_bin NOT NULL,
    issued_at  DATETIME(6) NOT NULL DEFAULT (UTC_TIMESTAMP(6)),
    expires_at DATETIME(6) NOT NULL,
    revoked_at DATETIME(6) NULL,
    restricted BOOLEAN               NOT NULL DEFAULT 0,
    CONSTRAINT PK_user_sessions PRIMARY KEY (session_id),
    CONSTRAINT UQ_user_sessions_token_hash UNIQUE (token_hash),
    CONSTRAINT CK_user_sessions_token_hash CHECK (REGEXP_LIKE(token_hash, '^[0-9a-f]{64}$', 'c')),
    CONSTRAINT CK_user_sessions_expiry CHECK (expires_at > issued_at),
    CONSTRAINT CK_user_sessions_revoked CHECK (revoked_at IS NULL OR revoked_at >= issued_at),
    CONSTRAINT FK_user_sessions_users FOREIGN KEY (user_id) REFERENCES users (user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_as_ci;


CREATE INDEX IX_user_sessions_user_active ON user_sessions (user_id, expires_at);
