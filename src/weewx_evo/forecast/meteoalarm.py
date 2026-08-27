"""MeteoAlarm: official warnings for 38 European countries, in one feed.

Every European weather service issues its own warnings in its own format on
its own schedule. MeteoAlarm is the aggregator EUMETNET runs to put them in
one place, and it publishes CAP -- the same document format the American NWS
uses -- inside an Atom feed per country. So one parser covers a continent, and
the warnings are the *official* ones rather than somebody's reinterpretation.

Two things to know.

**A country feed is not a place.** Germany's feed carries every warning for
every district in the country: 46 of them on an ordinary morning. So a region
has to be picked, and the region ids (`DE037`) are not something anybody
knows off the top of their head. `check()` therefore lists what is currently
in the feed, with names -- which makes the settings page's test button the way
somebody finds their own region rather than a validation afterthought.

Matching is on the area description as well as the id, because "Kreis Plön"
is findable and `DE037` is not.

**The legacy RSS feeds were switched off on 14 January 2026.** The Atom feeds
carry the same data and are the ones being maintained. Anything still pointing
at `.../rss/...` has been receiving nothing since then, silently -- which is
the failure mode this whole file is meant to avoid, so it is worth saying
twice.
"""

from __future__ import annotations

import datetime
import logging
import re

from ..uploads import request
from . import BaseSource, ForecastError, Place, Reading, Warning, parse_xml

log = logging.getLogger(__name__)

HOST = "feeds.meteoalarm.org"
PATH = "/feeds/meteoalarm-legacy-atom-{country}"

ATOM = "{http://www.w3.org/2005/Atom}"
CAP = "{urn:oasis:names:tc:emergency:cap:1.2}"

#: The country names in the feed URLs. MeteoAlarm spells them out in English
#: and lowercase, which is not derivable from a country code -- so the list is
#: here rather than guessed, and a wrong guess is a 404 rather than an empty
#: feed that looks like calm weather.
COUNTRIES: tuple[tuple[str, str], ...] = (
    ("austria", "Austria"), ("belgium", "Belgium"),
    ("bosnia-herzegovina", "Bosnia and Herzegovina"), ("bulgaria", "Bulgaria"),
    ("croatia", "Croatia"), ("cyprus", "Cyprus"), ("czechia", "Czechia"),
    ("denmark", "Denmark"), ("estonia", "Estonia"), ("finland", "Finland"),
    ("france", "France"), ("germany", "Germany"), ("greece", "Greece"),
    ("hungary", "Hungary"), ("iceland", "Iceland"), ("ireland", "Ireland"),
    ("israel", "Israel"), ("italy", "Italy"), ("latvia", "Latvia"),
    ("lithuania", "Lithuania"), ("luxembourg", "Luxembourg"),
    ("malta", "Malta"), ("moldova", "Moldova"), ("montenegro", "Montenegro"),
    ("netherlands", "Netherlands"), ("north-macedonia", "North Macedonia"),
    ("norway", "Norway"), ("poland", "Poland"), ("portugal", "Portugal"),
    ("romania", "Romania"), ("serbia", "Serbia"), ("slovakia", "Slovakia"),
    ("slovenia", "Slovenia"), ("spain", "Spain"), ("sweden", "Sweden"),
    ("switzerland", "Switzerland"), ("ukraine", "Ukraine"),
    ("united-kingdom", "United Kingdom"),
)


def parse_time(text: str | None) -> int:
    """A CAP timestamp as unix time. Zero when absent or unparseable.

    CAP writes `2026-08-27T06:00:00+00:00`, and some producers write `Z`
    instead of the offset. `fromisoformat` handles the offset in every
    supported Python and the `Z` only from 3.11 -- which is our floor, but
    the substitution costs nothing and removes the question.
    """
    if not text:
        return 0
    try:
        cleaned = text.strip().replace("Z", "+00:00")
        when = datetime.datetime.fromisoformat(cleaned)
    except ValueError:
        return 0
    if when.tzinfo is None:
        # No zone at all. CAP requires one, so this is a producer being
        # sloppy; UTC is the least wrong reading and the alternative is
        # discarding a real warning.
        when = when.replace(tzinfo=datetime.UTC)
    return int(when.timestamp())


