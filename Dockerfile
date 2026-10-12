FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .
COPY templates templates
COPY static static

ENV PYTHONUNBUFFERED=1 \
    DB_PATH=/data/data.db \
    HOME=/tmp

# Run unprivileged; docker-compose.yml overrides the uid to match the owner of ./data
RUN mkdir /data && chown 1000:1000 /data
USER 1000:1000

VOLUME /data
EXPOSE 5000

# One worker: SQLite has a single writer, and the daily backup thread should run once
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "1", "--threads", "4", "app:app"]
