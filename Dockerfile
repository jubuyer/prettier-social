FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ ./src

# Ensure Python doesn't buffer stdout (useful for logs)
ENV PYTHONUNBUFFERED=1

# Run the app
CMD ["python", "src/main.py"]
