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

# git is here to answer one question no other test can: what does a fresh
# clone actually get? `starter/plots.toml` was ignored by a pattern written for
# the installation's own file, and on a machine that has the file the wizard
# works perfectly. Only the index knows the difference.
RUN apt-get update && apt-get install -y --no-install-recommends \
        fonts-dejavu-core \
        git \
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
#
# Pinned is not the same as forgotten. This sat on 5.1.0 from the day the
# container was written while WeeWX went to 5.5, and the gap showed up by
# accident: the CWOP packet type compared clean in here and did not in a venv
# with the current release. Raise it deliberately, read what turns red, and
# decide about each one -- that is the whole value of comparing at all.
RUN pip install --no-cache-dir \
        "weewx==5.5.0" \
        "Pillow==12.3.0" \
        "ephem==4.2" \
        "pyftpdlib==2.0.1" \
        "pytest==8.4.2" \
        "ruff==0.16.4"

# The push protocols, which the core no longer ships. Installed the way an
# operator installs them, which is the point: before this they were imported
# out of the source tree, so nothing ever ran the entry point that a real
# installation depends on entirely.
#
# Pinned to commits for the same reason WeeWX is pinned to a version. And a
# test that needs one says so and skips where it is absent -- the core has to
# be testable with no driver at all, because that is what a fresh install is.
ARG PUSH_COMMON=52559665bb349e4cfa34d90745662b776fc0fd99
ARG ECOWITT=1e1ad54fb4ae1945da3c7a0b7b5ac7286dc84e01
ARG AMBIENT=69e0ce8a4df0c90a20f60efb6bd086a3d3ac9af5
ARG WUNDERGROUND=390a13402845924a38b321d9177b2bd6556303e7
ARG ACURITE=029cc9b35e97b2cd3e4b4b41e696d2775b8d3717
ARG LACROSSE=4ae4c03df5af3950256fd79808c07833ba85a92b
ARG WEATHERFLOW=e75158e51be8a476f4269ea896ded07273af83f0
RUN pip install --no-cache-dir --no-deps \
   "weewx-evo-push-common @ git+https://github.com/weewx-evo/weewx-evo-push-common@${PUSH_COMMON}" \
   "weewx-evo-ecowitt @ git+https://github.com/weewx-evo/weewx-evo-ecowitt@${ECOWITT}" \
   "weewx-evo-ambient @ git+https://github.com/weewx-evo/weewx-evo-ambient@${AMBIENT}" \
   "weewx-evo-wunderground @ git+https://github.com/weewx-evo/weewx-evo-wunderground@${WUNDERGROUND}" \
   "weewx-evo-acurite @ git+https://github.com/weewx-evo/weewx-evo-acurite@${ACURITE}" \
   "weewx-evo-lacrosse @ git+https://github.com/weewx-evo/weewx-evo-lacrosse@${LACROSSE}" \
   "weewx-evo-weatherflow @ git+https://github.com/weewx-evo/weewx-evo-weatherflow@${WEATHERFLOW}"

# weewx-sdr, one file, for `sdr_test.py`. It is not part of WeeWX and not
# pip-installable, so it comes down as the file it is -- which is also how
# somebody installs it. Pinned to a commit for the same reason everything
# else here is pinned: a test that compares against whatever was on a server
# this morning compares against a moving thing.
#
# Here rather than vendored in the repository because it is 166 KB of
# somebody else's driver, and the point of `weewxnames.py` is that we do not
# need a copy of one. The test skips where it is absent.
ARG SDR_COMMIT=e5f1f9915322fa6d1c25b4ff8e490b804cefeac1
RUN mkdir -p /opt/weewx-sdr && \
    python3 -c "import urllib.request as u, sys; \
      u.urlretrieve('https://raw.githubusercontent.com/matthewwall/\
weewx-sdr/${SDR_COMMIT}/bin/user/sdr.py', '/opt/weewx-sdr/sdr.py')" && \
    python3 -c "import ast; ast.parse(open('/opt/weewx-sdr/sdr.py').read())"
ENV WEEWX_SDR=/opt/weewx-sdr/sdr.py

# WeeWX installs as a package, so it imports without a path. Ours is a
# checkout, mounted at run time.
WORKDIR /repo
ENV PYTHONPATH=/repo/src

# Not root. A test that only passes as root has found a permission bug and
# reported it as a pass.
RUN useradd --system --uid 1001 --create-home runner
USER runner

ENTRYPOINT ["python", "tools/runtests.py"]
