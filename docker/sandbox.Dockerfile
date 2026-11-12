FROM python:3.12-slim
COPY ca.crt /tmp/build-ca.crt
RUN if [ -s /tmp/build-ca.crt ]; then export PIP_CERT=/tmp/build-ca.crt; fi; \
    pip install --no-cache-dir pytest==8.3.4 && python -c "import pytest"
WORKDIR /work
