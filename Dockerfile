FROM python:3.12-slim

WORKDIR /app

# Install curl for health checks
RUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*

# Install dependencies directly
RUN pip install --no-cache-dir \
    fastapi>=0.109.0 \
    uvicorn[standard]>=0.27.0 \
    python-multipart>=0.0.6 \
    aiosqlite>=0.19.0 \
    pydantic>=2.5.0

# Copy application
COPY penny/ ./penny/
COPY static/ ./static/

# Create data directory
RUN mkdir -p /app/data

# Run the app
EXPOSE 8000
CMD ["uvicorn", "penny.main:app", "--host", "0.0.0.0", "--port", "8000"]
