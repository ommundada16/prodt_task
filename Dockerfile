FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

EXPOSE 8000 9001 9002

CMD ["uvicorn", "app.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
