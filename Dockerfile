FROM node:20-slim AS frontend
WORKDIR /fe
COPY frontend/package*.json ./
RUN npm install
COPY frontend ./
RUN npm run build

FROM python:3.12-slim
WORKDIR /srv
COPY backend/pyproject.toml ./backend/
RUN pip install --no-cache-dir ./backend
COPY backend ./backend
COPY --from=frontend /fe/dist ./backend/static
WORKDIR /srv/backend
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
