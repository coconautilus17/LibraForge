FROM sandreas/m4b-tool@sha256:3154399019ed6a2d26fd477f71a1367e4c60e605d0188699028ad3444afd3c70

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    SCRIPTS_DIR=/app/scripts \
    REPORTS_DIR=/app/reports \
    PATH=/opt/venv/bin:$PATH

RUN apk upgrade --no-cache \
    && apk add --no-cache ffmpeg python3 py3-pip \
    && python3 -m venv /opt/venv

WORKDIR /app
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r /app/requirements.txt

COPY app /app/app
COPY scripts /app/scripts
COPY config /app/config
# Chapter Forge's Hybrid backend loads this script even when the optional
# faster-whisper/tqdm stack (requirements-chaptering.txt) isn't installed --
# without it, the failure is a confusing "script not found" instead of a
# clear "chaptering dependencies aren't installed" message. It's 64KB, not
# worth omitting from this lean image just to save the copy.
COPY tools /app/tools

# Create the writable mount points and make them world-writable so the image
# works for any runtime UID/GID. Named volumes inherit these perms at first
# creation, so compose/`docker run` with `--user` (or the default 1000) can
# write reports, auth files, and UI config overrides without a host chown.
RUN mkdir -p /app/reports /auth \
    && chmod -R 0777 /app/reports /auth /app/config

# Default to a non-root user so a bare `docker run` (no --user) does not write
# root-owned files into a mounted library. Compose overrides this with the host
# UID/GID.
USER 1000:1000

EXPOSE 5056
ENTRYPOINT []
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "5056"]
