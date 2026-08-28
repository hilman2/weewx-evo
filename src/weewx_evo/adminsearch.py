"""Finding a setting by name, across everything that has one.

There are seven groups of core settings, one form per driver, one per feed,
export, upload and forecast, and ninety-two charts. Somebody who knows they
want "the FTP password" has to know which page it is on -- and the pages are
organised by what a thing *is*, which is the right organisation and the
wrong index.

So: one box, and it looks in every schema's every option, plus the charts
and the readings they draw. What comes back is a link to the page and the
anchor of the group the field is in, so following it lands on the setting
rather than at the top of a form with seven sections.

## Matching, and why it is this dull

Substring, case-folded, over the name, the label and the help text. Not
fuzzy, not ranked by cleverness: a settings search that guesses is one where
the thing you typed exactly is third. Exact-ish matches sort first, and that
is the whole of the ranking.

There is no index and nothing is cached. Everything here is already in
memory or in a file this process reads on every page anyway, and a stale
index is a search that cannot find what somebody saved a second ago.
"""

from __future__ import annotations

import html
import logging
from typing import Any

log = logging.getLogger(__name__)

NEWLINE = "\n"

#: Enough to be worth searching for. One letter matches most of the page and
#: two is still noise; the box says so rather than returning everything.
SHORTEST = 2

#: How many to show. Past this it is a list to scroll rather than an answer,
#: and the fix is a better query.
MOST = 60


class Hit:
    """One thing found, and how to reach it."""

    __slots__ = ("detail", "href", "rank", "title", "where")

    def __init__(self, title: str, where: str, href: str, detail: str = "",
                 rank: int = 2) -> None:
        self.title = title
        #: Which page it is on, in words. "Settings / Listener".
        self.where = where
        self.href = href
        self.detail = detail
        #: 0 is an exact name, 1 a name that starts with it, 2 the rest.
        self.rank = rank


def _rank(needle: str, name: str, label: str) -> int | None:
    name, label = name.casefold(), label.casefold()
    if needle in (name, label):
        return 0
    if name.startswith(needle) or label.startswith(needle):
        return 1
    return None


def find(admin: Any, query: str) -> list[Hit]:
    """Everything matching, best first."""
    needle = (query or "").strip().casefold()
    if len(needle) < SHORTEST:
        return []

    hits: list[Hit] = []
    for schema in admin.schemas:
        for group in schema.groups:
            for option in group.options:
                rank = _rank(needle, option.name, option.label)
                if rank is None:
                    if needle not in (option.help or "").casefold():
                        continue
                    rank = 3
                from .admin import anchor

                hits.append(Hit(
                    option.label, f"{schema.label} / {group.label}",
                    f"./{schema.name}#{anchor(group.label)}",
                    option.name, rank))

    hits.extend(_charts(admin, needle))
    hits.sort(key=lambda one: (one.rank, one.title.casefold()))
    return hits[:MOST]


def _charts(admin: Any, needle: str) -> list[Hit]:
    """Charts by their name, and by the readings they draw.

    The second one is the reason this is here at all: "where is outTemp
    drawn" is a question with a dozen answers spread over four spans, and no
    page lists it.
    """
    from . import adminplots

    try:
        charts = adminplots.load(admin)
    except Exception:
        log.debug("could not read the charts for the search", exc_info=True)
        return []

    found = []
    for plot in charts:
        rank = _rank(needle, plot.name, plot.title or plot.name)
        drawn = [line.obs for line in plot.lines]
        if rank is None:
            if not any(needle in one.casefold() for one in drawn):
                continue
            rank = 2
        shown = ", ".join(drawn[:4])
        if len(drawn) > 4:
            shown += f", and {len(drawn) - 4} more"
        found.append(Hit(plot.name, f"Charts / {plot.span}",
                         f"./plot:{plot.name}", shown, rank))
    return found


def box(query: str = "") -> str:
    """The search field. On every page, because that is the point of it."""
    return f'''
<form class="find" method="get" action="./search" role="search">
  <input type="search" name="q" value="{html.escape(query)}"
         placeholder="Find a setting" aria-label="Find a setting">
</form>'''


def results(admin: Any, query: str) -> str:
    query = (query or "").strip()
    if len(query.casefold()) < SHORTEST:
        return f'''
<h2>Find a setting</h2>
{box(query)}
<p class="lede">Type at least {SHORTEST} letters. It looks through every
   setting on every page, and through the charts and the readings they
   draw.</p>
'''

    hits = find(admin, query)
    if not hits:
        return f'''
<h2>Find a setting</h2>
{box(query)}
<p class="navempty">Nothing matches {html.escape(query)!r}. The search
   covers setting names, their labels and their explanations, chart names
   and the readings a chart draws.</p>
'''

    rows = NEWLINE.join(f'''
      <li>
        <a href="{html.escape(one.href)}">{html.escape(one.title)}</a>
        <span class="note">{html.escape(one.detail)}</span>
        <span class="note aside">{html.escape(one.where)}</span>
      </li>''' for one in hits)
    more = ""
    if len(hits) == MOST:
        more = (f'<p class="note">Showing the first {MOST}. '
                "Something more specific will do better.</p>")
    return f'''
<h2>Find a setting</h2>
{box(query)}
<p class="lede">{len(hits)} match(es) for {html.escape(query)!r}. Each one
   goes to the page and the section it is in.</p>
<section class="flow">
  <ul class="sends plain">{rows}</ul>
</section>
{more}
'''