class MeteoAlarm(BaseSource):
    """Warnings from meteoalarm.org."""

    label = "MeteoAlarm"
    summary = ("Official weather warnings for 38 European countries, from "
               "the aggregator EUMETNET runs. No account needed.")
    warns = True
    #: Warnings change on their own schedule, not on a model run. Fifteen
    #: minutes is often enough to be useful and rare enough to be polite.
    every = 900

    def __init__(self, country: str = "", region: str = "",
                 minimum: str = "Minor", host: str = HOST,
                 timeout: int = 20, every: int = 900) -> None:
        self.country = (country or "").strip().lower()
        # One or more, comma separated: a district and the coast beside it
        # are two regions and somebody living there wants both.
        self.regions = [r.strip().lower() for r in (region or "").split(",")
                        if r.strip()]
        self.minimum = (minimum or "Minor").strip()
        self.host = host or HOST
        self.timeout = int(timeout)
        self.every = int(every)
        if not self.country:
            raise ValueError(
                "MeteoAlarm needs a country: its feeds are one per country. "
                f"One of: {', '.join(name for name, _label in COUNTRIES)}")

    # -- fetching --------------------------------------------------------

    def _feed(self) -> str:
        status, body = request(self.host, PATH.format(country=self.country),
                               timeout=self.timeout)
        if status == 404:
            raise ForecastError(
                f"MeteoAlarm has no feed called {self.country!r}. It spells "
                f"countries out in English and lowercase, like "
                f"'united-kingdom'.", permanent=True)
        if status != 200:
            raise ForecastError(f"MeteoAlarm answered {status}")
        return body

    def fetch(self, place: Place) -> Reading:
        reading = Reading(source="meteoalarm")
        for entry in self.entries(self._feed()):
            if not self._wanted(entry):
                continue
            reading.warnings.append(entry)
        if not self.regions:
            reading.note = (f"no region set, so all {len(reading.warnings)} "
                            f"warnings for {self.country} are kept")
        return reading

    def entries(self, xml: str) -> list[Warning]:
        """Every warning in the feed, before any filtering.

        Public because `check` uses it to show what regions exist -- which is
        how somebody finds the id for their own.
        """
        root = parse_xml(xml, "MeteoAlarm feed")
        found = []
        for entry in root.findall(f"{ATOM}entry"):
            area = _text(entry, f"{CAP}areaDesc")
            code = ""
            for geocode in entry.findall(f"{CAP}geocode"):
                if _text(geocode, f"{ATOM}valueName") == "EMMA_ID":
                    code = _text(geocode, f"{ATOM}value")
            identifier = (_text(entry, f"{CAP}identifier")
                          or _text(entry, f"{ATOM}id"))
            found.append(Warning(
                identifier=f"{identifier}:{code or area}",
                event=_text(entry, f"{CAP}event"),
                severity=_text(entry, f"{CAP}severity") or "Unknown",
                urgency=_text(entry, f"{CAP}urgency"),
                certainty=_text(entry, f"{CAP}certainty"),
                starts=parse_time(_text(entry, f"{CAP}onset")
                                  or _text(entry, f"{CAP}effective")),
                ends=parse_time(_text(entry, f"{CAP}expires")) or None,
                issued=parse_time(_text(entry, f"{CAP}sent")),
                headline=_text(entry, f"{ATOM}title"),
                area=area,
                kind=code,
                source="meteoalarm",
            ))
        return found

    def _wanted(self, warning: Warning) -> bool:
        if warning.rank < _rank(self.minimum):
            return False
        if not self.regions:
            # No region set keeps everything. That is loud rather than
            # silent, which is the right way round for a warning: somebody
            # will notice a page covered in alerts for the whole country and
            # go and narrow it down. Nobody notices missing ones.
            return True
        haystack = f"{warning.kind} {warning.area}".lower()
        return any(region in haystack for region in self.regions)

    # -- the settings page -----------------------------------------------

    def check(self, place: Place) -> str:
        """Fetch, and list the regions -- which is how somebody finds theirs."""
        try:
            entries = self.entries(self._feed())
        except ForecastError as exc:
            return f"refused: {exc}"
        except Exception as exc:
            return f"could not reach {self.host}: {exc}"
        if not entries:
            return (f"The feed for {self.country} is reachable and currently "
                    f"carries no warnings, which is what calm weather looks "
                    f"like. Come back when there is some to pick a region.")

        regions = sorted({(w.kind, w.area) for w in entries if w.area})
        kept = [w for w in entries if self._wanted(w)]
        lines = [(f"{len(entries)} warning(s) in the {self.country} feed, "
                  f"{len(kept)} of them matching this setting."), "",
                 ("Regions with a warning right now -- use the id or any "
                  "part of the name:")]
        for code, area in regions[:40]:
            lines.append(f"  {code or '?':<8} {area}")
        if len(regions) > 40:
            lines.append(f"  ... and {len(regions) - 40} more")
        return "\n".join(lines)

    @staticmethod
    def options() -> list:
        from ..options import Group, Option

        return [
            Group("Where", "", (
                Option("country", "Country", kind="choice", required=True,
                       choices=COUNTRIES,
                       help="MeteoAlarm publishes one feed per country."),
                Option("region", "Region", kind="list",
                       placeholder="DE037, Kreis Ploen",
                       help="A country feed carries every district. Use the "
                            "region id or any part of its name; several are "
                            "allowed. Leave it empty and every warning in the "
                            "country is kept, which is loud but never misses "
                            "one. Press 'Test' to see the regions that have a "
                            "warning right now."),
            )),
            Group("What to keep", "", (
                Option("minimum", "At least", kind="choice", default="Minor",
                       choices=(("Minor", "everything, including yellow"),
                                ("Moderate", "orange and above"),
                                ("Severe", "red and above"),
                                ("Extreme", "only the most severe")),
                       help=("CAP's own levels. Yellow warnings are frequent "
                             "and often about ordinary rain.")),
            )),
            Group("How often", "", (
                Option("every", "Ask every", kind="duration", default=900,
                       minimum=300, maximum=7200,
                       help="Warnings do not follow a model run, so this is "
                            "a compromise between being current and being a "
                            "good guest on a free service."),
            )),
            Group("How", "", (
                Option("host", "Feed host", default=HOST, advanced=True),
                Option("timeout", "Give up after", kind="duration",
                       default=20, minimum=5, maximum=120, advanced=True),
            )),
        ]


def _text(element: object, path: str) -> str:
    found = element.find(path) if element is not None else None
    if found is None or found.text is None:
        return ""
    return re.sub(r"\s+", " ", found.text).strip()


def _rank(severity: str) -> int:
    return {"minor": 1, "moderate": 2, "severe": 3, "extreme": 4}.get(
        severity.lower(), 0)
