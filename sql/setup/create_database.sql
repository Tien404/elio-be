/*
  create_database  — run once per environment while connected to master.
  ---------------------------------------------------------------------------
  Creates the isolated ELIO database named by the sqlcmd variable DbName
  (sql/apply_migrations.ps1 passes it; default there is elio_dev).
  Manual run:  sqlcmd -S localhost -E -C -I -v DbName="elio_dev" -i sql/setup/create_database.sql
  SSMS: enable Query > SQLCMD Mode and add  :setvar DbName elio_dev  at the top.
  Rollback   : DROP DATABASE [elio_dev];   (destroys all data)
  Post-check : SELECT name, collation_name FROM sys.databases WHERE name = N'$(DbName)';
*/
SET NOCOUNT ON;

IF DB_ID(N'$(DbName)') IS NULL
BEGIN
    CREATE DATABASE [$(DbName)] COLLATE SQL_Latin1_General_CP1_CI_AS;
    PRINT N'Database $(DbName) created.';
END
ELSE
    PRINT N'Database $(DbName) already exists; nothing to do.';
GO

-- Snapshot-based reads reduce reader/writer blocking for dashboards and lists.
ALTER DATABASE [$(DbName)] SET READ_COMMITTED_SNAPSHOT ON WITH ROLLBACK IMMEDIATE;
GO
