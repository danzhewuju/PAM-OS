ARG PYTHON_BASE_IMAGE=m.daocloud.io/docker.io/library/python:3.12-slim
FROM ${PYTHON_BASE_IMAGE}

ARG PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PAM_OS_DB=/data/memory.sqlite3 \
    PAM_OS_HOST=0.0.0.0 \
    PAM_OS_PORT=8765

WORKDIR /app

RUN adduser --disabled-password --gecos "" --home /home/pam pam \
    && mkdir -p /data \
    && chown -R pam:pam /data

COPY pyproject.toml README.md LICENSE ./
COPY src ./src

RUN pip install --no-cache-dir --index-url "${PIP_INDEX_URL}" ".[api]"

USER pam

EXPOSE 8765
VOLUME ["/data"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import base64, os, urllib.request; port=os.environ.get('PAM_OS_PORT','8765'); req=urllib.request.Request(f'http://127.0.0.1:{port}/health'); enabled=os.environ.get('PAM_OS_AUTH_ENABLED','').strip().lower() in {'1','true','yes','on'}; user=os.environ.get('PAM_OS_AUTH_USERNAME',''); password=os.environ.get('PAM_OS_AUTH_PASSWORD',''); req.add_header('Authorization', 'Basic ' + base64.b64encode(f'{user}:{password}'.encode()).decode()) if enabled else None; urllib.request.urlopen(req, timeout=3).read()" || exit 1

CMD ["sh", "-c", "memory serve --host \"${PAM_OS_HOST:-0.0.0.0}\" --port \"${PAM_OS_PORT:-8765}\""]
