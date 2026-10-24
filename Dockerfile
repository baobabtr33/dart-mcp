FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy DART_MCP_CACHE_DIR=/data
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
RUN uv sync --frozen --no-dev
RUN useradd --create-home app && mkdir -p /data && chown app /data
USER app
VOLUME /data
EXPOSE 8000
CMD ["uv", "run", "--no-sync", "dart-mcp", "--transport", "streamable-http", "--host", "0.0.0.0", "--port", "8000"]
