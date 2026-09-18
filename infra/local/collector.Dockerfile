# Platform collectors for the local stand. Telegram runs in public_web mode and
# Rutube on the public API, so neither needs a session or a token.
#
# PyMax собирается отдельным слоем из закреплённого коммита: зависимость из git
# несовместима с проверкой хешей, и смешивать её с остальными нельзя.
FROM python:3.13-slim@sha256:9d2e5553305c7c7b0097999bb17187c69b921ccd6bc9d40e4bb5ebe652c00285 AS pymax
RUN apt-get update && apt-get install -y --no-install-recommends git \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /build
COPY requirements/tooling.lock requirements/pymax.txt ./requirements/
RUN pip install --require-hashes --no-deps --upgrade -r requirements/tooling.lock \
 && pip wheel --no-deps --wheel-dir /wheels -r requirements/pymax.txt \
 && sha256sum /wheels/*.whl

FROM python:3.13-slim@sha256:9d2e5553305c7c7b0097999bb17187c69b921ccd6bc9d40e4bb5ebe652c00285
WORKDIR /app
RUN apt-get update \
 && apt-get upgrade -y --no-install-recommends \
 && rm -rf /var/lib/apt/lists/*
COPY requirements/tooling.lock requirements/collector.lock ./requirements/
RUN pip install --require-hashes --no-deps --upgrade -r requirements/tooling.lock \
 && pip install --require-hashes --no-deps --no-build-isolation -r requirements/collector.lock
COPY --from=pymax /wheels /wheels
RUN pip install --no-deps --no-index --find-links /wheels maxapi-python \
 && rm -rf /wheels \
 && python -m pip uninstall --yes setuptools wheel \
 && python -m pip uninstall --yes pip
COPY collector_runtime ./collector_runtime
COPY collector_target ./collector_target
RUN useradd --system --uid 10002 --user-group m-ranked-collector \
 && install -d -o 10002 -g 10002 -m 0750 /state
USER 10002:10002
ENV PYTHONUNBUFFERED=1 TZ=UTC
ENTRYPOINT ["python", "-m", "collector_target"]
