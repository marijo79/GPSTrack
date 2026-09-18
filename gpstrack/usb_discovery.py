"""Discover a USB-tethered phone's IP via its default route.

When a phone shares its connection over USB tethering, it acts as the
default gateway for that link. The interface name varies across
reconnects/machines (enx<mac>, usb0, rndis0, ...) and even the host's own
IP on that link can change, but the phone's IP as read from the *current*
default route stays correct regardless -- so there's no need to hardcode
or manually update an IP address.
"""
from __future__ import annotations

from typing import Iterable, Optional

ROUTE_TABLE_PATH = "/proc/net/route"
USB_INTERFACE_PREFIXES = ("enx", "usb", "rndis")


def _hex_to_ip(hex_str: str) -> str:
    # /proc/net/route stores addresses as little-endian 32-bit hex.
    value = int(hex_str, 16)
    return ".".join(str((value >> (8 * i)) & 0xFF) for i in range(4))


def find_usb_gateway(
    interface_prefixes: Iterable[str] = USB_INTERFACE_PREFIXES,
    route_table_path: str = ROUTE_TABLE_PATH,
) -> Optional[str]:
    """Return the default gateway IP on a USB-tethering-looking interface, or None."""
    try:
        with open(route_table_path) as f:
            lines = f.readlines()
    except OSError:
        return None

    prefixes = tuple(interface_prefixes)
    for line in lines[1:]:  # skip header
        fields = line.split()
        if len(fields) < 3:
            continue
        iface, destination, gateway = fields[0], fields[1], fields[2]
        if destination != "00000000":  # only interested in default routes
            continue
        if not iface.startswith(prefixes):
            continue
        return _hex_to_ip(gateway)
    return None
