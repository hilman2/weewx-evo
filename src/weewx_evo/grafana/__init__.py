"""Grafana, provisioned out of what is already configured.

Nothing here is a second set of settings. The InfluxDB uploads already say
where the server is, which bucket, which measurement, which units and what
each archive is called -- so a datasource is a restatement of one, and asking
for the address again is asking somebody to type it accurately twice. Same
reasoning as the live push: the export already knew everything, so nothing had
to be set up.

**Generated, never drawn by hand.** A dashboard checked into the repository is
wrong the first time somebody adds a sensor, and stale for ever after that.
These come out of `plots.toml`, the archive's own schema and `units`, which
means a station with a soil probe and four extra thermometers gets panels for
them without anybody knowing they exist.

    weewx-evo grafana provision --out /data/grafana

writes, in the shape Grafana's file provisioning expects:

    datasources/weewx-evo.yaml    one per InfluxDB server, not per archive
    dashboards/weewx-evo.yaml     the provider
    dashboards/*.json             overview, locations, charts, operations

**One datasource per server, not per archive.** Five archives writing into one
bucket are five `location` tags, and that is the arrangement that lets a single
query draw all five. Grouping them here is what makes the difference visible:
uploads pointing at the same bucket become one datasource, and their locations
become the list a dashboard variable offers.

**Grafana reads; the upload writes.** They want different tokens, and the one
in the configuration file has write permission on the bucket. It is used when
nothing else is given, because a provisioning run that produces something that
does not work is worth less than one that says what it did -- but it is said,
every time, because a read-only token is thirty seconds of work and this file
ends up in a container somebody else may look inside.
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .. import units
from .words import Words

log = logging.getLogger(__name__)

#: Grafana's own dashboard schema version. 39 is what Grafana 10.2 and every
#: version since reads without migrating anything on load.
SCHEMA_VERSION = 39

#: Where the compose file mounts the dashboards inside the container. Written
#: into the provider file, so the two cannot drift apart.
CONTAINER_DASHBOARDS = "/etc/grafana/provisioning/dashboards"


@dataclass
class Server:
    """One InfluxDB, with the locations that write into it."""

    url: str
    bucket: str
    org: str = ""
    token: str = ""
    measurement: str = "weather"
    system: int = units.METRICWX
    api: str = "v2"
    #: The `location` tag of every upload pointing here, in configuration
    #: order. The dashboards offer them as a variable; the data decides what
    #: is actually there, so a station added later appears without a rerun.
    locations: list[str] = field(default_factory=list)
    #: The uploads this was built from, for the report.
    uploads: list[str] = field(default_factory=list)
    #: The station's language. Carried on the server rather than passed to
    #: every function that writes a word, because that is what a server
    #: already is here: the context a panel is built against.
    words: Words = field(default_factory=Words)

    @property
    def uid(self) -> str:
        """A stable identifier. Stable is the requirement, not pretty.

        A dashboard refers to its datasource by uid, so one that changes
        between runs breaks every panel that was provisioned before it.
        """
        safe = "".join(c if c.isalnum() else "-" for c in
                       f"{self.url}-{self.bucket}".lower())
        return f"weewx-evo-{safe}".strip("-")[:40]

    @property
    def name(self) -> str:
        return f"weewx-evo ({self.bucket})"

    def reference(self) -> dict:
        return {"type": "influxdb", "uid": self.uid}


def servers_from(uploads: dict[str, dict],
                 language: Any = None) -> list[Server]:
    """The InfluxDB servers among the configured uploads.

    Grouped by where they point. Two uploads writing different archives into
    one bucket are one server with two locations -- which is the whole shape
    the comparison dashboards are built on.
    """
    found: dict[tuple, Server] = {}
    for name, settings in sorted(uploads.items()):
        if str(settings.get("kind", "")).strip() != "influx":
            continue
        url = str(settings.get("url") or "").strip().rstrip("/")
        bucket = str(settings.get("bucket") or "").strip()
        if not url or not bucket:
            log.warning("the upload %r has no address or bucket; skipping it",
                        name)
            continue
        measurement = str(settings.get("measurement") or "weather").strip()
        key = (url, str(settings.get("org") or ""), bucket, measurement)
        server = found.get(key)
        if server is None:
            system = {"us": units.US, "metric": units.METRIC,
                      "metricwx": units.METRICWX}.get(
                          str(settings.get("unit_system") or "metricwx").lower(),
                          units.METRICWX)
            server = Server(url=url, bucket=bucket,
                            org=str(settings.get("org") or ""),
                            token=str(settings.get("token") or ""),
                            measurement=measurement, system=system,
                            api=str(settings.get("api") or "v2"),
                            words=Words(language))
            found[key] = server
        location = str(settings.get("location") or "").strip()
        if location and location not in server.locations:
            server.locations.append(location)
        server.uploads.append(name)
    return list(found.values())


# ---------------------------------------------------------------------------
# The files.
# ---------------------------------------------------------------------------

def datasource_yaml(servers: list[Server], read_token: str = "") -> str:
    """The datasource provisioning file.

    Hand-written YAML rather than a library: this is four keys deep, the core
    has no YAML writer, and adding a dependency for one file that never grows
    is the trade nothing here makes.
    """
    lines = [
        "# Written by `weewx-evo grafana provision`. Edits are lost on the",
        "# next run -- change the InfluxDB upload on the settings page.",
        "apiVersion: 1",
        "",
        "datasources:",
    ]
    for server in servers:
        token = read_token or server.token
        lines += [
            f"  - name: {_yaml(server.name)}",
            f"    uid: {server.uid}",
            "    type: influxdb",
            "    access: proxy",
            f"    url: {_yaml(server.url)}",
            # Flux, not InfluxQL: an InfluxDB 2 bucket needs a DBRP mapping
            # before InfluxQL can see it, and that missing step reports itself
            # as "no measurements found".
            "    jsonData:",
            "      version: Flux",
            f"      organization: {_yaml(server.org)}",
            f"      defaultBucket: {_yaml(server.bucket)}",
            "      httpMode: POST",
            "    secureJsonData:",
            f"      token: {_yaml(token)}",
            "    isDefault: " + ("true" if server is servers[0] else "false"),
            "    editable: false",
            "",
        ]
    return "\n".join(lines)


def provider_yaml(folder: str = "weewx-evo") -> str:
    """Tells Grafana where the dashboard files are."""
    return "\n".join([
        "# Written by `weewx-evo grafana provision`.",
        "apiVersion: 1",
        "",
        "providers:",
        "  - name: weewx-evo",
        "    type: file",
        f"    folder: {_yaml(folder)}",
        # Without this a dashboard deleted in the browser comes back on the
        # next Grafana restart and looks like a bug in Grafana.
        "    disableDeletion: false",
        "    allowUiUpdates: true",
        "    updateIntervalSeconds: 60",
        "    options:",
        f"      path: {CONTAINER_DASHBOARDS}",
        "      foldersFromFilesStructure: false",
        "",
    ])


def _yaml(value: str) -> str:
    """One scalar, quoted so that a password with a colon in it survives."""
    return '"' + str(value).replace("\\", "\\\\").replace('"', '\\"') + '"'


@dataclass
class Written:
    """What a provisioning run did, so the command can report it."""

    files: list[Path] = field(default_factory=list)
    servers: int = 0
    panels: int = 0
    icons: int = 0
    notes: list[str] = field(default_factory=list)

    def summary(self) -> str:
        said = (f"{len(self.files)} files, {self.servers} datasource(s), "
                f"{self.panels} panels")
        return said + (f", {self.icons} icons" if self.icons else "")


def provision(out: str | Path, uploads: dict[str, dict], plots: Any,
              archive: str | Path | None = None, read_token: str = "",
              language: Any = None, forecasts: bool = False) -> Written:
    """Write everything Grafana needs into `out`.

    Nothing is started and nothing is asked of Grafana: these are files, and
    Grafana reads them when it starts. A provisioning tool that talked to a
    running Grafana would have opinions about how Grafana is supervised, and
    that is the operator's business -- the same line `adminsetup.py` draws.
    """
    from . import dashboards as build
    from . import query_influx as flux

    report = Written()
    servers = servers_from(uploads, language)
    report.servers = len(servers)
    if not servers:
        report.notes.append(
            "No InfluxDB upload is configured, so there is nothing to point "
            "Grafana at. Add one on the publishing page first.")
        return report

    intervals = flux.intervals_in(archive) if archive else []
    weight = len(intervals) > 1
    if weight:
        report.notes.append(
            f"The archive has more than one interval ({', '.join(str(i) for i in intervals)} "
            f"minutes), so averages are weighted by it -- the same way "
            f"aggregate.py does. Extremes are unaffected.")
    elif archive and not intervals:
        report.notes.append(
            f"Could not read the archive intervals from {archive}; averages "
            f"are unweighted, which is right for a database whose interval "
            f"never changed.")

    # Absolute, so what is reported is what a compose file has to mount. A
    # relative path printed here is resolved against whatever directory the
    # reader happens to be in next.
    out = Path(out).resolve()
    (out / "datasources").mkdir(parents=True, exist_ok=True)
    (out / "dashboards").mkdir(parents=True, exist_ok=True)

    if not read_token:
        report.notes.append(
            "Grafana is being given the upload's own token, which can write "
            "to the bucket. It only needs to read. Pass --read-token with a "
            "read-only one.")

    path = out / "datasources" / "weewx-evo.yaml"
    _write(path, datasource_yaml(servers, read_token), secret=True)
    report.files.append(path)

    path = out / "dashboards" / "weewx-evo.yaml"
    _write(path, provider_yaml())
    report.files.append(path)

    if forecasts:
        # Grafana serves these from its own `public/`, and it cannot see into
        # our container -- so the files go where the compose file mounts
        # them. Without that mount the panel shows a broken image, which says
        # what to fix; with a mapping to a file that is not there it would
        # show nothing at all.
        from . import icons as weather_icons

        made = weather_icons.written(out / "icons")
        report.icons = len(made)
        report.notes.append(
            f"{len(made)} weather icons written to {out / 'icons'}. Mount "
            f"that at /usr/share/grafana/public/img/weewx-evo, or the "
            f"forecast table draws broken images.")

    for server in servers:
        for name, board in build.all_of(server, plots, weight,
                                        forecasts).items():
            path = out / "dashboards" / f"{name}.json"
            _write(path, json.dumps(board, indent=2, sort_keys=False) + "\n")
            report.files.append(path)
            report.panels += len(board.get("panels", []))

    return report


def _write(path: Path, text: str, secret: bool = False) -> None:
    """Written beside and renamed, so a Grafana reading it never sees half.

    Grafana rescans this directory every minute, and it does not wait for a
    writer -- a dashboard caught mid-write is a parse error in its log and an
    empty folder in the browser.
    """
    temporary = path.with_suffix(path.suffix + ".part")
    temporary.write_text(text, encoding="utf-8")
    if secret:
        # It holds a token. Grafana reads it as its own user, so this is
        # about everybody else on the machine.
        try:
            os.chmod(temporary, 0o600)
        except OSError:  # pragma: no cover - Windows, and not a failure
            pass
    temporary.replace(path)


def stamp(words: Words | None = None) -> str:
    """A line for the generated dashboards, so their origin is on the page."""
    said = (words or Words()).generated
    return said.format(when=time.strftime("%Y-%m-%d %H:%M"))
