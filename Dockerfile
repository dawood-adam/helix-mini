FROM python:3.13-slim

# Non-root user for isolation
RUN groupadd -r helix && useradd -r -g helix -d /home/helix -m helix

WORKDIR /app
COPY pyproject.toml .
COPY src/ src/
# CLI mode is dependency-light; add [sdk] if you need the LangGraph/API path.
RUN pip install --no-cache-dir . && rm -rf /root/.cache

# Project dir (Atlas + .helix live here by default) — mount your project over it
RUN mkdir -p /work && chown -R helix:helix /work /home/helix
USER helix
ENV HELIX_HOME=/work
WORKDIR /work

ENTRYPOINT ["helix"]
