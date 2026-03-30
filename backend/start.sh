#!/bin/sh
set -e

echo "Running database migrations..."
# Check if alembic_version table exists. If tables exist but no alembic tracking,
# stamp the current revision so future migrations apply incrementally.
python -c "
from app.database import engine
from sqlalchemy import inspect
insp = inspect(engine)
tables = insp.get_table_names()
if 'alembic_version' not in tables and len(tables) > 0:
    print('Existing DB without migration tracking — stamping current revision')
    import subprocess
    subprocess.run(['python', '-m', 'alembic', 'stamp', 'head'], check=True)
"
python -m alembic upgrade head

echo "Seeding database (skips if data exists)..."
python -c "from seed import seed; seed()"

echo "Starting server..."
exec python -m uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
