FROM python:3.9-slim

# Install system dependencies (FFmpeg is critical)
RUN apt-get update && apt-get install -y \
    ffmpeg \
    git \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements first to leverage cache
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir gunicorn
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application
COPY . .

# Create downloads directory with write permissions
RUN mkdir -p downloads && chmod 777 downloads

# Expose port (Render/Railway use env var PORT, but default 5000 is good for doc)
ENV PORT=5000
EXPOSE 5000

# Start command using Gunicorn
CMD ["sh", "-c", "gunicorn --bind 0.0.0.0:$PORT app:app"]
