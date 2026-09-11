FROM python:3.13-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends git \
 && rm -rf /var/lib/apt/lists/*
COPY requirements.txt ./
RUN --mount=type=cache,target=/root/.cache/pip pip install -r requirements.txt
COPY api ./api
COPY contracts ./contracts
ENV PYTHONUNBUFFERED=1 TZ=UTC
ENTRYPOINT ["python", "-m", "api"]
