import sys, os, time, sqlite3, tempfile, pathlib, shutil
sys.path.insert(0, "src")
os.environ["TZ"] = "Europe/Berlin"; time.tzset()
from weewx_evo import units, language
from weewx_evo.series import Reader
from weewx_evo.tags import Tags
from weewx_evo.feeds.cheetah import CheetahFeed

skin = pathlib.Path("/mnt/d/Git/weewx-wdc/skins/weewx-wdc")
conn = sqlite3.connect("file:reference/weewx.sdb?mode=ro", uri=True)
reader = Reader(conn)
out = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else tempfile.mkdtemp())
spoken = language.get("en")
tags = Tags(reader, target=units.Target(reader.system, language=spoken),
            unit_system=reader.system,
            station={"location": "Kirchdorf an der Amper", "latitude": 48.4596,
                     "longitude": 11.6539, "altitude": 440.0,
                     "station_url": "https://example.org", "version": "0.0.1",
                     "hardware": "ecowitt"})
feed = CheetahFeed(reader, skin, tags, encoding="html_entities")
made = feed.produce(out)
print(made.note)
print()
if feed.failed:
    for name, why in feed.failed[:12]:
        print(f"  {name}: {why[:130]}")
print()
print(tags.report())
