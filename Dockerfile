FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8080

WORKDIR /workspace

RUN addgroup --system app && adduser --system --ingroup app app

COPY services/api/requirements.txt services/api/requirements.txt
RUN python -m pip install --upgrade pip \
    && python -m pip install -r services/api/requirements.txt

COPY configs configs
COPY services/api/app services/api/app
COPY services/api/scripts services/api/scripts

WORKDIR /workspace/services/api

USER app

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080}"]
