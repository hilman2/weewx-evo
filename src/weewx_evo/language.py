"""The words weewx-evo writes itself.

Not a skin's words. A skin keeps its own translations and they win wherever
they say anything, because the page belongs to whoever wrote it. This is for
everything the core produces where there is no skin in the way:

- the labels on a chart it draws, which go straight into a PNG
- the names of the moon's phases and the points of the compass
- the months on a time axis

## Why not gettext

`.mo` files are compiled and binary: they cannot be read with `cat`, cannot
be diffed, and need a build step before a translation takes effect. A
weather station is a machine somebody edits over SSH once a year. The same
reasoning as `plots.toml`: a file a person can open, change and hand to
somebody else.

## Why the months are here

`time.strftime("%b")` follows the *process* locale, not this setting. A
container with nothing set answers "May" where a German page wants "Mai",
and setting `LC_TIME` globally to fix one chart changes how every other part
of the program formats every other thing. So the twelve words are written
down and looked up.

## Adding a language

One file, `lang/<code>.toml`, in the shape of `de.toml`. Nothing has to be
registered: the file being there is what makes the language available, and
`languages()` reads the directory.
"""

from __future__ import annotations

import logging
import time
import tomllib
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

#: Where the files are. Beside this module, so an installation carries its
#: translations with it however it was installed.
HERE = Path(__file__).resolve().parent / "lang"

#: English, and the shape every other file follows. Written out rather than
#: kept in a file of its own: it is the fallback, and a fallback that can go
#: missing is not one.
ENGLISH: dict[str, Any] = {
    "name": "English",
    "moon": {
        "phases": ("New", "Waxing crescent", "First quarter",
                   "Waxing gibbous", "Full", "Waning gibbous",
                   "Last quarter", "Waning crescent"),
    },
    "compass": {
        "directions": ("N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
                       "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW",
                       "N/A"),
        "north": "N",
    },
    "months": {
        "short": ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
                  "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"),
        "long": ("January", "February", "March", "April", "May", "June",
                 "July", "August", "September", "October", "November",
                 "December"),
    },
    "days": {
        "short": ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"),
        "long": ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday",
                 "Saturday", "Sunday"),
    },
}


