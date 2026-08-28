#
#    Copyright (c) 2026 Manuel Hilgert
#
#    See the file LICENSE for your full rights.
#
"""Hardware that pushes its readings at a server, in six protocols.

`protocols/` and `catalogs/` come from weewx-ultimate-push unchanged. They
import nothing -- not WeeWX, not this program -- so a fix can travel either
way. `driver.py` is the whole of the adaptation.
"""

VERSION = "0.8.0"
