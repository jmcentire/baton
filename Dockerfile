# Baton deployment image for the Exemplar stack control/smoke node.

FROM python:3.12-slim AS builder

WORKDIR /build

COPY pyproject.toml README.md ./
COPY src ./src

RUN pip install --upgrade pip wheel \
    && pip wheel --wheel-dir /wheels .

FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    BATON_HOST=0.0.0.0 \
    BATON_PORT=9900

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates tini \
    && rm -rf /var/lib/apt/lists/* \
    && useradd -r -u 1000 -m -d /home/baton baton \
    && mkdir -p /app/.baton \
    && chown -R baton:baton /app

COPY --from=builder /wheels /wheels
RUN pip install --no-cache-dir /wheels/*.whl \
    && rm -rf /wheels

COPY baton.yaml ./baton.yaml
COPY configs ./configs

USER baton

EXPOSE 9900

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["sh", "-c", "baton dashboard --serve --host ${BATON_HOST} --port ${BATON_PORT} --dir /app"]
