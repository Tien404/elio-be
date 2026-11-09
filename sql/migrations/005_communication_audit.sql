-- MySQL 8.4 / UTC. Apply with python -m scripts.migrate.

CREATE TABLE announcements (
    announcement_id INT AUTO_INCREMENT NOT NULL,
    offering_id     INT               NOT NULL,
    author_id       INT               NOT NULL,
    title           VARCHAR(200)     NOT NULL,
    body            LONGTEXT     NOT NULL,
    status          VARCHAR(10)       NOT NULL DEFAULT 'DRAFT',
    published_at    DATETIME(6) NULL,
    version         INT               NOT NULL DEFAULT 1,
    CONSTRAINT PK_announcements PRIMARY KEY (announcement_id),
    CONSTRAINT CK_announcements_title CHECK (CHAR_LENGTH(title) > 0),
    CONSTRAINT CK_announcements_body CHECK (CHAR_LENGTH(body) > 0),
    CONSTRAINT CK_announcements_status CHECK (status IN ('DRAFT', 'PUBLISHED', 'ARCHIVED')),
    CONSTRAINT CK_announcements_published CHECK (status = 'DRAFT' OR published_at IS NOT NULL),
    CONSTRAINT CK_announcements_version CHECK (version >= 1),
    CONSTRAINT FK_announcements_offerings FOREIGN KEY (offering_id) REFERENCES course_offerings (offering_id),
    CONSTRAINT FK_announcements_author FOREIGN KEY (author_id) REFERENCES users (user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_as_ci;

CREATE INDEX IX_announcements_offering ON announcements (offering_id, status, published_at DESC);

CREATE TABLE notifications (
    notification_id INT AUTO_INCREMENT NOT NULL,
    recipient_id    INT               NOT NULL,
    actor_id        INT               NULL,
    offering_id     INT               NULL,
    event_type      VARCHAR(30)       NOT NULL,
    message         VARCHAR(500)     NOT NULL,
    target_type     VARCHAR(80)       NOT NULL,
    target_id       INT               NOT NULL,
    created_at      DATETIME(6) NOT NULL DEFAULT (UTC_TIMESTAMP(6)),
    is_read         BOOLEAN               NOT NULL DEFAULT 0,
    event_key       VARCHAR(200) COLLATE utf8mb4_bin NOT NULL,
    CONSTRAINT PK_notifications PRIMARY KEY (notification_id),
    CONSTRAINT UQ_notifications_event UNIQUE (recipient_id, event_key),
    CONSTRAINT CK_notifications_not_actor CHECK (actor_id IS NULL OR actor_id <> recipient_id),
    CONSTRAINT CK_notifications_message CHECK (CHAR_LENGTH(message) > 0),
    CONSTRAINT CK_notifications_target_id CHECK (target_id > 0),
    CONSTRAINT FK_notifications_recipient FOREIGN KEY (recipient_id) REFERENCES users (user_id),
    CONSTRAINT FK_notifications_actor FOREIGN KEY (actor_id) REFERENCES users (user_id),
    CONSTRAINT FK_notifications_offerings FOREIGN KEY (offering_id) REFERENCES course_offerings (offering_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_as_ci;


CREATE INDEX IX_notifications_inbox ON notifications (recipient_id, created_at DESC);

CREATE TABLE audit_entries (
    audit_id    INT AUTO_INCREMENT NOT NULL,
    actor_id    INT               NOT NULL,
    action_type VARCHAR(100)      NOT NULL,
    target_type VARCHAR(80)       NOT NULL,
    target_id   INT               NOT NULL,
    reason      VARCHAR(1000)    NULL,
    details     LONGTEXT     NOT NULL DEFAULT ('{}'),
    created_at  DATETIME(6) NOT NULL DEFAULT (UTC_TIMESTAMP(6)),
    CONSTRAINT PK_audit_entries PRIMARY KEY (audit_id),
    CONSTRAINT CK_audit_entries_details CHECK (JSON_VALID(details) = 1),
    CONSTRAINT CK_audit_entries_action CHECK (CHAR_LENGTH(action_type) > 0),
    CONSTRAINT FK_audit_entries_actor FOREIGN KEY (actor_id) REFERENCES users (user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_as_ci;

CREATE INDEX IX_audit_entries_target ON audit_entries (target_type, target_id, created_at);
CREATE INDEX IX_audit_entries_created ON audit_entries (created_at);
