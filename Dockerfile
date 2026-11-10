FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY gotham ./gotham
COPY rules ./rules
COPY docker ./docker
RUN useradd -r -u 10001 gotham && mkdir -p /data && chown gotham /data
USER 10001
ENV GOTHAM_DATA_DIR=/data
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/api/v4/health',timeout=3)"
CMD ["uvicorn", "gotham.app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
