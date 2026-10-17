FROM python:3.13-slim
WORKDIR /service
ADD https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem /service/global-bundle.pem
RUN chmod 644 /service/global-bundle.pem
ENV DB_SSLROOTCERT=/service/global-bundle.pem
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py database.py validity_check.py ./
COPY static ./static
RUN useradd --create-home service && mkdir /service/data && chown service:service /service/data
USER service
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
