"""Calibration and limits, in the settings page.

Like the charts, these do not fit the form generator: a limit is not one
named value but four numbers about one reading, and a station has a hundred
readings. So this is written by hand, and it has to be better than a text
editor at the two things a text editor cannot do at all.

**Show what the reading has actually done.** Nobody can type a plausible
ceiling for `soilMoist3` out of their head, and a guessed limit throws away
measurements. So every row carries the range that reading has been in, taken
from the archive, beside the box the figure goes in. Guessing is then a
matter of looking rather than of remembering.

**Say what a rule would cost before it is saved.** `weewx-evo quality check`
answers that from the command line; this page runs the same comparison and
prints it above the table -- a limit that would have refused two hundred
readings last month is a limit about the rule, not about the sensor.

## Only the readings that are there

A station has a hundred columns in its schema and reports thirty. Listing all
of them is a page nobody scrolls, so the table is what the archive has
actually recorded, and the ones with a rule come first.

## Every series, because the rules are not keyed on one

There is one `quality.toml`, and `build_archivers` hands the same policy to
every archiver. So a floor worked out from the default series is applied to
the north field too, and a page that measured only the default would offer a
ceiling the north field passes twice a summer -- with the dry run beside it
saying the rule refuses nothing.

Which files those are comes from `archives.toml` through the register, the
way `Admin.columns` finds them. Reading `archive_db` instead is what this did
before, and the two are allowed to differ the moment anything writes either:
on the beta instance `archive_db` still said `archive/weewx.sdb` while the
register said `/data/weewx.sdb`, so the page found no file, showed no rows at
all, and answered "there is nothing in the archive to work them out from yet"
about a database holding a year.

## The file stays hand-editable

This writes the same `quality.toml` a person would, in the same shape --
`[limits.<obs>]` and `[calibrate.<sender-id>.<obs>]`. Same rule as
`plots.toml`: the file is the thing, and this is a way of editing it.
"""

from __future__ import annotations

import html
import json
import logging
import sqlite3
import time
from contextlib import closing
from pathlib import Path
from typing import Any

from . import quality as quality_defs
from . import units

log = logging.getLogger(__name__)

NEWLINE = "\n"

#: How much history the ranges and the dry run look at. A year, because a
#: station that has not seen a cold winter has not seen its own floor -- and
#: reading it is one indexed scan.
LOOK_BACK = 365 * 86400

#: The most rows shown before the rest go behind a summary line. Thirty-four
#: readings with four boxes each is a page nobody finishes.
SHOWN = 40


def path_for(admin: Any) -> Path:
    """Beside the configuration, like `plots.toml`."""
    named = str(getattr(admin, "quality_file", "")
                or quality_defs.FILENAME)
    where = Path(named)
    return where if where.is_absolute() else Path(admin.path).parent / where


def load(admin: Any) -> quality_defs.Policy:
    return quality_defs.load(path_for(admin))


def store(admin: Any, policy: quality_defs.Policy) -> str:
    """Write the file. Returns an error, or empty.

    Written beside and renamed, so a page saved while the archiver is reading
    never hands it half a file.
    """
    if getattr(admin, "read_only", False):
        return "This admin page was started read-only."
    where = path_for(admin)
    try:
        working = where.with_suffix(".part")
        working.write_text(as_toml(policy), encoding="utf-8")
        working.replace(where)
    except OSError as exc:
        log.exception("could not write %s", where)
        return f"Could not write {where}: {exc}"
    return ""


