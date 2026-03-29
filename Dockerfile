FROM python:3.11-slim

WORKDIR /app
COPY backend/requirements.txt ./backend/
RUN pip install --no-cache-dir -r backend/requirements.txt

COPY backend/ ./backend/
COPY index.html .

# Force cache bust for new party/challenge features
RUN echo "deploy-v2-parties-challenges"

WORKDIR /app/backend
RUN python seed.py

WORKDIR /app/backend
CMD python -m uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
