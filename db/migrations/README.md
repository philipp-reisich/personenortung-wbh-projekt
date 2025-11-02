# Database Migrations

The RTLS prototype uses [Alembic](https://alembic.sqlalchemy.org/) for
managing database schema migrations. When you make changes to the database
structure, generate a new migration and apply it to your database.

## Usage

1. Install Alembic into your virtual environment (already installed via
   `api/requirements.txt`).
2. Copy the `alembic.ini.example` (not provided here) to `alembic.ini` and
   adjust the `sqlalchemy.url` to match your database.
3. Initialize the Alembic environment in this directory:

   ```sh
   alembic init .
   ```

4. Generate a new migration after editing `db/schema.sql` or the ORM models:

   ```sh
   alembic revision --autogenerate -m "Add new table"
   ```

5. Apply migrations to the database:

   ```sh
   alembic upgrade head
   ```

For the purposes of this prototype, the base schema is applied from
`schema.sql` during container startup. Migrations are optional but
recommended for future evolution.