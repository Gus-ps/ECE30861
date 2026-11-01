FROM python:3.13-slim
WORKDIR /service
ADD https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem /service/global-bundle.pem
RUN chmod 644 /service/global-bundle.pem
ENV DB_SSLROOTCERT=/service/global-bundle.pem
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py database.py contracts.py validity_check.py test_interface.py remediation.py phase4_store.py phase4_jobs.py phase4_service.py phase4_contracts.py service_worker.py service_errors.py package_checks.py ./
COPY accessibility_checker ./accessibility_checker
COPY static ./static
RUN useradd --create-home service && mkdir /service/data && chown service:service /service/data
USER service
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
