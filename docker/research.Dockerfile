FROM python:3.12-slim
COPY ca.crt /tmp/build-ca.crt
RUN if [ -s /tmp/build-ca.crt ]; then export PIP_CERT=/tmp/build-ca.crt; fi; \
    pip install --no-cache-dir nbformat nbclient ipykernel numpy pandas scikit-learn matplotlib scipy \
    && python -c "import nbclient, numpy, pandas, sklearn"
WORKDIR /work
