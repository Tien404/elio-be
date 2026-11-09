SET ANSI_NULLS ON;
SET QUOTED_IDENTIFIER ON;
SET XACT_ABORT ON;
SET NOCOUNT ON;
IF EXISTS (SELECT 1 FROM dbo.schema_migrations WHERE migration_id=N'007_workspace_metadata') RETURN;
BEGIN TRANSACTION;
ALTER TABLE dbo.course_offerings ADD learning_information NVARCHAR(MAX) NULL;
INSERT dbo.schema_migrations (migration_id) VALUES (N'007_workspace_metadata');
COMMIT TRANSACTION;
