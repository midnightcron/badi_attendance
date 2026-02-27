FROM python:3.11-slim

WORKDIR /app

# Install dependencies first (layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY main.py websocket_handler.py table_writer.py blob_writer.py ./

# Non-root user for security
RUN useradd --create-home appuser
USER appuser

CMD ["python", "-u", "main.py"]
