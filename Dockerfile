# Use official lightweight Python image
FROM python:3.11-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV SECRET_KEY=c69fc621e47743c584ea00c3d51053bb09a2e6659f0f9b6e828453ea1a4155b2
ENV MYSQL_HOST=seg-dev.sreenidhi.edu.in
ENV MYSQL_USER=demo
ENV MYSQL_PASSWORD=Admin@321#
ENV MYSQL_DATABASE=seg_demo
ENV MYSQL_PORT=3306
ENV MYSQL_ENABLE_REMOTE=true


# Set working directory
WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy project files
COPY . .

# Create a non-privileged user and group
RUN groupadd -r appgroup && useradd -r -g appgroup -d /app -s /sbin/nologin appuser \
    && chown -R appuser:appgroup /app

# Switch to the non-privileged user
USER appuser

# Expose port
EXPOSE 5000

# Command to run the application using Gunicorn with multi-threaded workers
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "3", "--threads", "4", "--worker-class", "gthread", "--access-logfile", "-", "--error-logfile", "-", "--log-level", "info", "wsgi:application"]
