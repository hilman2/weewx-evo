# The test image. Everything every test in this repository can ask for, so
# that a run is the same run on any machine and nothing is quietly skipped.
#
# This is the opposite of `deploy/Dockerfile` on purpose. That one is
# deliberately bare -- weewx-evo has no dependencies outside the standard
# library, and a station that runs untouched for years is better off with
# nothing extra in it. This one has WeeWX, pyephem, an FTP server and a PHP,
# because a test that cannot compare against the thing it was transcribed
# from is not a test, it is an opinion.
#
# What is here and why:
#
#   weewx        six of these run our arithmetic and WeeWX's side by side.
#                Without it, `units`, `series` and `tags` skip -- which is
#                exactly the coverage that matters most.
#   ephem        sun, moon and planets are measured against it. Same reason.
#   CT3, Pillow  a skin is written in Cheetah; a chart is drawn with Pillow.
#   pyftpdlib    the FTP export is tested against a real FTP server.
#   php-cli      `live.php` runs on somebody else's web host. "It looked
#                fine to me" is not a test of it.
#   ruff         it finds the kind of fault no test finds: a call in a
#                branch nothing walks through. Pinned to the version
#                `required-version` in pyproject.toml asks for: the rule list
#                there names rules that older ruffs have never heard of, and
#                the failure then reads as a broken config rather than an old
#                tool.
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=Europe/Berlin

# The day tables are keyed on local midnight. Read in another zone, the
# comparison pairs one day with another -- that produced 27 failures once and
# not one of them was real.
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

RUN apt-get update && apt-get install -y --no-install-recommends \
        fonts-dejavu-core \
        php-cli \
        rsync \
        tzdata \
        nodejs npm \
    && rm -rf /var/lib/apt/lists/*

# A DOM to run the skin's own JavaScript in. The fault that put this here: the
# live badges were painted into the element a MutationObserver was watching,
# so every paint was a mutation and every mutation a paint. The page rendered
# perfectly, every test passed, and the tab stopped responding a second after
# loading. Nothing that reads HTML as text can find that. It has to run.
RUN npm install --global --no-fund --no-audit jsdom@26.1.0
ENV NODE_PATH=/usr/local/lib/node_modules

# WeeWX brings CT3 and configobj with it, which is the point: the Cheetah the
# comparison runs under is then the same one WeeWX itself uses.
#
# Pinned, all of it. A comparison against a moving target tells you the target
# moved, on a morning when you were changing something else.
RUN pip install --no-cache-dir \
        "weewx==5.1.0" \
        "Pillow==12.3.0" \
        "ephem==4.2" \
        "pyftpdlib==2.0.1" \
        "pytest==8.4.2" \
        "ruff==0.16.4"

# WeeWX installs as a package, so it imports without a path. Ours is a
# checkout, mounted at run time.
WORKDIR /repo
ENV PYTHONPATH=/repo/src

# Not root. A test that only passes as root has found a permission bug and
# reported it as a pass.
RUN useradd --system --uid 1001 --create-home runner
USER runner

ENTRYPOINT ["python", "tools/runtests.py"]
