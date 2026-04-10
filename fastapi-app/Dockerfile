# Build from repository root (pdf_pipeline_v2):
#   docker build -f fastapi-app/Dockerfile .
#
FROM python:3.12-slim-bookworm

WORKDIR /app
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY orchestrator.py config.py /app/
COPY agents /app/agents
COPY utils /app/utils
COPY fastapi-app /app/fastapi-app

RUN python -m playwright install chromium || true

WORKDIR /app/fastapi-app
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
