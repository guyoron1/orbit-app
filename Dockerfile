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
COPY backend/start.sh ./start.sh
RUN chmod +x start.sh
CMD ["./start.sh"]
