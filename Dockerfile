FROM python:3.12-slim

WORKDIR /app

# Install dependencies
COPY pyproject.toml .
RUN pip install --no-cache-dir .

# Copy application
COPY penny/ ./penny/
COPY static/ ./static/

# Create data directory
RUN mkdir -p /app/data

# Run the app
EXPOSE 8000
CMD ["uvicorn", "penny.main:app", "--host", "0.0.0.0", "--port", "8000"]
