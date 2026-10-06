# syntax=docker/dockerfile:1
FROM python:3.11-alpine

RUN apk add --no-cache \
    tesseract-ocr \
    tesseract-ocr-fra \
    libjpeg-turbo-dev \
    zlib-dev \
    build-base \
    linux-headers \
    sqlite-dev \
    libffi-dev

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

ENV GRAVITY_STORAGE_PATH=/app/nas_storage
ENV PYTHONUNBUFFERED=1
EXPOSE 8000
CMD ["python", "main.py"]