class Language:
    """One language, and what to say in it.

    Every lookup falls back to English rather than to the key: a translation
    that covers most of the readings and none of the moon phases should give
    English moon phases, not `moon.phases.3`.
    """

    __slots__ = ("code", "values")

    def __init__(self, code: str = "en",
                 values: dict[str, Any] | None = None) -> None:
        self.code = code or "en"
        self.values = values or {}

    @property
    def name(self) -> str:
        return str(self.values.get("name") or ENGLISH["name"])

    @property
    def unit_system(self) -> str:
        """What a page in this language is read in, unless told otherwise.

        Empty for English, because there is no answer: an American and a
        Briton read the same words and different units. German has one.
        """
        return str(self.values.get("unit_system") or "")

    def obs(self, obs_type: str) -> str:
        """What a reading is called. Empty where this language has no word.

        Empty rather than the English, so a caller can tell "translated to
        this" from "not translated" and fall back to whatever else it has --
        which for a chart is the skin's label first.
        """
        name = str(obs_type or "")
        found = (self.values.get("obs") or {})
        if name in found and isinstance(found[name], str):
            return found[name]

        families = found.get("numbered") or {}
        stem = name.rstrip("0123456789")
        number = name[len(stem):]
        if number and stem in families:
            return f"{families[stem]} {number}"
        return ""

    def weather(self, code: int, fallback: str = "") -> str:
        """What the sky is doing, for a WMO code.

        `forecast/codes.py` asks this and takes the English it already has
        when the answer is empty -- so a language that translates fifteen of
        the twenty-eight codes shows fifteen translated and thirteen in
        English, rather than nothing.

        The key is the number, because the number is what the source sends.
        Keying on the English would mean a translation breaking the moment
        somebody rewords "Light rain showers".
        """
        found = (self.values.get("weather") or {})
        said = found.get(str(int(code)))
        return said if isinstance(said, str) and said else fallback

    def moon_phases(self) -> tuple[str, ...]:
        return self._sequence("moon", "phases", 8)

    def compass(self) -> tuple[str, ...]:
        return self._sequence("compass", "directions", 17)

    def months(self, long: bool = False) -> tuple[str, ...]:
        return self._sequence("months", "long" if long else "short", 12)

    def days(self, long: bool = False) -> tuple[str, ...]:
        return self._sequence("days", "long" if long else "short", 7)

    def date_shape(self, which: str = "date") -> str:
        """This language's `%x`, `%X` or `%c`, as a plain strftime format.

        Empty where the language file says nothing, and then the caller
        leaves the code alone for `strftime` to answer out of the process
        locale -- which is the old behaviour, and right for English.
        """
        found = self.values.get("formats")
        if not isinstance(found, dict):
            found = ENGLISH.get("formats") or {}
        return str(found.get(which) or "")

    def spell(self, shape: str, when: float) -> str:
        """A moment, written out in this language.

        Two substitutions before `strftime` gets it, both for the same
        reason: the answer would otherwise come from the process locale.

        `%b` and friends are the names of months and days. `%x`, `%X` and
        `%c` are whole formats -- "the local way of writing a date" -- and
        what is local is the reader's language, not the container's
        environment, which is unset.
        """
        when_local = time.localtime(when)

        for code, which in (("%c", "datetime"), ("%x", "date"),
                            ("%X", "time")):
            if code in shape:
                said = self.date_shape(which)
                if said:
                    shape = shape.replace(code, said)

        for code, words, monthly in (("%b", self.months(), True),
                                     ("%B", self.months(long=True), True),
                                     ("%a", self.days(), False),
                                     ("%A", self.days(long=True), False)):
            if code not in shape:
                continue
            at = (when_local.tm_mon - 1) if monthly else when_local.tm_wday
            if 0 <= at < len(words):
                shape = shape.replace(code, words[at])

        return time.strftime(shape, when_local)

    def unit_labels(self) -> dict[str, Any]:
        """The words inside a unit, where this language has different ones.

        Only the ones that differ. Degrees Celsius are degrees Celsius
        everywhere; hours are Stunden.
        """
        found = self.values.get("units")
        if not isinstance(found, dict):
            return {}
        return {key: (tuple(value) if isinstance(value, (list, tuple))
                      else value)
                for key, value in found.items()}

    def text(self, section: str, key: str, fallback: str = "") -> str:
        """One word out of any section, or `fallback`.

        The escape hatch for everything that is neither a reading, a month
        nor a compass point -- the handful of structural words a page needs
        around them ("today", "compare", "indoors"). The caller carries the
        English, for the same reason this module does: a fallback that can
        be missing is not one.

        An untranslated key is not warned about. A language file with
        fifteen of twenty words should show fifteen translated, not produce
        five log lines every time a page is drawn.
        """
        found = (self.values.get(section) or {}).get(key)
        return found if isinstance(found, str) and found else fallback

    def say(self, english: str) -> str:
        """One piece of the settings page, in this language.

        Keyed on the English itself. That is the opposite of `weather()`,
        which is keyed on the WMO number, and the difference is who owns the
        wording: a forecast source can reword "Light rain showers" under us,
        while these words are ours. When one is reworded here, the key that
        no longer matches is *findable* -- `tools/adminlang_test.py` lists
        every string the page produces and every key no file answers -- and
        the fallback in the meantime is the English, which is correct rather
        than merely present.

        The alternative was a symbolic key for each of several hundred
        strings. That is a second name to invent, to keep unique and to keep
        in step with the text, for no gain: `admin.places.add.button` tells
        a translator less than "Add place" does.
        """
        return self.text("admin", english, english)

    def fill(self, english: str, **values: Any) -> str:
        """One piece of the page that has a number or a name in it.

        `say("{n} more, rarely needed").format(n=3)` would be the obvious
        spelling and is a page that can be taken down by a translation: a
        file with a stray brace, or one that renamed the placeholder, raises
        out of the middle of the markup. A translator who breaks a
        placeholder should cost their own language that one line, not the
        settings page.
        """
        said = self.say(english)
        try:
            return said.format(**values)
        except (KeyError, IndexError, ValueError):
            log.warning("%s: %r does not fit its placeholders; using English",
                        self.code, said)
            try:
                return english.format(**values)
            except (KeyError, IndexError, ValueError):
                # The English is ours and this is a programming error, but a
                # page that renders the braces is better than one that 500s.
                return english

    def setting(self, name: str, part: str = "label") -> str:
        """The label or help text of one setting, or empty.

        Keyed on the setting's own name (`interval`, `web.port`) rather than
        on its English, because `help` is several sentences and a paragraph
        makes a poor key. The name is already stable: it is what the option
        is called in the configuration file, and renaming one is a migration
        whether or not anything is translated.

        Empty rather than the English, so `field()` can tell "this language
        does not say" from "this language says the same" and fall back to
        what the schema carries.

        **Two settings sharing a name share this line, and that has bitten
        once.** The core had `driver` for "which protocol reads an upload
        whose path names none" while a driver add-on has `driver` for "which
        piece of hardware this reads" -- so a menu of serial consoles was
        rendered with the core's label *and* its help, a paragraph about
        upload paths. The fix was to delete the core's setting, which had
        stopped being needed: every installed protocol recognises its own
        uploads. Qualifying the key by the sort of thing it belongs to was
        the other candidate and is deliberately not here -- it is machinery
        for a collision that no longer exists, and `host` meaning host in
        both an FTP export and an MQTT driver is the ordinary case.
        """
        found = (self.values.get("settings") or {}).get(name)
        if not isinstance(found, dict):
            return ""
        said = found.get(part)
        return said if isinstance(said, str) else ""

    def _sequence(self, section: str, key: str,
                  wanted: int) -> tuple[str, ...]:
        found = (self.values.get(section) or {}).get(key)
        if isinstance(found, (list, tuple)) and len(found) == wanted:
            return tuple(str(x) for x in found)
        if found is not None:
            # The wrong length is worth saying: eight phases and seven names
            # is an index error somewhere downstream, weeks later.
            log.warning("%s: %s.%s has %d entries, not %d; using English",
                        self.code, section, key,
                        len(found) if hasattr(found, "__len__") else 0,
                        wanted)
        return tuple(ENGLISH[section][key])


