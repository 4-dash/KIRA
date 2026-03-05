FROM python:3.11-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1

# Install system dependencies for shapely (libgeos) and lxml (gcc/libxml)
RUN apt-get update && apt-get install -y \
    libgeos-dev \
    gcc \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy and install requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy everything from the Ingester folder into the container
COPY . .

CMD ["sleep", "infinity"]