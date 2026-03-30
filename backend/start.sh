#!/bin/sh

echo "=== Orbit Startup ==="

# Handle database schema and Alembic state in one step
python -c "
from app.database import Base, engine
from app import models  # register all models
from sqlalchemy import inspect

tables = inspect(engine).get_table_names()
has_alembic = 'alembic_version' in tables
has_tables = len([t for t in tables if t != 'alembic_version']) > 0

if has_tables and has_alembic:
    # Normal case: run pending migrations
    print('Running pending Alembic migrations...')
    import subprocess, sys
    subprocess.run([sys.executable, '-m', 'alembic', 'upgrade', 'head'], check=True)

elif has_tables and not has_alembic:
    # Tables from create_all but no Alembic tracking — stamp head
    print('Existing tables without Alembic — stamping head')
    import subprocess, sys
    subprocess.run([sys.executable, '-m', 'alembic', 'stamp', 'head'], check=True)

else:
    # Empty DB — create tables via create_all, then stamp
    print('Empty database — creating tables...')
    Base.metadata.create_all(bind=engine)
    print('Stamping Alembic head...')
    import subprocess, sys
    subprocess.run([sys.executable, '-m', 'alembic', 'stamp', 'head'], check=True)
" || echo "WARNING: migration step had an error, continuing"

echo "Seeding database (skips if data exists)..."
python -c "from seed import seed; seed()" || echo "WARNING: seed failed"

echo "Starting server..."
exec python -m uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
