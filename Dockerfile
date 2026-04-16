# Stage 1: Build frontend
FROM node:20-alpine AS frontend-builder
WORKDIR /app
COPY frontend/package.json frontend/package-lock.json ./
RUN --mount=type=cache,target=/root/.npm npm ci
COPY frontend/ .
ENV VITE_API_URL=/api
RUN npm run build

# Stage 2: Install Python dependencies (only reruns when pyproject.toml changes)
FROM python:3.12-slim AS backend-deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev libjpeg62-turbo-dev zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY backend/pyproject.toml .
RUN mkdir -p app && touch app/__init__.py
RUN pip install --no-cache-dir .

# Stage 3: Runtime
FROM python:3.12-slim AS runtime
ARG GALACTILOG_VERSION=dev
ARG GALACTILOG_GIT_SHA=unknown
ENV GALACTILOG_VERSION=${GALACTILOG_VERSION} \
    GALACTILOG_GIT_SHA=${GALACTILOG_GIT_SHA}

# Install runtime packages first (cacheable independent of app code)
RUN apt-get update && apt-get install -y --no-install-recommends \
    nginx supervisor curl gosu libcap2-bin \
    && rm -rf /var/lib/apt/lists/* \
    && rm -f /etc/nginx/sites-enabled/default \
    && groupadd -g 1000 galactilog \
    && useradd -u 1000 -g 1000 -M -s /sbin/nologin galactilog \
    && mkdir -p /var/log/nginx \
    && ln -sf /dev/stdout /var/log/nginx/access.log \
    && ln -sf /dev/stderr /var/log/nginx/error.log \
    && chown -R galactilog:galactilog /var/log/nginx

# Configure nginx paths and permissions (cacheable, depends only on base nginx config)
RUN mkdir -p /app/data/fits /app/data/thumbnails /app/data/thumbnails/previews \
             /app/run /app/run/nginx \
             /app/run/nginx/client_body /app/run/nginx/proxy \
             /app/run/nginx/fastcgi /app/run/nginx/uwsgi /app/run/nginx/scgi \
    && sed -i 's|^pid .*|pid /app/run/nginx/nginx.pid;|' /etc/nginx/nginx.conf \
    && sed -i 's|^user .*|user galactilog galactilog;|' /etc/nginx/nginx.conf \
    && sed -i 's|^error_log .*|error_log /var/log/nginx/error.log warn;|' /etc/nginx/nginx.conf \
    && sed -i '/^http {/a\    client_body_temp_path /app/run/nginx/client_body;\n    proxy_temp_path /app/run/nginx/proxy;\n    fastcgi_temp_path /app/run/nginx/fastcgi;\n    uwsgi_temp_path /app/run/nginx/uwsgi;\n    scgi_temp_path /app/run/nginx/scgi;' /etc/nginx/nginx.conf \
    && setcap cap_net_bind_service=+ep /usr/sbin/nginx

# Copy built artifacts from other stages
COPY --from=backend-deps /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=backend-deps /usr/local/bin /usr/local/bin
COPY --from=frontend-builder /app/dist /usr/share/nginx/html

# Copy application code (changes frequently, placed last)
COPY backend/app/ /app/app/
COPY backend/data/ /app/data/
COPY backend/alembic.ini /app/alembic.ini
COPY backend/alembic/ /app/alembic/
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY supervisord.conf /etc/supervisor/conf.d/supervisord.conf
COPY backend/entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh \
    && chown -R galactilog:galactilog /app/data /app/run

WORKDIR /app
ENV GALACTILOG_CELERY_CONCURRENCY=4
EXPOSE 80
CMD ["/app/entrypoint.sh"]
