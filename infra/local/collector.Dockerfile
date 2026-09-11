# Platform collectors for the local stand. Telegram runs in public_web mode and
# Rutube on the public API, so neither needs a session or a token.
FROM python:3.13-slim
RUN apt-get update && apt-get install -y --no-install-recommends git \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt ./
# BeautifulSoup parses the Telegram embed pages with lxml.
RUN pip install --no-cache-dir -r requirements.txt lxml==6.0.2
COPY collector_runtime ./collector_runtime
COPY collector_target ./collector_target
ENV PYTHONUNBUFFERED=1 TZ=UTC
ENTRYPOINT ["python", "-m", "collector_target"]