def as_toml(policy: quality_defs.Policy) -> str:
    """The policy as the file a person would have written."""
    lines = [
        "# Calibration and limits. Written by the settings page, and meant to",
        "# be readable and editable by hand.",
        "#",
        "# A reading that fails a limit is dropped, not zeroed: zero is a",
        "# measurement, and a gauge reporting 0.0 because its value was",
        "# refused cannot be told from a dry afternoon.",
        "",
        f'unit_system = "{units.name(policy.system).lower()}"',
    ]
    for obs in sorted(policy.limits):
        rule = policy.limits[obs]
        lines.append("")
        lines.append(f"[limits.{_key(obs)}]")
        if rule.minimum is not None:
            lines.append(f"minimum = {rule.minimum:g}")
        if rule.maximum is not None:
            lines.append(f"maximum = {rule.maximum:g}")
        if rule.spike is not None:
            lines.append(f"spike = {rule.spike:g}")
        if rule.stuck is not None:
            lines.append(f"stuck = {rule.stuck}")
        if rule.resolution:
            lines.append(f"resolution = {rule.resolution:g}")

    entries = {**policy.obsolete_calibration, **policy.calibration}
    for sender in sorted(entries):
        for obs in sorted(entries[sender]):
            adjust = entries[sender][obs]
            who = sender or "everywhere"
            lines.append("")
            if sender in policy.obsolete_calibration:
                lines.append("# Ignored legacy label: use a canonical sender ID.")
            lines.append(f"[calibrate.{_key(who)}.{_key(obs)}]")
            if adjust.offset:
                lines.append(f"offset = {adjust.offset:g}")
            if adjust.scale != 1.0:
                lines.append(f"scale = {adjust.scale:g}")
    return NEWLINE.join(lines) + NEWLINE


def _key(value: str) -> str:
    """One quoted TOML key, including slashes and dots in sender IDs."""
    return json.dumps(str(value), ensure_ascii=False)


# ---------------------------------------------------------------------------
# What the readings have done.
# ---------------------------------------------------------------------------

def survey(admin: Any, since: float | None = None
           ) -> tuple[dict[str, quality_defs.Seen], dict[str, int], int]:
    """What the readings have been, and what the rules would refuse.

    One pass over every series, because the page needs both figures about the
    same records and reading a year of archive twice per render is a settings
    page that takes seconds to open.

    Returns the ranges by reading, how many records each rule would refuse by
    reading, and how many records were looked at. Refusals are empty where
    nothing is configured, which is most installations.
    """
    since = (time.time() - LOOK_BACK) if since is None else since
    policy = load(admin)
    checking = bool(policy.limits)

    ranges = []
    dropped: dict[str, int] = {}
    records = 0
    for name, where in _series(admin):
        rows = _records(where, since)
        if not rows:
            continue
        records += len(rows)
        ranges.append(quality_defs.watch(rows, system=policy.system))
        if not checking:
            continue
        # A checker per series. Shared, the last record of one place would be
        # the spike rule's reference for the first of another -- a step
        # neither sensor took, reported against whichever place happens to be
        # read second.
        checker = quality_defs.Check(policy)
        for row in rows:
            system = units.system_from(row.get("usUnits"),
                                       default=units.METRICWX)
            corrected = checker.calibrate(row, "", system)
            checker.check(corrected, float(row.get("dateTime") or 0), "",
                          system)
        for obs, count in checker.dropped.items():
            dropped[obs] = dropped.get(obs, 0) + count
        log.debug("%s: %d record(s), %d refused", name, len(rows),
                  sum(checker.dropped.values()))

    return quality_defs.across(ranges), dropped, records


def measured(admin: Any, since: float | None = None
             ) -> dict[str, quality_defs.Seen]:
    """What each reading has been, from the archives.

    The figure beside the box. Without it the page is a text editor with
    worse keybindings -- typing a ceiling for a soil probe out of your head
    is exactly what produces a limit that throws away measurements.
    """
    return survey(admin, since)[0]


def _series(admin: Any) -> list[tuple[str, Path]]:
    """Every series' archive file that is actually there, by place name.

    Out of the register rather than out of `archive_db`, and out of the
    configuration the page is editing rather than the running settings: a
    page that read a different file would show ranges for an archive it is
    not writing rules for. With no `archives.toml` the register answers with
    the settings themselves, so a single-series installation gets the file it
    has always got.
    """
    from . import adminarchives

    try:
        every = adminarchives.load(admin).all()
    except Exception:
        log.debug("could not read the archives for the ranges", exc_info=True)
        return []

    out = []
    for one in every:
        where = Path(str(one.file))
        if not where.is_absolute():
            where = Path(admin.path).parent / where
        if where.exists():
            out.append((one.name, where))
    return out


