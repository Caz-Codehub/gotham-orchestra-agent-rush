FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
# ca.crt is optional (only needed behind a TLS-inspecting proxy); the wildcard keeps the build valid without it.
COPY requirements.txt ca.crt* ./
RUN if [ -s ca.crt ]; then export PIP_CERT=/app/ca.crt; fi; pip install --no-cache-dir -r requirements.txt
COPY gotham ./gotham
COPY rules ./rules
COPY docker ./docker
RUN useradd -r -u 10001 gotham && mkdir -p /data /audit && chown gotham /data /audit && chmod 700 /audit
USER 10001
ENV GOTHAM_DATA_DIR=/data GOTHAM_AUDIT_DB=/audit/specter.sqlite3 GOTHAM_SPECTER_DB=/tmp/gotham-specter.sqlite3 GOTHAM_LEDGER_PATH=/tmp/gotham-missions.sqlite3
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/api/v4/health',timeout=3)"
CMD ["uvicorn", "gotham.app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
