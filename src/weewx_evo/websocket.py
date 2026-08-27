"""WebSocket, RFC 6455, enough of it to carry MQTT.

A browser cannot open a TCP socket. It can open a WebSocket, and the MQTT
specification defines how MQTT rides inside one -- which is why every weather
skin that shows live readings needs a broker with a websocket listener, and
why this file exists.

It is a second protocol, and that is the honest cost of being the broker
rather than telling somebody to install Mosquitto. It is also a small one:
a handshake and a framing layer, both fully specified, both in the standard
library's reach.

## What is here

  * The opening handshake: an HTTP request with `Upgrade: websocket`, answered
    with the SHA-1 of the client's key and a fixed magic string. That constant
    is not a secret and not a checksum -- it exists so that a caching proxy
    which does not understand WebSocket cannot accidentally complete the
    handshake from a stored response.
  * Framing: opcodes, the three payload length forms, and masking.
  * Ping and pong, because a browser tab in the background gets one from the
    other side eventually and a socket that does not answer is closed.

## What is not

No extensions, so no `permessage-deflate`. A weather reading is a few hundred
bytes and compressing it would cost more than it saves. No fragmentation on
the way out: nothing here writes a message big enough to need it. Fragments
*arriving* are handled, because a browser is entitled to send them.

## The rule that catches everybody

**A client must mask every frame it sends; a server must never mask one.**
Not a suggestion: a conforming implementation closes the connection when the
other side gets it wrong. Masking is not security -- the key is in the frame --
it exists so that a proxy cannot be tricked into seeing an HTTP request inside
a WebSocket payload.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import os
import socket
import struct

log = logging.getLogger(__name__)

#: RFC 6455's constant, appended to the client's key before hashing. Not a
#: secret: it is there so a proxy that does not understand WebSocket cannot
#: complete the handshake out of a cached response.
MAGIC = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

CONTINUATION, TEXT, BINARY = 0x0, 0x1, 0x2
CLOSE, PING, PONG = 0x8, 0x9, 0xA

#: The largest message accepted. A weather reading is a few hundred bytes;
#: this is far above anything legitimate and far below what would hurt.
MAX_MESSAGE = 1 << 20


class WebSocketError(Exception):
    """The connection cannot continue."""


def accept_key(key: str) -> str:
    """The `Sec-WebSocket-Accept` value for a client's key."""
    digest = hashlib.sha1((key + MAGIC).encode("ascii")).digest()  # noqa: S324
    return base64.b64encode(digest).decode("ascii")


def handshake_response(headers: dict[str, str],
                       protocol: str = "mqtt") -> bytes | None:
    """The 101 response for an upgrade request, or None if it is not one.

    `protocol` is echoed back in `Sec-WebSocket-Protocol`. Every browser MQTT
    library asks for `mqtt` and several refuse a server that does not answer
    with it -- so this is not decoration.
    """
    lowered = {k.lower(): v for k, v in headers.items()}
    if "websocket" not in lowered.get("upgrade", "").lower():
        return None
    key = lowered.get("sec-websocket-key", "").strip()
    if not key:
        return None

    lines = [
        "HTTP/1.1 101 Switching Protocols",
        "Upgrade: websocket",
        "Connection: Upgrade",
        f"Sec-WebSocket-Accept: {accept_key(key)}",
    ]
    # Only when the client asked for it. Answering with a subprotocol nobody
    # offered is itself a protocol error.
    offered = [p.strip() for p in
               lowered.get("sec-websocket-protocol", "").split(",") if p.strip()]
    if protocol and protocol in offered:
        lines.append(f"Sec-WebSocket-Protocol: {protocol}")
    return ("\r\n".join(lines) + "\r\n\r\n").encode("ascii")


def encode_frame(payload: bytes, opcode: int = BINARY,
                 mask: bool = False) -> bytes:
    """One frame. `mask` only for a client -- a server must never mask."""
    first = 0x80 | opcode          # FIN set: nothing here fragments on the way out
    length = len(payload)
    header = bytearray([first])

    flag = 0x80 if mask else 0x00
    if length < 126:
        header.append(flag | length)
    elif length < (1 << 16):
        header.append(flag | 126)
        header += struct.pack("!H", length)
    else:
        header.append(flag | 127)
        header += struct.pack("!Q", length)

    if not mask:
        return bytes(header) + payload
    key = os.urandom(4)
    masked = bytes(b ^ key[i % 4] for i, b in enumerate(payload))
    return bytes(header) + key + masked


