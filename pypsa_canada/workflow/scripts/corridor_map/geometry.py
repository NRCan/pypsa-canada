"""Bus placement, voltage labels, and corridor curve geometry."""

import math
import re

from .settings import SELF_LOOP_RADIUS_M


def canonical_pair(a: str, b: str):
    """Return a sorted pair of bus names for use as a corridor key."""
    return tuple(sorted([str(a).strip(), str(b).strip()]))


def line_voltage_kv(name: str):
    """Extract a trailing kV integer from a line name, or return None."""
    m = re.search(r"_(\d{2,4})\s*$", str(name).strip())
    return int(m.group(1)) if m else None


def voltage_mix_label(kvs):
    """Format a voltage label, ignoring missing values."""
    kvs = sorted({k for k in kvs if k is not None})
    if not kvs:
        return "mixed kV"
    if len(kvs) == 1:
        return f"{kvs[0]} kV"
    return f"{'+'.join(map(str, kvs))} kV"


def bus_voltage_kv(bus_name: str):
    """Extract a trailing voltage integer from a bus name, or return None."""
    m = re.search(r"(\d{2,4})\s*$", str(bus_name).strip())
    return int(m.group(1)) if m else None


def jitter_bus(lat, lon, position, group_size, jitter_m):
    """Spread co-located buses deterministically around a circle."""
    if group_size <= 1:
        return lat, lon
    angle = 2 * math.pi * (position / group_size)
    dlat = (jitter_m / 111320.0) * math.cos(angle)
    dlon = (jitter_m / (111320.0 * max(0.1, math.cos(math.radians(lat))))) * math.sin(
        angle
    )
    return lat + dlat, lon + dlon


def bearing(lat1, lon1, lat2, lon2):
    """Compute the initial forward bearing in radians clockwise from north."""
    dlon = math.radians(lon2 - lon1)
    lat1r, lat2r = math.radians(lat1), math.radians(lat2)
    y = math.sin(dlon) * math.cos(lat2r)
    x = math.cos(lat1r) * math.sin(lat2r) - math.sin(lat1r) * math.cos(
        lat2r
    ) * math.cos(dlon)
    return math.atan2(y, x)


def offset_point(lat, lon, theta, offset_m, sign=1):
    """Displace coordinates by metres in direction theta using a local projection."""
    dlat = (offset_m / 111320.0) * sign
    dlon = (offset_m / (111320.0 * max(0.1, math.cos(math.radians(lat))))) * sign
    return lat + dlat * math.cos(theta), lon + dlon * math.sin(theta)


def offset_midpoint(lat1, lon1, lat2, lon2, offset_m=3000.0, sign=1):
    """Return the midpoint displaced perpendicular to the corridor."""
    latm = (lat1 + lat2) / 2.0
    lonm = (lon1 + lon2) / 2.0
    theta = bearing(lat1, lon1, lat2, lon2) + math.pi / 2.0
    return offset_point(latm, lonm, theta, offset_m, sign=sign)


def approx_distance_m(lat1, lon1, lat2, lon2):
    """Estimate distance in metres using the equirectangular approximation."""
    R = 6371000.0
    x = math.radians(lon2 - lon1) * math.cos(math.radians((lat1 + lat2) / 2.0))
    y = math.radians(lat2 - lat1)
    return R * math.sqrt(x * x + y * y)


def make_curve(
    lat1, lon1, lat2, lon2, offset_m, sign=1, self_loop_radius_m=SELF_LOOP_RADIUS_M
):
    """Build a three-point corridor path or a five-point self-loop."""
    if abs(lat1 - lat2) < 1e-9 and abs(lon1 - lon2) < 1e-9:
        return [
            offset_point(lat1, lon1, ang, self_loop_radius_m)
            for ang in (0, math.pi / 2, math.pi, 3 * math.pi / 2, 0)
        ]
    latc, lonc = offset_midpoint(lat1, lon1, lat2, lon2, offset_m=offset_m, sign=sign)
    return [(lat1, lon1), (latc, lonc), (lat2, lon2)]


def parallel_offsets(n: int, base_offset_m: float, step_m: float):
    """Generate alternating signed offsets for parallel physical lines."""
    offsets = [(+1, base_offset_m)]
    for k in range(1, n):
        sign = -1 if k % 2 == 1 else +1
        extra = ((k + 1) // 2) * step_m
        offsets.append((sign, base_offset_m + extra))
    return offsets
