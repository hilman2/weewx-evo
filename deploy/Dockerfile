# weewx-evo has no dependencies outside the standard library, so there is
# nothing to install and nothing to pin. That is worth keeping: a weather
# station runs for years without being touched, and every dependency is a
# thing that can stop working while nobody is looking.
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=Europe/Berlin

# The archive day boundary is local time, so the container's timezone is part
# of the data, not a display setting.
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

WORKDIR /app
# The bundled drivers come with the source; weewx-ecowitt is one of them.
COPY src/ /app/src/
COPY tools/ /app/tools/
ENV PYTHONPATH=/app/src

# Unprivileged: this process is reachable from the internet through Caddy, and
# it has no reason to own the files it writes beyond writing them.
RUN useradd --system --uid 1001 --create-home weewx && \
    mkdir -p /data && chown weewx:weewx /data
USER weewx
VOLUME /data

EXPOSE 8000
ENTRYPOINT ["python", "-m", "weewx_evo.cli"]
CMD ["serve"]
