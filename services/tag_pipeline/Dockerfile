FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends fonts-courier-prime \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py .

ENTRYPOINT ["python", "/app/main.py"]