class FrameReader:
    """Reads WebSocket messages off a socket, reassembling fragments.

    `expect_masked` says which side of the connection this is. A client must
    mask every frame it sends and a server must never mask one, so the two
    roles enforce opposite rules -- and a reader that assumes one of them is
    a reader that only works in one direction.
    """

    def __init__(self, sock: socket.socket, expect_masked: bool = True) -> None:
        self.sock = sock
        self.expect_masked = expect_masked
        self._buffer = bytearray()

    def _exactly(self, count: int) -> bytes:
        """`count` bytes, or an error. Never a short read.

        The same care as the MQTT reader, for the same reason: `recv`
        returning fewer bytes than asked is normal, and treating it as an
        error or as the whole message is the bug that only appears under
        load.
        """
        while len(self._buffer) < count:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise WebSocketError("the connection closed")
            self._buffer += chunk
        out = bytes(self._buffer[:count])
        del self._buffer[:count]
        return out

    def frame(self) -> tuple[int, bool, bytes]:
        """One frame as (opcode, final, payload)."""
        first, second = self._exactly(2)
        opcode = first & 0x0F
        final = bool(first & 0x80)
        masked = bool(second & 0x80)
        length = second & 0x7F

        if length == 126:
            length = struct.unpack("!H", self._exactly(2))[0]
        elif length == 127:
            length = struct.unpack("!Q", self._exactly(8))[0]
        if length > MAX_MESSAGE:
            raise WebSocketError(f"a frame claims {length} bytes, past the "
                                 f"{MAX_MESSAGE} limit")

        key = self._exactly(4) if masked else b""
        payload = self._exactly(length) if length else b""
        if masked:
            payload = bytes(b ^ key[i % 4] for i, b in enumerate(payload))
        elif self.expect_masked and opcode != CLOSE:
            # A client that does not mask is a protocol error, and a
            # conforming server closes on it. Said plainly because the
            # symptom otherwise is "it works from Node and not from a
            # browser", which is a long evening.
            raise WebSocketError("a client frame arrived unmasked")
        elif masked and not self.expect_masked:
            raise WebSocketError("a server frame arrived masked")
        return opcode, final, payload

    def message(self) -> tuple[int, bytes]:
        """One whole message, following fragments. Answers pings itself.

        Returns (opcode, payload). A CLOSE comes back as such rather than
        raising: the caller decides how to shut down, and a broker wants to
        drop that client's subscriptions before it goes.
        """
        opcode, final, payload = self.frame()

        while opcode in (PING, PONG, CLOSE):
            if opcode == CLOSE:
                return CLOSE, payload
            if opcode == PING:
                # Answered here rather than handed up: a pong is a protocol
                # obligation with no meaning to anything above, and a socket
                # that does not answer one gets closed.
                self.sock.sendall(encode_frame(payload, PONG))
            opcode, final, payload = self.frame()

        if final:
            return opcode, payload

        # Fragmented. Nothing here sends fragments, but a browser is entitled
        # to, and a message that arrives in two pieces must not become two
        # half MQTT packets.
        parts = [payload]
        total = len(payload)
        while not final:
            next_opcode, final, chunk = self.frame()
            if next_opcode in (PING, PONG):
                if next_opcode == PING:
                    self.sock.sendall(encode_frame(chunk, PONG))
                final = False
                continue
            if next_opcode == CLOSE:
                return CLOSE, b""
            if next_opcode != CONTINUATION:
                raise WebSocketError("a new message started before the last "
                                     "one finished")
            total += len(chunk)
            if total > MAX_MESSAGE:
                raise WebSocketError("a fragmented message grew past the limit")
            parts.append(chunk)
        return opcode, b"".join(parts)


def close_frame(code: int = 1000, reason: str = "") -> bytes:
    """A close frame, with the status code first as the RFC requires."""
    return encode_frame(struct.pack("!H", code) + reason.encode("utf-8")[:120],
                        CLOSE)
