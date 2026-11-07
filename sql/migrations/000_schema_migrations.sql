/*
  000_schema_migrations
  ---------------------------------------------------------------------------
  Purpose      : Migration history table used by every later script.
  Target DB    : elio_dev (or any isolated ELIO database); run while connected to it.
  Prerequisite : sql/setup/create_database.sql (database exists).
  Transaction  : single transaction, XACT_ABORT ON; re-running is a no-op.
  Rollback     : DROP TABLE dbo.schema_migrations;  (only after all other migrations are rolled back)
  Post-check   : SELECT * FROM dbo.schema_migrations;
*/
SET ANSI_NULLS ON;
SET QUOTED_IDENTIFIER ON;
SET XACT_ABORT ON;
SET NOCOUNT ON;

IF OBJECT_ID(N'dbo.schema_migrations', N'U') IS NOT NULL
BEGIN
    PRINT N'000_schema_migrations already applied; skipping.';
    RETURN;
END;

BEGIN TRANSACTION;

CREATE TABLE dbo.schema_migrations (
    migration_id NVARCHAR(100)    NOT NULL,
    applied_at   DATETIMEOFFSET(7) NOT NULL CONSTRAINT DF_schema_migrations_applied_at DEFAULT SYSUTCDATETIME(),
    applied_by   NVARCHAR(128)    NOT NULL CONSTRAINT DF_schema_migrations_applied_by DEFAULT SUSER_SNAME(),
    CONSTRAINT PK_schema_migrations PRIMARY KEY (migration_id)
);

INSERT dbo.schema_migrations (migration_id) VALUES (N'000_schema_migrations');

COMMIT TRANSACTION;
PRINT N'000_schema_migrations applied.';
