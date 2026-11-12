FROM python:3.12-alpine
COPY lab_target_app.py /app/app.py
COPY lab_canary.txt /app/canary.txt
COPY files /app/files
USER 65534:65534
EXPOSE 8080
CMD ["python","-B","/app/app.py"]
