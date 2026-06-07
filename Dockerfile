FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

WORKDIR /app

COPY bot/requirements.txt /app/requirements.txt

RUN pip install --no-cache-dir -r requirements.txt \
    && python -m playwright install --with-deps chromium

COPY bot/ /app/

CMD ["python", "main.py"]
