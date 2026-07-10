FROM node:20-slim AS frontend
WORKDIR /fe
COPY frontend/package*.json ./
RUN npm install
COPY frontend ./
RUN npm run build

FROM python:3.12-slim
WORKDIR /srv
COPY config.toml ./config.toml
COPY backend/pyproject.toml ./backend/
RUN pip install --no-cache-dir ./backend
COPY backend ./backend
COPY --from=frontend /fe/dist ./backend/static
WORKDIR /srv/backend
RUN chmod +x entrypoint.sh
ENTRYPOINT ["./entrypoint.sh"]
