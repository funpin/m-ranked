FROM python:3.13-slim
WORKDIR /app
RUN pip install --no-cache-dir "psycopg[binary]==3.3.5"
COPY anomaly_analysis ./anomaly_analysis
ENV PYTHONUNBUFFERED=1
ENTRYPOINT ["python", "-m", "anomaly_analysis"]
