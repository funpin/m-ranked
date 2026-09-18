FROM python:3.13-slim@sha256:9d2e5553305c7c7b0097999bb17187c69b921ccd6bc9d40e4bb5ebe652c00285
WORKDIR /app
RUN apt-get update \
 && apt-get upgrade -y --no-install-recommends \
 && rm -rf /var/lib/apt/lists/*
COPY requirements/tooling.lock requirements/anomaly.lock ./requirements/
RUN pip install --require-hashes --no-deps --upgrade -r requirements/tooling.lock \
 && pip install --require-hashes --no-deps --only-binary=:all: -r requirements/anomaly.lock \
 && python -m pip uninstall --yes setuptools wheel \
 && python -m pip uninstall --yes pip
COPY anomaly_analysis ./anomaly_analysis
RUN useradd --system --uid 10003 --user-group m-ranked-anomaly
USER 10003:10003
ENV PYTHONUNBUFFERED=1
ENTRYPOINT ["python", "-m", "anomaly_analysis"]
