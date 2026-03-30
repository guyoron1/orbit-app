FROM python:3.11-slim

WORKDIR /app
COPY backend/requirements.txt ./backend/
RUN pip install --no-cache-dir -r backend/requirements.txt

# Cache bust — forces Docker to re-copy backend files
ARG CACHE_BUST=v7-simple-cmd
RUN echo "${CACHE_BUST}"

COPY backend/ ./backend/
COPY index.html .
COPY manifest.json .
COPY sw.js .
COPY icon-192.png .
COPY icon-512.png .

WORKDIR /app/backend
CMD python -c "from seed import seed; seed()" && python -m uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
