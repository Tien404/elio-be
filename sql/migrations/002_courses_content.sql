-- MySQL 8.4 / UTC. Apply with python -m scripts.migrate.

CREATE TABLE courses (
    course_id   INT AUTO_INCREMENT NOT NULL,
    course_code VARCHAR(40)  NOT NULL,
    course_name VARCHAR(200) NOT NULL,
    credits     DECIMAL(4,1)  NOT NULL,
    description LONGTEXT NULL,
    CONSTRAINT PK_courses PRIMARY KEY (course_id),
    CONSTRAINT UQ_courses_course_code UNIQUE (course_code),
    CONSTRAINT CK_courses_course_code CHECK (CHAR_LENGTH(course_code) > 0),
    CONSTRAINT CK_courses_course_name CHECK (CHAR_LENGTH(course_name) > 0),
    CONSTRAINT CK_courses_credits CHECK (credits > 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_as_ci;

CREATE TABLE course_offerings (
    offering_id       INT AUTO_INCREMENT NOT NULL,
    course_id         INT               NOT NULL,
    semester          VARCHAR(40)      NOT NULL,
    section_code      VARCHAR(40)      NOT NULL,
    title             VARCHAR(200)     NOT NULL,
    state             VARCHAR(10)       NOT NULL DEFAULT 'DRAFT',
    join_code         CHAR(6) COLLATE utf8mb4_bin NULL,
    join_code_enabled BOOLEAN               NOT NULL DEFAULT 0,
    created_by        INT               NOT NULL,
    created_at        DATETIME(6) NOT NULL DEFAULT (UTC_TIMESTAMP(6)),
    archived_at       DATETIME(6) NULL,
    version           INT               NOT NULL DEFAULT 1,
    CONSTRAINT PK_course_offerings PRIMARY KEY (offering_id),
    CONSTRAINT UQ_course_offerings_section UNIQUE (course_id, semester, section_code),
    CONSTRAINT CK_course_offerings_semester CHECK (CHAR_LENGTH(semester) > 0),
    CONSTRAINT CK_course_offerings_section_code CHECK (CHAR_LENGTH(section_code) > 0),
    CONSTRAINT CK_course_offerings_title CHECK (CHAR_LENGTH(title) > 0),
    CONSTRAINT CK_course_offerings_state CHECK (state IN ('DRAFT', 'OPEN', 'ARCHIVED')),

    CONSTRAINT CK_course_offerings_join_code CHECK (join_code IS NULL OR (REGEXP_LIKE(join_code, '^[A-Z0-9]{6}$', 'c'))),
    CONSTRAINT CK_course_offerings_join_enabled CHECK (join_code_enabled = 0 OR join_code IS NOT NULL),
    CONSTRAINT CK_course_offerings_archived CHECK ((state = 'ARCHIVED' AND archived_at IS NOT NULL) OR (state <> 'ARCHIVED' AND archived_at IS NULL)),
    CONSTRAINT CK_course_offerings_version CHECK (version >= 1),
    CONSTRAINT FK_course_offerings_courses FOREIGN KEY (course_id) REFERENCES courses (course_id),
    CONSTRAINT FK_course_offerings_created_by FOREIGN KEY (created_by) REFERENCES instructors (user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_as_ci;

CREATE UNIQUE INDEX UX_course_offerings_join_code ON course_offerings (join_code);

CREATE TABLE course_memberships (
    membership_id INT AUTO_INCREMENT NOT NULL,
    offering_id   INT               NOT NULL,
    user_id       INT               NOT NULL,
    course_role   VARCHAR(20)       NOT NULL,
    status        VARCHAR(10)       NOT NULL DEFAULT 'ACTIVE',
    joined_at     DATETIME(6) NOT NULL DEFAULT (UTC_TIMESTAMP(6)),
    version       INT               NOT NULL DEFAULT 1,
    member_role VARCHAR(10) GENERATED ALWAYS AS (CASE WHEN course_role = 'STUDENT' THEN 'STUDENT' ELSE 'INSTRUCTOR' END) STORED,
    CONSTRAINT PK_course_memberships PRIMARY KEY (membership_id),
    CONSTRAINT UQ_course_memberships_member UNIQUE (offering_id, user_id),
    CONSTRAINT CK_course_memberships_course_role CHECK (course_role IN ('STUDENT', 'PRIMARY_INSTRUCTOR', 'CO_INSTRUCTOR')),
    CONSTRAINT CK_course_memberships_status CHECK (status IN ('ACTIVE', 'REMOVED')),
    CONSTRAINT CK_course_memberships_version CHECK (version >= 1),
    CONSTRAINT FK_course_memberships_offerings FOREIGN KEY (offering_id) REFERENCES course_offerings (offering_id),
    CONSTRAINT FK_course_memberships_users FOREIGN KEY (user_id, member_role) REFERENCES users (user_id, role)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_as_ci;

ALTER TABLE course_memberships ADD active_lead_offering_id INT GENERATED ALWAYS AS (CASE WHEN course_role = 'PRIMARY_INSTRUCTOR' AND status = 'ACTIVE' THEN offering_id END) STORED;
CREATE UNIQUE INDEX UX_course_memberships_one_lead ON course_memberships (active_lead_offering_id);
CREATE INDEX IX_course_memberships_user ON course_memberships (user_id, status);

CREATE TABLE topics (
    topic_id    INT AUTO_INCREMENT NOT NULL,
    offering_id INT           NOT NULL,
    title       VARCHAR(200) NOT NULL,
    position    INT           NOT NULL,
    version     INT           NOT NULL DEFAULT 1,
    CONSTRAINT PK_topics PRIMARY KEY (topic_id),
    CONSTRAINT UQ_topics_position UNIQUE (offering_id, position),
    CONSTRAINT UQ_topics_topic_offering UNIQUE (topic_id, offering_id),
    CONSTRAINT CK_topics_title CHECK (CHAR_LENGTH(title) > 0),
    CONSTRAINT CK_topics_position CHECK (position > 0),
    CONSTRAINT CK_topics_version CHECK (version >= 1),
    CONSTRAINT FK_topics_offerings FOREIGN KEY (offering_id) REFERENCES course_offerings (offering_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_as_ci;

CREATE TABLE file_assets (
    file_id       INT AUTO_INCREMENT NOT NULL,
    offering_id   INT               NOT NULL,
    uploaded_by   INT               NOT NULL,
    purpose       VARCHAR(25)       NOT NULL,
    assignment_id INT               NULL,
    file_key      VARCHAR(255) COLLATE utf8mb4_bin NOT NULL,
    file_name     VARCHAR(255)     NOT NULL,
    mime_type     VARCHAR(127)     NOT NULL,
    size_bytes    INT               NOT NULL,
    sha256        CHAR(64) COLLATE utf8mb4_bin NOT NULL,
    state         VARCHAR(10)       NOT NULL DEFAULT 'STAGING',
    uploaded_at   DATETIME(6) NOT NULL,
    expires_at    DATETIME(6) NOT NULL,
    CONSTRAINT PK_file_assets PRIMARY KEY (file_id),
    CONSTRAINT UQ_file_assets_file_key UNIQUE (file_key),
    CONSTRAINT UQ_file_assets_file_purpose UNIQUE (file_id, purpose),
    CONSTRAINT CK_file_assets_purpose CHECK (purpose IN ('MATERIAL', 'ASSIGNMENT_ATTACHMENT', 'SUBMISSION')),
    CONSTRAINT CK_file_assets_state CHECK (state IN ('STAGING', 'ATTACHED', 'EXPIRED')),
    CONSTRAINT CK_file_assets_file_name CHECK (CHAR_LENGTH(file_name) > 0),
    CONSTRAINT CK_file_assets_size CHECK (size_bytes >= 1 AND size_bytes <= CASE WHEN purpose = 'MATERIAL' THEN 50000000 ELSE 20000000 END),
    CONSTRAINT CK_file_assets_sha256 CHECK (REGEXP_LIKE(sha256, '^[0-9a-f]{64}$', 'c')),
    CONSTRAINT CK_file_assets_assignment CHECK (
        (purpose = 'MATERIAL' AND assignment_id IS NULL)
        OR (purpose = 'SUBMISSION' AND assignment_id IS NOT NULL)
        OR purpose = 'ASSIGNMENT_ATTACHMENT'),
    CONSTRAINT CK_file_assets_expiry CHECK (expires_at = DATE_ADD(uploaded_at, INTERVAL 24 HOUR)),
    CONSTRAINT FK_file_assets_offerings FOREIGN KEY (offering_id) REFERENCES course_offerings (offering_id),
    CONSTRAINT FK_file_assets_uploaded_by FOREIGN KEY (uploaded_by) REFERENCES users (user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_as_ci;


CREATE INDEX IX_file_assets_staging_expiry ON file_assets (expires_at);
CREATE INDEX IX_file_assets_offering ON file_assets (offering_id, purpose);

CREATE TABLE materials (
    material_id  INT AUTO_INCREMENT NOT NULL,
    topic_id     INT               NOT NULL,
    kind         VARCHAR(4)        NOT NULL,
    title        VARCHAR(200)     NOT NULL,
    status       VARCHAR(10)       NOT NULL DEFAULT 'DRAFT',
    is_mandatory BOOLEAN               NOT NULL DEFAULT 0,
    created_at   DATETIME(6) NOT NULL DEFAULT (UTC_TIMESTAMP(6)),
    version      INT               NOT NULL DEFAULT 1,
    CONSTRAINT PK_materials PRIMARY KEY (material_id),
    CONSTRAINT UQ_materials_material_kind UNIQUE (material_id, kind),
    CONSTRAINT CK_materials_kind CHECK (kind IN ('FILE', 'TEXT', 'LINK')),
    CONSTRAINT CK_materials_status CHECK (status IN ('DRAFT', 'PUBLISHED', 'ARCHIVED')),
    CONSTRAINT CK_materials_title CHECK (CHAR_LENGTH(title) > 0),
    CONSTRAINT CK_materials_version CHECK (version >= 1),
    CONSTRAINT FK_materials_topics FOREIGN KEY (topic_id) REFERENCES topics (topic_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_as_ci;

CREATE INDEX IX_materials_topic ON materials (topic_id, status);

CREATE TABLE file_materials (
    material_id  INT        NOT NULL,
    kind         VARCHAR(4) NOT NULL DEFAULT 'FILE',
    file_id      INT        NOT NULL,
    file_purpose VARCHAR(25) NOT NULL DEFAULT 'MATERIAL' CHECK (file_purpose = 'MATERIAL'),
    CONSTRAINT PK_file_materials PRIMARY KEY (material_id),
    CONSTRAINT UQ_file_materials_file UNIQUE (file_id),
    CONSTRAINT CK_file_materials_kind CHECK (kind = 'FILE'),
    CONSTRAINT FK_file_materials_materials FOREIGN KEY (material_id, kind) REFERENCES materials (material_id, kind),
    CONSTRAINT FK_file_materials_file_assets FOREIGN KEY (file_id, file_purpose) REFERENCES file_assets (file_id, purpose)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_as_ci;

CREATE TABLE text_materials (
    material_id INT           NOT NULL,
    kind        VARCHAR(4)    NOT NULL DEFAULT 'TEXT',
    body        LONGTEXT NOT NULL,
    CONSTRAINT PK_text_materials PRIMARY KEY (material_id),
    CONSTRAINT CK_text_materials_kind CHECK (kind = 'TEXT'),
    CONSTRAINT CK_text_materials_body CHECK (CHAR_LENGTH(TRIM(body)) > 0),
    CONSTRAINT FK_text_materials_materials FOREIGN KEY (material_id, kind) REFERENCES materials (material_id, kind)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_as_ci;

CREATE TABLE link_materials (
    material_id INT            NOT NULL,
    kind        VARCHAR(4)     NOT NULL DEFAULT 'LINK',
    url         VARCHAR(2048) NOT NULL,
    CONSTRAINT PK_link_materials PRIMARY KEY (material_id),
    CONSTRAINT CK_link_materials_kind CHECK (kind = 'LINK'),
    CONSTRAINT CK_link_materials_url CHECK (url LIKE 'http://_%' OR url LIKE 'https://_%'),
    CONSTRAINT FK_link_materials_materials FOREIGN KEY (material_id, kind) REFERENCES materials (material_id, kind)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_as_ci;

CREATE TABLE material_completions (
    student_id   INT               NOT NULL,
    material_id  INT               NOT NULL,
    completed_at DATETIME(6) NOT NULL DEFAULT (UTC_TIMESTAMP(6)),
    CONSTRAINT PK_material_completions PRIMARY KEY (student_id, material_id),
    CONSTRAINT FK_material_completions_students FOREIGN KEY (student_id) REFERENCES students (user_id),
    CONSTRAINT FK_material_completions_materials FOREIGN KEY (material_id) REFERENCES materials (material_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_as_ci;

CREATE INDEX IX_material_completions_material ON material_completions (material_id);
