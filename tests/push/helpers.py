#
#    Copyright (c) 2026 Manuel Hilgert
#
#    See the file LICENSE for your full rights.
#
"""What the tests need in order to say what they mean.

A mapper needs a dialect, and most tests do not care which one: they are about
inference, or about a captured payload, and the dialect is scaffolding. These build
the one they meant.
"""

from ultimatepush import protocols, transport
from ultimatepush.mapping import Mapper
from ultimatepush.protocols import Dialect


def mapper_for(fields=None, groups=None, channels=None, contested=None,
               placement_unknown=None, dialect=None, protocol='ecowitt', **kwargs):
    """A Mapper for a test.

    With no catalog given, it reads the named protocol's own, which is what the
    captured payloads in fixtures/ are. With one given, it builds a dialect out of
    exactly that, so a test about inference does not have to be rewritten every time
    the real catalog gains a sensor.
    """
    if dialect is None:
        if (fields is None and groups is None and channels is None
                and contested is None and placement_unknown is None):
            dialect = protocols.by_name(protocol).dialect({})
        else:
            dialect = Dialect('test', fields or {}, groups, channels, contested,
                              contested_with='another driver',
                              placement_unknown=placement_unknown, prefix='test_')
    return Mapper(dialect, **kwargs)


def read(protocol, text, **kwargs):
    """Read a captured payload the way the driver would, without a driver.

    Returns (packet, dialect, guesses). The protocol is named rather than detected,
    because a test about a catalog should fail on the catalog rather than on
    detection; detection has its own tests.
    """
    protocol = protocols.by_name(protocol) if isinstance(protocol, str) else protocol
    raw = transport.parse(text)
    dialect = protocol.dialect(raw)
    mapper = mapper_for(dialect=dialect, **kwargs)
    mapper.settle(protocol.settled_contested(raw))
    packet, guesses = mapper.to_packet(protocol.readings(FakeRequest(text), raw))
    return packet, dialect, guesses


def dialect_for(protocol, raw=None):
    """The dialect a protocol would read this payload with."""
    return protocols.by_name(protocol).dialect(raw or {})


class FakeRequest:
    """What a listener hands a driver, with only the parts a protocol looks at."""

    def __init__(self, text='', path='/data/report/', method='POST',
                 client_address='10.0.0.5'):
        self.text = text
        self.path = path
        self.method = method
        self.query = text if method == 'GET' else ''
        self.body = text.encode('utf-8') if method != 'GET' else b''
        self.headers = {}
        self.client_address = client_address