def _records(where: Path, since: float) -> list[dict]:
    """One archive over the window, oldest first.

    Read-only and `closing` as well as `with`: the context manager on a
    connection commits the transaction and leaves the connection open, and
    this is called on every render.
    """
    try:
        with closing(sqlite3.connect(f"file:{where}?mode=ro",
                                     uri=True)) as conn:
            conn.row_factory = sqlite3.Row
            return [dict(row) for row in conn.execute(
                "SELECT * FROM archive WHERE dateTime >= ? ORDER BY dateTime",
                (int(since),))]
    except sqlite3.Error:
        log.debug("could not read %s for the ranges", where, exc_info=True)
        return []


# ---------------------------------------------------------------------------
# Changing things.
# ---------------------------------------------------------------------------

def save(admin: Any, form: dict[str, Any]) -> dict[str, str]:
    """Take the whole table back. Returns errors by field name."""
    policy = load(admin)
    errors: dict[str, str] = {}
    limits = dict(policy.limits)

    for key, raw in sorted(form.items()):
        if not key.startswith("limit-"):
            continue
        _mark, obs, what = key.split("-", 2)
        value = str(raw).strip()
        rule = limits.get(obs) or quality_defs.Rule()
        try:
            limits[obs] = _with(rule, what, value)
        except ValueError:
            errors[key] = f"{value!r} is not a number"

    policy.limits = {obs: rule for obs, rule in limits.items()
                     if not rule.empty()}
    said = store(admin, policy)
    if said:
        errors[""] = said
    return errors


def _with(rule: quality_defs.Rule, what: str, value: str) -> quality_defs.Rule:
    """One field of one rule, changed. An empty box removes it."""
    from dataclasses import replace

    if what == "stuck":
        return replace(rule, stuck=int(float(value)) if value else None)
    if what == "resolution":
        return replace(rule, resolution=float(value) if value else 0.0)
    if what in ("minimum", "maximum", "spike"):
        return replace(rule, **{what: float(value) if value else None})
    return rule


def suggest(admin: Any) -> str:
    """Fill the table in from what the station has recorded.

    The button that makes this page worth having. It never overwrites a rule
    somebody wrote: a suggestion is what to do when you have nothing, not an
    opinion about what you already decided.
    """
    seen = measured(admin)
    if not seen:
        return ("There is nothing in the archive to work them out from yet.")
    policy = load(admin)
    limits = dict(policy.limits)
    added = 0
    for obs, entry in seen.items():
        if obs in limits:
            continue
        rule = entry.rule()
        if not rule.empty():
            limits[obs] = rule
            added += 1
    if not added:
        return "Every reading already has a rule; nothing was changed."
    policy.limits = limits
    return store(admin, policy)


def clear(admin: Any, obs: str) -> str:
    """Drop one reading's rule."""
    policy = load(admin)
    if obs in policy.limits:
        del policy.limits[obs]
        return store(admin, policy)
    return ""


# ---------------------------------------------------------------------------
# The page.
# ---------------------------------------------------------------------------

def nav(admin: Any, active: str) -> list[str]:
    """One entry, with how many readings have a rule."""
    policy = load(admin)
    current = " aria-current='page'" if active == "quality" else ""
    count = (f'<span class="count">{len(policy.limits)}</span>'
             if policy.limits else "")
    # The link says what the page it opens is called. It said "Quality" and
    # opened a page headed "Quality control", which is the same defect the
    # rest of this sidebar had four times over.
    return [f'<a href="./quality"{current}>Sensor checks{count}</a>']


