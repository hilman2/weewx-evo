"""weewx-evo: a modular rewrite of the WeeWX core.

The rule that shapes everything else: an existing WeeWX database must stay
readable and writable by WeeWX itself. Not "importable" -- the same file,
byte for byte the same meaning, with WeeWX 5 able to pick it up again.
"""

__version__ = "0.0.1"
