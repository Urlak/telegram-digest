# Use official Python 3.12 slim image for a smaller footprint
FROM python:3.12-slim

# Set working directory inside the container
WORKDIR /app

# Do not write .pyc files & do not buffer stdout (better for logging)
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Install project dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY src /app/src/

# We don't copy the data directory or .env file here 
# because they will be mounted globally safely via docker-compose

# The default command to start the bot
CMD ["python", "-m", "src.main"]
