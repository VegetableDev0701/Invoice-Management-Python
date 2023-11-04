# Use an official lightweight Python image.
# https://hub.docker.com/_/python
FROM python:3.10-slim-bookworm

# Set the working directory in the Docker image
WORKDIR /app

# Update and install necessary packages
RUN apt-get update && apt-get upgrade -y && apt-get install -y \
    libgl1-mesa-glx \
    libglib2.0-0 \
    --no-install-recommends && \
    apt-get install --only-upgrade -y openssl && \
    rm -rf /var/lib/apt/lists/*

# Install production dependencies.
COPY ./requirements.txt .
RUN pip install --no-cache-dir --upgrade -r requirements.txt

# Copy local code to the container image.
COPY . .
RUN chmod +x main.py

CMD ["/usr/local/bin/python", "main.py"]
