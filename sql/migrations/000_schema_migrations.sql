-- MySQL 8.4 / UTC. Apply with python -m scripts.migrate.

CREATE TABLE IF NOT EXISTS schema_migrations (
    migration_id VARCHAR(100)    NOT NULL,
    applied_at   DATETIME(6) NOT NULL DEFAULT (UTC_TIMESTAMP(6)),
    applied_by   VARCHAR(128)    NOT NULL DEFAULT (CURRENT_USER()),
    CONSTRAINT PK_schema_migrations PRIMARY KEY (migration_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_as_ci;
