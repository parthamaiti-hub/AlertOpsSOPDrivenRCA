FROM python:3.12-slim

WORKDIR /app
RUN pip install uv

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY backend/ backend/
COPY data/ data/

EXPOSE 8000
CMD ["uv", "run", "python", "-m", "backend.main", "web"]
