FROM python:3.11-slim

WORKDIR /app
COPY backend/requirements.txt ./backend/
RUN pip install --no-cache-dir -r backend/requirements.txt

# Cache bust — forces Docker to re-copy backend files
ARG CACHE_BUST=v22-overworld-init-fix
RUN echo "${CACHE_BUST}"

COPY backend/ ./backend/
COPY index.html .
COPY manifest.json .
COPY sw.js .
COPY icon-192.png .
COPY icon-512.png .
COPY icon-180.png .
COPY native-bridge.js .

WORKDIR /app/backend
RUN chmod +x start.sh
CMD ["./start.sh"]
