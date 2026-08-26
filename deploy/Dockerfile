# weewx-evo itself has no dependencies outside the standard library. That is
# worth keeping: a weather station runs for years without being touched, and
# every dependency is a thing that can stop working while nobody is looking.
#
# One feed is the exception, and it has to be. The Cheetah feed runs an
# existing WeeWX skin, unchanged -- Cheetah *is* what such a skin is written
# in, so there is no version of that feed without it. It is imported where it
# is used, so a station that runs no skin never loads it, and the core stays
# what it says it is.
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=Europe/Berlin

# The archive day boundary is local time, so the container's timezone is part
# of the data, not a display setting.
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

# CT3 is the maintained Cheetah, and the one WeeWX 5 depends on. Pinned,
# because a template language that changes under a skin is exactly the fault
# this project exists to avoid.
RUN pip install --no-cache-dir "CT3==3.4.0.post5"

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
