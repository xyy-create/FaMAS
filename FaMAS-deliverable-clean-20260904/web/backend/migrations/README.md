# Database Migrations

This directory contains Alembic migrations for the FaMAS Web backend.

Development startup runs Alembic migrations by default. For normal local development, start the backend and it will upgrade the configured database to the latest revision before seeding initial data.

To disable startup migrations, set:

```powershell
$env:FAMAS_AUTO_MIGRATE_DATABASE = "0"
```

Then run migrations manually:

```powershell
python -m alembic upgrade head
```

For an existing local SQLite database that was already created before Alembic was added, startup can stamp the legacy schema into Alembic after applying the local compatibility checks. For formal databases, create a backup and run `alembic stamp head` manually only after confirming the current tables match the models.
