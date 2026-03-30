#!/bin/sh

echo "=== Orbit Startup ==="

# Step 1: Stamp existing databases so Alembic knows they're current
python -c "
from app.database import engine
from sqlalchemy import inspect
tables = inspect(engine).get_table_names()
if 'alembic_version' not in tables and len(tables) > 0:
    print('Existing DB without migration tracking — stamping head')
    import subprocess, sys
    subprocess.run([sys.executable, '-m', 'alembic', 'stamp', 'head'], check=True)
elif 'alembic_version' in tables:
    print('Alembic version table found — will run upgrade')
else:
    print('Empty database — will create via migrations')
" || echo "WARNING: stamp check failed, continuing anyway"

# Step 2: Run migrations (creates tables for empty DBs, applies new migrations for existing)
python -m alembic upgrade head || echo "WARNING: alembic upgrade failed — tables may already exist, continuing"

# Step 3: Seed (only if DB is empty)
python -c "from seed import seed; seed()" || echo "WARNING: seed failed"

# Step 4: Start server
echo "Starting server..."
exec python -m uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
