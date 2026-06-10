FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend ./backend
COPY frontend ./frontend

# Los datos demo (SQLite) y los uploads viven en /data para poder montarse como volumen
ENV DATABASE_URL=sqlite:////data/portal_proveedores.db \
    UPLOAD_DIR=/data/uploads \
    PORT=8000
RUN mkdir -p /data/uploads

EXPOSE 8000

CMD uvicorn app.main:app --app-dir backend --host 0.0.0.0 --port ${PORT}
