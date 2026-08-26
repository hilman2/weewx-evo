# weewx-evo itself has no dependencies outside the standard library. That is
# worth keeping: a weather station runs for years without being touched, and
# every dependency is a thing that can stop working while nobody is looking.
#
# Three exceptions, all of them optional and all imported where they are
# used, so a station that wants none of them loads none of them and the core
# stays what it says it is:
#
#   CT3      the Cheetah feed runs an existing WeeWX skin unchanged, and
#            Cheetah *is* what such a skin is written in
#   Pillow   the image feed draws PNGs, and drawing needs something to draw
#   ephem    the moon. Sunrise and sunset are worked out here and measured
#            against pyephem at 37 seconds, which is why they are; the moon's
#            orbit is tilted, elliptical and pulled about, and approximating
#            that in thirty lines is how an almanac comes to be quietly
#            wrong. Without it `$almanac.hasExtras` is false and a skin
#            prints its own "install ephem" line, which is honest and is
#            also a page with a hole in it.
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=Europe/Berlin

# The archive day boundary is local time, so the container's timezone is part
# of the data, not a display setting.
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

# CT3 is the maintained Cheetah, and the one WeeWX 5 depends on. Pillow is
# what WeeWX draws with too. Both pinned: a template language or a rasteriser
# that changes under a running station is exactly the fault this project
# exists to avoid.
RUN pip install --no-cache-dir "CT3==3.4.0.post5" "Pillow==12.3.0"         "ephem==4.2.1"

# A typeface. Without one Pillow draws every label at a single fixed size, so
# a chart rendered at twice the pixels comes out with type half the height it
# should -- which looks like a decision somebody made rather than a missing
# package. About a megabyte.
RUN apt-get update && apt-get install -y --no-install-recommends         fonts-dejavu-core     && rm -rf /var/lib/apt/lists/*

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
