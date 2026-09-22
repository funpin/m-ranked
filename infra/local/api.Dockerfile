# База закреплена digest-ом: тег python:3.13-slim подвижен, digest — нет.
FROM python:3.13-slim@sha256:9d2e5553305c7c7b0097999bb17187c69b921ccd6bc9d40e4bb5ebe652c00285
WORKDIR /app
# Digest фиксирует исходный слой, а security-обновления Debian накатываются
# при сборке и попадают в аттестованный digest готового образа.
RUN apt-get update \
 && apt-get upgrade -y --no-install-recommends \
 && rm -rf /var/lib/apt/lists/*
# Сначала закрепляется сам инструмент установки: его загрузка — такая же
# граница поставки, как и загрузка зависимостей.
COPY requirements/tooling.lock requirements/api.lock ./requirements/
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --require-hashes --no-deps --upgrade -r requirements/tooling.lock \
 && pip install --require-hashes --no-deps --only-binary=:all: -r requirements/api.lock \
 && python -m pip uninstall --yes setuptools wheel \
 && python -m pip uninstall --yes pip
COPY api ./api
COPY contracts ./contracts
# Процесс не должен работать от root, а том со состоянием создаётся по правам
# каталога в образе.
RUN useradd --system --uid 10001 --user-group m-ranked-api \
 && install -d -o 10001 -g 10001 -m 0750 /state
USER 10001:10001
ENV PYTHONUNBUFFERED=1 TZ=UTC
ENTRYPOINT ["python", "-m", "api"]
