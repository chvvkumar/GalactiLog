# Stage 1: Build frontend
FROM node:20-alpine AS frontend-builder
WORKDIR /app
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ .
ENV VITE_API_URL=/api
RUN npm run build

# Stage 2: Install Python dependencies
FROM python:3.12-slim AS backend-deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev libjpeg62-turbo-dev zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY backend/pyproject.toml .
COPY backend/app/ app/
RUN pip install --no-cache-dir .

# Stage 3: Runtime
FROM python:3.12-slim AS runtime
RUN apt-get update && apt-get install -y --no-install-recommends \
    nginx supervisor curl \
    && rm -rf /var/lib/apt/lists/* \
    && rm -f /etc/nginx/sites-enabled/default

COPY --from=backend-deps /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=backend-deps /usr/local/bin /usr/local/bin
COPY --from=frontend-builder /app/dist /usr/share/nginx/html
COPY backend/app/ /app/app/
COPY backend/data/ /app/data/
COPY backend/alembic.ini /app/alembic.ini
COPY backend/alembic/ /app/alembic/
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY supervisord.conf /etc/supervisor/conf.d/supervisord.conf
COPY backend/entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh \
    && mkdir -p /app/data/fits /app/data/thumbnails /app/data/thumbnails/previews

WORKDIR /app
ENV GALACTILOG_CELERY_CONCURRENCY=4
EXPOSE 80
CMD ["/app/entrypoint.sh"]
