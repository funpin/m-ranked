FROM python:3.13-slim-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt ./
RUN --mount=type=cache,target=/root/.cache/pip pip install -r requirements.txt
COPY app ./app
COPY migration ./migration
COPY operations ./operations
COPY backend/src/main/resources/db/migration ./backend/src/main/resources/db/migration
COPY infra/local/seed.py ./infra/local/seed.py
COPY infra/local/progress.py ./infra/local/progress.py
COPY infra/local/finalize_partial.py ./infra/local/finalize_partial.py
RUN find app migration operations backend infra -type f -print0 | sort -z | xargs -0 sha256sum > SHA256SUMS
ENV PYTHONUNBUFFERED=1
CMD ["python", "infra/local/seed.py"]
