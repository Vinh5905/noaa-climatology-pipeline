FROM python:3.11-slim

WORKDIR /app

RUN pip install uv

COPY pyproject.toml uv.lock* ./
RUN uv sync --no-install-project

COPY . .
RUN uv sync

ENV PYTHONUNBUFFERED=1

ENTRYPOINT ["uv", "run", "python"]
