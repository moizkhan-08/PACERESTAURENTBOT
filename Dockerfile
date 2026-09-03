FROM python:3.11-slim

# Non-root user for security
RUN useradd --create-home --uid 1000 appuser
WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .
RUN chown -R appuser:appuser /app
USER appuser

# Unbuffered output for Docker logs
ENV PYTHONUNBUFFERED=1

# Expose port 4433
EXPOSE 4433

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:4433/health')" || exit 1

# Run the FastAPI server
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "4433"]
