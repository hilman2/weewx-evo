# Web server

`webserver.py`. Serving what the feeds produced.

A [feed](Feeds) writes a directory full of files. Something has to hand them to
a browser, and on a station in a shed that something should not have to be
nginx.

This is the small local answer. Anyone wanting a real web server puts one in
front — or uses an [export](Exports) and lets somewhere else do the serving.

**What gets served does not come straight from the feed.** A `local` export puts
it down; this server hands it out. The detour is deliberate: a feed rewrites its
directory while it runs, and a browser loading in the middle of that would get
half a page. → [Exports](Exports#a-directory-on-this-machine)

## The routes

```
/                what there is — or one of them, if it is the default
/<name>/         that directory
/<name>/…        everything beneath it
```

With `web.default` set, `/` is that one, and the others stay under `/<name>/`.

## Where the names come from

**From the `local` exports.** An export called `site` publishing to `data/site`
appears at `/site/`.

That is the whole configuration: you say where an export puts something, and it
is served from there. **Nobody has to write the same path down twice.**

```toml
[exports.site]
kind = "local"
directory = "data/site"
source = "json"
```

→ `/site/`

`[web.serve]` additionally names directories directly — for something this
system did not produce: a hand-written page, a directory another program fills.

```toml
[web.serve]
alt = "/var/www/handmade"
```

Directly named entries are registered **last** and therefore beat an export of
the same name. Someone who wrote a path down meant it.

## `Site`

```python
site = Site(feeds={"site": Path("data/site")},
            default="site", title="weewx-evo")
```

| Method | What it means |
|---|---|
| `resolve(feed, rest)` | The file for a request, or `None` |

`site_from(settings, feeds=None)` builds it from the configuration.
`index_page(site)` is the listing when none of them is the default.

`options.published_names()` is the same list for the admin page's form: the
`local` exports plus the directly named entries. **Reading the exports rather
than the feeds is the difference between offering what there is and offering
what there could be.**

### The check that matters

The last one in `resolve()`: **the resolved path has to lie inside the feed's
directory.**

A `..` in a URL, a symlink leading out, a template assembling its output path
from something a person can type — a feed's directory is written from a
template, and a template that can be made to write `../../etc` is one that
somebody eventually writes by accident.

`tools/web_test.py` tries exactly that.

## Caching

```python
INDEXES = ("index.html", "index.htm")
CACHE_SECONDS = {".css": 3600, ".js": 3600,
                 ".woff": 86400, ".woff2": 86400, ".ttf": 86400,
                 ".ico": 86400, ".svg": 3600}
```

HTML and JSON get **no** caching: those are the files whose whole purpose is to
change.

## `WebServer`

```python
server = WebServer(site, host="0.0.0.0", port=8081,
                   access=PRIVATE_ONLY, limits=limits)
server.start()
server.stop()
```

Like the other two services: bound to everything, answering private networks
only, with the same rate limit. → [Security](Security)

**No token.** A weather page is not a secret. What protects it is the network
boundary — and the fact that this machine answers nobody else.

## Running it

```bash
weewx-evo web --config evo.toml --port 8081
```

Or as part of `serve`, when `web.enabled` is set. Separate for the same reason
as `listen`: a machine that only shows the pages need not be the one that
records them.

## Settings

→ [Settings-Reference](Settings-Reference#website)

| | |
|---|---|
| `web.enabled` | Whether it runs along with `serve` |
| `web.port` | Default 8081, its own port |
| `web.default` | What sits at `/`. The choices come from `published_names()` |
| `web.allow` | Who gets an answer |
| `web.host` | |
| `[web.serve]` | Names pointing straight at directories |

## Checking it

```bash
python tools/web_test.py
```

Two things are checked: the routing — feeds under `/<name>/`, one of them
optionally at `/` — and **the boundary**, which is the part that would matter if
it were wrong.

<!-- covers
src/weewx_evo/webserver.py
tools/web_test.py
-->
