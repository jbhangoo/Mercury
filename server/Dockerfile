# Minimal container image for the Mercury server.
# Build:  docker build -t server-img .
# Run:    docker run -p 8000:8000 server-img

FROM python:3.13-slim

WORKDIR /app

# Install deps first so this layer is cached unless requirements.txt changes
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Make sure the prod launcher is executable inside the image even if git
# or the zip transfer dropped the +x bit
RUN chmod +x run-prod.sh

EXPOSE 8000

# Same Uvicorn launcher used to test production behavior locally
CMD ["./run-prod.sh"]
