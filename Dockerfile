FROM python:3.11-slim

WORKDIR /app
COPY backend/requirements.txt ./backend/
RUN pip install --no-cache-dir -r backend/requirements.txt

# Cache bust — forces Docker to re-copy backend files
ARG CACHE_BUST=v5-full-endpoints
RUN echo "${CACHE_BUST}"

COPY backend/ ./backend/
COPY index.html .
COPY manifest.json .
COPY sw.js .

WORKDIR /app/backend
RUN python seed.py

WORKDIR /app/backend
CMD python -m uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
