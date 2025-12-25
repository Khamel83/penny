FROM python:3.12-slim

WORKDIR /app

# Install system dependencies including Node.js for Claude Code runtime
RUN apt-get update && apt-get install -y \
    curl \
    gnupg \
    openssh-client \
    procps \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

# Install Claude Code CLI globally
RUN npm install -g @anthropic-ai/claude-code

# Install Python dependencies
RUN pip install --no-cache-dir \
    fastapi>=0.109.0 \
    uvicorn[standard]>=0.27.0 \
    python-multipart>=0.0.6 \
    aiosqlite>=0.19.0 \
    pydantic>=2.5.0 \
    requests>=2.31.0 \
    httpx>=0.27.0 \
    gkeepapi>=0.16.0 \
    claude-agent-sdk>=0.1.0 \
    dateparser>=1.1.0

# Create non-root user for Claude CLI (refuses to run as root)
# Using UID/GID 1001 to match homelab service user for volume compatibility
RUN groupadd -g 1001 penny && useradd -u 1001 -g penny -m penny

# Copy application
COPY penny/ ./penny/
COPY static/ ./static/

# Create data and builds directories with proper ownership
RUN mkdir -p /app/data /app/builds && chown -R penny:penny /app

# Switch to non-root user
USER penny

# Run the app
EXPOSE 8000
CMD ["uvicorn", "penny.main:app", "--host", "0.0.0.0", "--port", "8000"]