def overview(admin: Any, message: str = "", error: str = "") -> str:
    policy = load(admin)
    seen, dropped, records = survey(admin)
    problem = f'<p class="err">{html.escape(error)}</p>' if error else ""
    obsolete = ""
    if policy.obsolete_calibration:
        names = ", ".join(sorted(policy.obsolete_calibration))
        obsolete = (f'<p class="err">Ignored calibration labels: '
                    f'{html.escape(names)}. Use canonical Sender IDs.</p>')

    # Readings with a rule first, then the ones the archive holds. A page
    # that lists a hundred schema columns is a page nobody scrolls.
    named = sorted(policy.limits)
    rest = sorted(one for one in seen if one not in policy.limits)
    rows = [_row(obs, policy, seen, dropped, records) for obs in named]
    others = [_row(obs, policy, seen, dropped, records)
              for obs in rest[:SHOWN]]

    hidden = ""
    if others:
        hidden = f'''
<details class="more">
  <summary>{len(rest)} more reading(s) the archive holds</summary>
  <table class="rules">{_head()}{NEWLINE.join(others)}</table>
</details>'''

    return f'''
<section class="group">
  <h3>Sensor checks</h3>
  <p class="lede">Limits applied before readings are archived. No saved
     rule means no check.</p>
  {problem}
  {obsolete}
  {_dry_run(dropped, records)}
  <div class="actions">
    <form method="post" action="./quality/suggest">
      <button class="button" type="submit">Suggest from archive</button>
    </form>
  </div>
  <p class="help">Uses the last year. Existing rules stay unchanged.</p>

  <form method="post" action="./quality">
    <table class="rules">{_head()}{NEWLINE.join(rows) or _empty()}</table>
    <div class="actions">
      <button class="button" type="submit">Save</button>
    </div>
  </form>
  {hidden}
  <p class="help">Units: <strong>{html.escape(units.name(policy.system).lower())}</strong>.
     Spike: per minute. Stuck: identical readings; requires resolution.</p>
</section>'''


def _head() -> str:
    return '''
<thead><tr>
  <th>Reading</th><th>Seen</th><th>Floor</th><th>Ceiling</th>
  <th>Spike / min</th><th>Stuck</th><th>Resolution</th>
</tr></thead>'''


def _empty() -> str:
    return ('<tr><td colspan="7" class="quiet">No rules. Nothing is being '
            'refused.</td></tr>')


def _row(obs: str, policy: quality_defs.Policy, seen: dict,
         dropped: dict, records: int) -> str:
    rule = policy.limits.get(obs) or quality_defs.Rule()
    entry = seen.get(obs)
    unit, _group = units.unit_of(obs, policy.system)
    label = units.label(unit) if unit else ""

    if entry is not None and entry.count > 1:
        range_said = (f"{entry.lowest:g} to {entry.highest:g}"
                      f"{html.escape(label)}")
    else:
        range_said = '<span class="quiet">not recorded</span>'

    refused = dropped.get(obs, 0)
    note = ""
    if refused:
        share = 100.0 * refused / max(records, 1)
        # A rule refusing a large share of a station's own history is a rule
        # about the rule, not about the sensor.
        tone = "warn" if share > 5 else "quiet"
        note = (f'<div class="{tone}">would refuse {refused} '
                f'({share:.1f}%)</div>')

    return f'''
<tr>
  <td><strong>{html.escape(obs)}</strong>
      <div class="quiet">{html.escape(units.obs_label(obs))}</div>{note}</td>
  <td class="num">{range_said}</td>
  {_box(obs, "minimum", rule.minimum)}
  {_box(obs, "maximum", rule.maximum)}
  {_box(obs, "spike", rule.spike)}
  {_box(obs, "stuck", rule.stuck)}
  {_box(obs, "resolution", rule.resolution or None)}
</tr>'''


def _box(obs: str, what: str, value: Any) -> str:
    shown = "" if value is None else f"{value:g}"
    return (f'<td><input type="text" inputmode="decimal" '
            f'name="limit-{html.escape(obs)}-{what}" '
            f'value="{html.escape(shown)}" size="6" '
            f'autocomplete="off" spellcheck="false"></td>')


def _dry_run(dropped: dict, records: int) -> str:
    """What the rules as they stand would cost, before anything is saved."""
    if not records:
        return ""
    if not dropped:
        return ('<p class="ok">Over the last year of records, these rules '
                'would refuse nothing.</p>')
    total = sum(dropped.values())
    worst = max(dropped.values())
    said = ", ".join(f"{html.escape(obs)} ({count})"
                     for obs, count in sorted(dropped.items(),
                                              key=lambda x: -x[1])[:5])
    tone = "err" if worst > records * 0.05 else "note"
    extra = ("<br>More than one record in twenty is refused, which is "
             "usually a limit set too tightly rather than a sensor at fault."
             if worst > records * 0.05 else "")
    return (f'<p class="{tone}">Over {records} record(s), these rules would '
            f'refuse {total} reading(s): {said}.{extra}</p>')
