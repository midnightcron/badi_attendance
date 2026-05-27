FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY export.py .

RUN useradd --create-home appuser
USER appuser

CMD ["python", "-u", "export.py"]
