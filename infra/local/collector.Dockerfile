# Platform collectors for the local stand. Telegram runs in public_web mode and
# Rutube on the public API, so neither needs a session or a token.
FROM python:3.13-slim
RUN apt-get update && apt-get install -y --no-install-recommends git \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt ./
# BeautifulSoup parses the Telegram embed pages with lxml.
RUN pip install --no-cache-dir -r requirements.txt lxml==6.0.2
COPY app ./app
COPY collector_target ./collector_target
# collector_target/legacy_csv.py reads the shared reverse-snapshot envelope.
COPY migration/__init__.py migration/reverse_sync_format.py ./migration/
ENV PYTHONUNBUFFERED=1 TZ=UTC
ENTRYPOINT ["python", "-m", "collector_target"]
