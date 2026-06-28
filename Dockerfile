FROM python:3.12-slim
WORKDIR /srv
COPY backend/pyproject.toml ./backend/
RUN pip install --no-cache-dir ./backend
COPY backend ./backend
WORKDIR /srv/backend
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
