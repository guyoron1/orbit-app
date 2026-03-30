FROM python:3.11-slim

WORKDIR /app
COPY backend/requirements.txt ./backend/
RUN pip install --no-cache-dir -r backend/requirements.txt

COPY backend/ ./backend/
COPY index.html .
COPY manifest.json .
COPY sw.js .

# Force cache bust for new party/challenge features
RUN echo "deploy-v5-fix-endpoints-httpx"

WORKDIR /app/backend
RUN python seed.py

WORKDIR /app/backend
CMD python -m uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
