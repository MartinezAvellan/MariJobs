FROM --platform=$BUILDPLATFORM python:3.12-slim AS builder

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir --target=/deps -r requirements.txt

COPY src/ src/
COPY config/ config/

FROM python:3.12-slim

WORKDIR /app

COPY --from=builder /deps /deps
COPY --from=builder /app .

ENV PYTHONPATH=/deps

CMD ["python", "-m", "src.main"]