#: Read files stay read. A hundred charts is a hundred lookups otherwise.
_LOADED: dict[str, Language] = {}


def get(code: str | None) -> Language:
    """The language for a code, or English.

    `de_AT` reads `de.toml` and then `de_AT.toml` over it, the same way a
    skin's translations work, so a regional file carries only what it says
    differently.
    """
    wanted = str(code or "").strip() or "en"
    if wanted in _LOADED:
        return _LOADED[wanted]

    country = wanted.split(".")[0]
    parts = country.split("_")
    order = [parts[0]] if len(parts) == 1 else [parts[0], country]

    values: dict[str, Any] = {}
    for name in order:
        found = _read(HERE / f"{name}.toml")
        if found:
            values = _merge(values, found)
    if not values and wanted not in ("en", "en_GB", "en_US"):
        log.info("no translation for %r; the built-in English is being used",
                 wanted)
    language = Language(wanted, values)
    _LOADED[wanted] = language
    return language


def languages() -> list[tuple[str, str]]:
    """Every language there is a file for, as (code, name).

    English is always first and always there, because it is built in.
    """
    out = [("en", ENGLISH["name"])]
    if HERE.is_dir():
        for path in sorted(HERE.glob("*.toml")):
            found = _read(path)
            name = str(found.get("name") or path.stem)
            if path.stem != "en":
                out.append((path.stem, name))
    return out


def forget() -> None:
    """Drop what has been read. For a test that changes a file."""
    _LOADED.clear()


def _read(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        with open(path, "rb") as handle:
            return tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        # Named, and then ignored. A broken translation should cost its own
        # words, not the whole report.
        log.error("could not read %s: %s", path, exc)
        return {}


def _merge(base: dict[str, Any], over: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for key, value in over.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out
