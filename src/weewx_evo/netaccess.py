"""Who may talk to us.

Almost every weather station is on a home network: a small machine in a shed
or a cupboard, a console on the same wifi, and somebody wanting to look at the
settings from a laptop in the kitchen. Binding to localhost makes that need an
SSH tunnel, which is one thing too many to explain. Binding to everything and
hoping for the best is how a configuration page ends up on Shodan.

So: bind to everything, answer only what is on a private network. That covers
the shed, the kitchen laptop, Docker, and any reverse proxy -- a proxy always
connects from loopback or a private address, so putting one in front keeps
working without a thought.

Reaching it from the open internet is then a decision somebody makes on
purpose, rather than a default they never saw:

    --allow any                     everything, with a warning in the log
    --allow 10.0.0.0/8,203.0.113.4  exactly these

Loopback is always allowed. A rule that can lock the machine out of its own
service is a rule that will.

This is not authentication and does not replace the token. It narrows who can
try, which is worth having: a token that is only ever offered to the network
it belongs on cannot be guessed at from elsewhere.
"""

from __future__ import annotations

import ipaddress
import logging

log = logging.getLogger(__name__)

#: Networks that count as "not the open internet".
#:
#: The obvious RFC 1918 ranges, plus three that matter in practice and are
#: missed often enough to be worth naming:
#:
#:   100.64.0.0/10  carrier-grade NAT, which is what Tailscale hands out
#:   169.254.0.0/16 link-local, i.e. two machines and a cable, no DHCP
#:   fc00::/7       the IPv6 equivalent of 192.168, and increasingly the
#:                  address a modern home router actually uses
PRIVATE = tuple(ipaddress.ip_network(n) for n in (
    "127.0.0.0/8", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16",
    "169.254.0.0/16", "100.64.0.0/10",
    "::1/128", "fc00::/7", "fe80::/10",
))

LOOPBACK = tuple(ipaddress.ip_network(n) for n in ("127.0.0.0/8", "::1/128"))


class Access:
    """Which addresses are answered."""

    __slots__ = ("described", "everyone", "networks")

    def __init__(self, networks: tuple = PRIVATE, everyone: bool = False,
                 described: str = "private networks") -> None:
        self.networks = networks
        self.everyone = everyone
        self.described = described

    @classmethod
    def parse(cls, setting: str | None) -> Access:
        """From 'private' (the default), 'any', or a list of addresses.

        A list may hold networks (`10.0.0.0/8`) or single addresses
        (`203.0.113.4`), separated by commas.

        **Loopback is added whatever the list says**, and that is deliberate
        twice over: a reverse proxy connects from it, so a list that left it
        out would make Caddy the one thing that cannot get through -- and a
        service configured from this machine must never be able to lock this
        machine out of it. `loopback` narrows to it; nothing widens away from
        it.
        """
        text = (setting or "private").strip().lower()
        if text in ("loopback", "this-machine", "here"):
            # Narrower than `private`, and a genuinely different answer: the
            # local network is other people's computers, and for something
            # like the broker's publishing path that is exactly the
            # difference that matters.
            return cls(networks=LOOPBACK, described="this machine only")
        if text in ("private", "", "lan", "local"):
            return cls()
        if text in ("any", "all", "0.0.0.0/0", "*"):
            return cls(everyone=True, described="anywhere")

        networks = list(LOOPBACK)
        for part in setting.split(","):  # type: ignore[union-attr]
            part = part.strip()
            if not part:
                continue
            try:
                networks.append(ipaddress.ip_network(part, strict=False))
            except ValueError:
                raise ValueError(
                    f"{part!r} is not an address or a network. Write them like "
                    "10.0.0.0/8 or 192.168.1.50, separated by commas.") from None
        if len(networks) == len(LOOPBACK):
            raise ValueError("no addresses were given")
        return cls(networks=tuple(networks),
                   described=", ".join(str(n) for n in networks[len(LOOPBACK):]))

    def allows(self, address: str) -> bool:
        if self.everyone:
            return True
        try:
            ip = ipaddress.ip_address(address)
        except ValueError:
            # Something that is not an address at all. Unix sockets and test
            # doubles land here; both are local by construction.
            return address in ("", "?", "local")
        # An IPv4 address arriving on a dual-stack socket looks like
        # ::ffff:192.168.1.5, and would otherwise match no IPv4 rule.
        mapped = getattr(ip, "ipv4_mapped", None)
        if mapped is not None:
            ip = mapped
        return any(ip in network for network in self.networks)

    def __str__(self) -> str:
        return self.described


#: What a service gets when nothing was configured.
PRIVATE_ONLY = Access()
EVERYONE = Access(everyone=True, described="anywhere")
#: This machine and nothing else. For a path that has exactly one legitimate
#: user and it is in this process.
LOOPBACK_ONLY = Access(networks=LOOPBACK, described="this machine only")


def warn_if_open(access: Access, what: str) -> None:
    """Say so, once, at startup, when a service answers the whole internet."""
    if access.everyone:
        log.warning("%s answers any address. Whoever reaches the port has only "
                    "the token in their way.", what)
