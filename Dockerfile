# Multi-stage build: dependencies resolved with uv in the builder, runtime runs as a non-root user.
FROM python:3.12-slim AS builder
COPY --from=ghcr.io/astral-sh/uv:0.6 /uv /usr/local/bin/uv
WORKDIR /app
ENV UV_PROJECT_ENVIRONMENT=/app/.venv UV_COMPILE_BYTECODE=1
COPY pyproject.toml README.md ./
COPY playbook ./playbook
COPY fakes ./fakes
RUN uv sync --no-dev --no-editable

FROM python:3.12-slim
RUN useradd --system --create-home --uid 10001 playbook
WORKDIR /app
COPY --from=builder /app/.venv /app/.venv
COPY procedures ./procedures
ENV PATH="/app/.venv/bin:$PATH" PLAYBOOK_RUNS_DIR=/home/playbook/runs
USER playbook
EXPOSE 8801 8802 8803
ENTRYPOINT ["playbook"]
CMD ["--help"]
