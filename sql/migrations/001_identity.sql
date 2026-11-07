/*
  001_identity  (logical model group 1 / EERD section 1 "Identity & access")
  ---------------------------------------------------------------------------
  Tables       : users, students, instructors, admins, user_sessions
  Target DB    : elio_dev (or any isolated ELIO database).
  Prerequisite : 000_schema_migrations.
  Transaction  : single transaction, XACT_ABORT ON; skipped when already recorded.
  Rollback     : DROP TABLE user_sessions, admins, instructors, students (after
                 ALTER TABLE users DROP CONSTRAINT FK_users_created_by), users;
                 DELETE dbo.schema_migrations WHERE migration_id = N'001_identity';
  Post-check   : SELECT name FROM sys.tables ORDER BY name;

  Notes
  - Subtype tables carry a fixed role column + composite FK (user_id, role) so a
    STUDENT row can only point at a STUDENT user, etc. "Exactly one subtype per
    user" is enforced by the AuthService account transaction.
  - email uses a case-insensitive collation, so UNIQUE is case-insensitive.
  - token_hash is a lowercase hex SHA-256 of the opaque session token (never the token).
  - users.created_by -> admins is circular; it is added after admins exists.
    Only the bootstrap administrator may have created_by NULL (service rule).
*/
SET ANSI_NULLS ON;
SET QUOTED_IDENTIFIER ON;
SET XACT_ABORT ON;
SET NOCOUNT ON;

IF EXISTS (SELECT 1 FROM dbo.schema_migrations WHERE migration_id = N'001_identity')
BEGIN
    PRINT N'001_identity already applied; skipping.';
    RETURN;
END;

BEGIN TRANSACTION;

CREATE TABLE dbo.users (
    user_id         INT IDENTITY(1,1) NOT NULL,
    email           NVARCHAR(254) COLLATE Latin1_General_100_CI_AS NOT NULL,
    full_name       NVARCHAR(150)     NOT NULL,
    password_hash   NVARCHAR(255)     NOT NULL,
    role            VARCHAR(10)       NOT NULL,
    status          VARCHAR(10)       NOT NULL CONSTRAINT DF_users_status DEFAULT 'ACTIVE',
    must_change_pwd BIT               NOT NULL CONSTRAINT DF_users_must_change_pwd DEFAULT 1,
    created_by      INT               NULL,
    created_at      DATETIMEOFFSET(7) NOT NULL CONSTRAINT DF_users_created_at DEFAULT SYSUTCDATETIME(),
    version         INT               NOT NULL CONSTRAINT DF_users_version DEFAULT 1,
    CONSTRAINT PK_users PRIMARY KEY (user_id),
    CONSTRAINT UQ_users_email UNIQUE (email),
    CONSTRAINT UQ_users_user_role UNIQUE (user_id, role),
    CONSTRAINT CK_users_email CHECK (email LIKE N'%_@_%' AND email NOT LIKE N'% %'),
    CONSTRAINT CK_users_full_name CHECK (LEN(full_name) > 0),
    CONSTRAINT CK_users_role CHECK (role IN ('STUDENT', 'INSTRUCTOR', 'ADMIN')),
    CONSTRAINT CK_users_status CHECK (status IN ('ACTIVE', 'LOCKED')),
    CONSTRAINT CK_users_version CHECK (version >= 1)
);

CREATE TABLE dbo.students (
    user_id      INT          NOT NULL,
    role         VARCHAR(10)  NOT NULL CONSTRAINT DF_students_role DEFAULT 'STUDENT',
    student_code NVARCHAR(20) NOT NULL,
    CONSTRAINT PK_students PRIMARY KEY (user_id),
    CONSTRAINT UQ_students_student_code UNIQUE (student_code),
    CONSTRAINT CK_students_role CHECK (role = 'STUDENT'),
    CONSTRAINT CK_students_student_code CHECK (LEN(student_code) > 0),
    CONSTRAINT FK_students_users FOREIGN KEY (user_id, role) REFERENCES dbo.users (user_id, role)
);

CREATE TABLE dbo.instructors (
    user_id           INT           NOT NULL,
    role              VARCHAR(10)   NOT NULL CONSTRAINT DF_instructors_role DEFAULT 'INSTRUCTOR',
    can_create_course BIT           NOT NULL CONSTRAINT DF_instructors_can_create_course DEFAULT 0,
    department        NVARCHAR(100) NULL,
    CONSTRAINT PK_instructors PRIMARY KEY (user_id),
    CONSTRAINT CK_instructors_role CHECK (role = 'INSTRUCTOR'),
    CONSTRAINT FK_instructors_users FOREIGN KEY (user_id, role) REFERENCES dbo.users (user_id, role)
);

CREATE TABLE dbo.admins (
    user_id INT         NOT NULL,
    role    VARCHAR(10) NOT NULL CONSTRAINT DF_admins_role DEFAULT 'ADMIN',
    CONSTRAINT PK_admins PRIMARY KEY (user_id),
    CONSTRAINT CK_admins_role CHECK (role = 'ADMIN'),
    CONSTRAINT FK_admins_users FOREIGN KEY (user_id, role) REFERENCES dbo.users (user_id, role)
);

ALTER TABLE dbo.users
    ADD CONSTRAINT FK_users_created_by FOREIGN KEY (created_by) REFERENCES dbo.admins (user_id);

CREATE TABLE dbo.user_sessions (
    session_id INT IDENTITY(1,1) NOT NULL,
    user_id    INT               NOT NULL,
    token_hash CHAR(64) COLLATE Latin1_General_100_BIN2 NOT NULL,
    issued_at  DATETIMEOFFSET(7) NOT NULL CONSTRAINT DF_user_sessions_issued_at DEFAULT SYSUTCDATETIME(),
    expires_at DATETIMEOFFSET(7) NOT NULL,
    revoked_at DATETIMEOFFSET(7) NULL,
    restricted BIT               NOT NULL CONSTRAINT DF_user_sessions_restricted DEFAULT 0,
    CONSTRAINT PK_user_sessions PRIMARY KEY (session_id),
    CONSTRAINT UQ_user_sessions_token_hash UNIQUE (token_hash),
    CONSTRAINT CK_user_sessions_token_hash CHECK (token_hash NOT LIKE '%[^0-9a-f]%'),
    CONSTRAINT CK_user_sessions_expiry CHECK (expires_at > issued_at),
    CONSTRAINT CK_user_sessions_revoked CHECK (revoked_at IS NULL OR revoked_at >= issued_at),
    CONSTRAINT FK_user_sessions_users FOREIGN KEY (user_id) REFERENCES dbo.users (user_id)
);

-- "Revoke all sessions of a user" and "list active sessions" lookups.
CREATE INDEX IX_user_sessions_user_active ON dbo.user_sessions (user_id, expires_at) WHERE revoked_at IS NULL;

INSERT dbo.schema_migrations (migration_id) VALUES (N'001_identity');

COMMIT TRANSACTION;
PRINT N'001_identity applied.';
