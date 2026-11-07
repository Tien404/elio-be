/*
  005_communication_audit  (logical model group 5 / EERD section 5 "Communication & audit")
  ---------------------------------------------------------------------------
  Tables       : announcements, notifications, audit_entries
  Target DB    : elio_dev (or any isolated ELIO database).
  Prerequisite : 004_quiz_engine.
  Transaction  : single transaction, XACT_ABORT ON; skipped when already recorded.
  Rollback     : DROP TABLE audit_entries, notifications, announcements;
                 DELETE dbo.schema_migrations WHERE migration_id = N'005_communication_audit';
  Post-check   : SELECT name FROM sys.tables ORDER BY name;

  Notes
  - Forum tables from the EERD (forum_threads / forum_posts) are intentionally omitted:
    forum is out of scope per docs/GUIDE.md.
  - notifications: UNIQUE (recipient_id, event_key) makes retried event delivery idempotent;
    the actor is never in the audience (CHECK actor_id <> recipient_id).
  - audit_entries.details is JSON stored as NVARCHAR(MAX) with ISJSON validation.
    Append-only is enforced through application privileges (grant INSERT/SELECT only).
*/
SET ANSI_NULLS ON;
SET QUOTED_IDENTIFIER ON;
SET XACT_ABORT ON;
SET NOCOUNT ON;

IF EXISTS (SELECT 1 FROM dbo.schema_migrations WHERE migration_id = N'005_communication_audit')
BEGIN
    PRINT N'005_communication_audit already applied; skipping.';
    RETURN;
END;

BEGIN TRANSACTION;

CREATE TABLE dbo.announcements (
    announcement_id INT IDENTITY(1,1) NOT NULL,
    offering_id     INT               NOT NULL,
    author_id       INT               NOT NULL,
    title           NVARCHAR(200)     NOT NULL,
    body            NVARCHAR(MAX)     NOT NULL,
    status          VARCHAR(10)       NOT NULL CONSTRAINT DF_announcements_status DEFAULT 'DRAFT',
    published_at    DATETIMEOFFSET(7) NULL,
    version         INT               NOT NULL CONSTRAINT DF_announcements_version DEFAULT 1,
    CONSTRAINT PK_announcements PRIMARY KEY (announcement_id),
    CONSTRAINT CK_announcements_title CHECK (LEN(title) > 0),
    CONSTRAINT CK_announcements_body CHECK (LEN(body) > 0),
    CONSTRAINT CK_announcements_status CHECK (status IN ('DRAFT', 'PUBLISHED', 'ARCHIVED')),
    CONSTRAINT CK_announcements_published CHECK (status = 'DRAFT' OR published_at IS NOT NULL),
    CONSTRAINT CK_announcements_version CHECK (version >= 1),
    CONSTRAINT FK_announcements_offerings FOREIGN KEY (offering_id) REFERENCES dbo.course_offerings (offering_id),
    CONSTRAINT FK_announcements_author FOREIGN KEY (author_id) REFERENCES dbo.users (user_id)
);

CREATE INDEX IX_announcements_offering ON dbo.announcements (offering_id, status, published_at DESC);

CREATE TABLE dbo.notifications (
    notification_id INT IDENTITY(1,1) NOT NULL,
    recipient_id    INT               NOT NULL,
    actor_id        INT               NULL,
    offering_id     INT               NULL,
    event_type      VARCHAR(30)       NOT NULL,
    message         NVARCHAR(500)     NOT NULL,
    target_type     VARCHAR(80)       NOT NULL,
    target_id       INT               NOT NULL,
    created_at      DATETIMEOFFSET(7) NOT NULL CONSTRAINT DF_notifications_created_at DEFAULT SYSUTCDATETIME(),
    is_read         BIT               NOT NULL CONSTRAINT DF_notifications_is_read DEFAULT 0,
    event_key       VARCHAR(200) COLLATE Latin1_General_100_BIN2 NOT NULL,
    CONSTRAINT PK_notifications PRIMARY KEY (notification_id),
    CONSTRAINT UQ_notifications_event UNIQUE (recipient_id, event_key),
    CONSTRAINT CK_notifications_not_actor CHECK (actor_id IS NULL OR actor_id <> recipient_id),
    CONSTRAINT CK_notifications_message CHECK (LEN(message) > 0),
    CONSTRAINT CK_notifications_target_id CHECK (target_id > 0),
    CONSTRAINT FK_notifications_recipient FOREIGN KEY (recipient_id) REFERENCES dbo.users (user_id),
    CONSTRAINT FK_notifications_actor FOREIGN KEY (actor_id) REFERENCES dbo.users (user_id),
    CONSTRAINT FK_notifications_offerings FOREIGN KEY (offering_id) REFERENCES dbo.course_offerings (offering_id)
);

-- Inbox: newest first, unread filter.
CREATE INDEX IX_notifications_inbox ON dbo.notifications (recipient_id, created_at DESC) INCLUDE (is_read);

CREATE TABLE dbo.audit_entries (
    audit_id    INT IDENTITY(1,1) NOT NULL,
    actor_id    INT               NOT NULL,
    action_type VARCHAR(100)      NOT NULL,
    target_type VARCHAR(80)       NOT NULL,
    target_id   INT               NOT NULL,
    reason      NVARCHAR(1000)    NULL,
    details     NVARCHAR(MAX)     NOT NULL CONSTRAINT DF_audit_entries_details DEFAULT N'{}',
    created_at  DATETIMEOFFSET(7) NOT NULL CONSTRAINT DF_audit_entries_created_at DEFAULT SYSUTCDATETIME(),
    CONSTRAINT PK_audit_entries PRIMARY KEY (audit_id),
    CONSTRAINT CK_audit_entries_details CHECK (ISJSON(details) = 1),
    CONSTRAINT CK_audit_entries_action CHECK (LEN(action_type) > 0),
    CONSTRAINT FK_audit_entries_actor FOREIGN KEY (actor_id) REFERENCES dbo.users (user_id)
);

CREATE INDEX IX_audit_entries_target ON dbo.audit_entries (target_type, target_id, created_at);
CREATE INDEX IX_audit_entries_created ON dbo.audit_entries (created_at);

INSERT dbo.schema_migrations (migration_id) VALUES (N'005_communication_audit');

COMMIT TRANSACTION;
PRINT N'005_communication_audit applied.';
