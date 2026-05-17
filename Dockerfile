FROM python:3.13-slim

# Non-root user for sandbox isolation
RUN groupadd -r helix && useradd -r -g helix -d /home/helix -m helix

# Install helix-mini
WORKDIR /app
COPY pyproject.toml .
COPY src/ src/
RUN pip install --no-cache-dir . && \
    rm -rf /root/.cache

# Create helix home owned by sandbox user
RUN mkdir -p /home/helix/.helix-mini && \
    chown -R helix:helix /home/helix

# Source folders will be mounted read-only at /input
# Atlas output will be mounted at /home/helix/.helix-mini
RUN mkdir -p /input && chown helix:helix /input

USER helix
ENV HELIX_MINI_HOME=/home/helix/.helix-mini

ENTRYPOINT ["helix-mini"]
