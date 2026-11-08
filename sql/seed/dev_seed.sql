/*
  dev_seed — DEVELOPMENT ONLY test accounts.
  ---------------------------------------------------------------------------
  Creates user_id 1 as an administrator you can log in with immediately:
      email    : admin@elio.local
      password : ElioAdmin@2026
  The password is public (it is in this file), so NEVER run this outside a local dev database.
  The script refuses to run unless the database name contains "dev".

  Run:  sqlcmd -S localhost -E -C -I -b -d elio_dev -i sql/seed/dev_seed.sql
  Safe to re-run: skips accounts that already exist.
  Rollback: delete the rows (sessions/audit referencing the user first).
*/
SET ANSI_NULLS ON;
SET QUOTED_IDENTIFIER ON;
SET XACT_ABORT ON;
SET NOCOUNT ON;

DECLARE @db SYSNAME = DB_NAME();
IF @db NOT LIKE N'%dev%'
BEGIN
    RAISERROR(N'dev_seed refuses to run on database %s (name must contain "dev").', 16, 1, @db);
    RETURN;
END;

BEGIN TRANSACTION;

IF NOT EXISTS (SELECT 1 FROM dbo.users WHERE user_id = 1 OR email = N'admin@elio.local')
BEGIN
    SET IDENTITY_INSERT dbo.users ON;
    INSERT dbo.users (user_id, email, full_name, password_hash, role, status, must_change_pwd, created_by)
    VALUES (1, N'admin@elio.local', N'Dev Admin',
            N'scrypt$16384$8$1$sKL685k0_DTKpTK0nOLXEg$3SGsnHlQFD08SQVT9qZN6l1fUJSGKRDpZLiJOxgaIIc',
            'ADMIN', 'ACTIVE', 0, NULL);
    SET IDENTITY_INSERT dbo.users OFF;
    INSERT dbo.admins (user_id) VALUES (1);
    PRINT N'Created user 1: admin@elio.local (ADMIN).';
END
ELSE
    PRINT N'User 1 / admin@elio.local already exists; skipped.';

-- Keep IDENTITY ahead of the seeded id so the next account gets 2+.
DECLARE @max INT = (SELECT MAX(user_id) FROM dbo.users);
DBCC CHECKIDENT ('dbo.users', RESEED, @max) WITH NO_INFOMSGS;

COMMIT TRANSACTION;
