"""Parse authored maps, archetypes, regions, and terrain metadata."""

import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from .config import ARCH_ROOT, MAP_ROOT, ROOT


def fields(lines: list[str]) -> dict[str, list[str]]:
    """Parse scalar fields while preserving repeated Atrinik attributes."""
    result: dict[str, list[str]] = defaultdict(list)
    in_message = False
    message = []
    for raw in lines:
        line = raw.rstrip("\n")
        if in_message:
            if line == "endmsg":
                result["msg"].append("\n".join(message).strip())
                in_message = False
                message = []
            else:
                message.append(line)
            continue
        if line == "msg":
            in_message = True
            continue
        key, separator, value = line.partition(" ")
        if separator:
            result[key].append(value.strip())
    return dict(result)


def parse_blocks(path: Path) -> dict:
    """Parse an authored map into its header and nested arch objects."""
    stack: list[dict] = []
    roots: list[dict] = []
    header = None
    with path.open(errors="replace") as handle:
        for lineno, raw in enumerate(handle, 1):
            line = raw.rstrip("\n")
            if line.startswith("arch "):
                node = {"arch": line[5:], "attrs_raw": [], "children": [], "line": lineno}
                if stack:
                    stack[-1]["children"].append(node)
                else:
                    roots.append(node)
                stack.append(node)
            elif line == "end":
                if stack:
                    node = stack.pop()
                    node["attrs"] = fields(node.pop("attrs_raw"))
                    if node["arch"] == "map" and header is None:
                        header = node
            elif stack:
                stack[-1]["attrs_raw"].append(raw)
    return {"header": header, "objects": [node for node in roots if node is not header]}


def flatten(nodes: list[dict], parent: dict | None = None):
    for node in nodes:
        yield node, parent
        yield from flatten(node["children"], node)


def one(attrs: dict, key: str, default=None):
    values = attrs.get(key)
    return values[-1] if values else default


def load_archetypes(arch_root: Path = ARCH_ROOT, root: Path = ROOT) -> dict[str, dict]:
    result = {}
    for path in arch_root.rglob("*.arc"):
        lines = path.read_text(errors="replace").splitlines()
        index = 0
        while index < len(lines):
            if not lines[index].startswith("Object "):
                index += 1
                continue
            name = lines[index][7:]
            index += 1
            block = []
            while index < len(lines) and lines[index] != "end":
                block.append(lines[index] + "\n")
                index += 1
            attrs = fields(block)
            result[name] = {
                "path": str(path.relative_to(root)),
                "attrs": {key: values[-1] for key, values in attrs.items() if values},
            }
            index += 1
    return result


def _number(value, default=0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _integer(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _last(attrs: dict, key: str, default=None):
    value = attrs.get(key, default)
    if isinstance(value, list):
        return value[-1] if value else default
    return value


def merged_attrs(node: dict, archetypes: dict[str, dict]) -> dict[str, str]:
    attrs = dict(archetypes.get(node["arch"], {}).get("attrs", {}))
    mask_values = node["attrs"].get("amask", [])
    if mask_values:
        attrs.update(archetypes.get(mask_values[-1], {}).get("attrs", {}))
    attrs.update({key: values[-1] for key, values in node["attrs"].items() if values})
    return attrs


def source_map_files(map_root: Path = MAP_ROOT) -> list[Path]:
    result = []
    for path in map_root.rglob("*"):
        if not path.is_file():
            continue
        try:
            with path.open("rb") as handle:
                if handle.read(9) == b"arch map\n":
                    result.append(path)
        except OSError:
            continue
    return sorted(result)


def parse_map_header(path: Path) -> dict[str, list[str]]:
    """Read only the leading map object, without parsing the map contents."""
    block = []
    with path.open(errors="replace") as handle:
        if handle.readline().rstrip("\n") != "arch map":
            return {}
        for raw in handle:
            if raw.rstrip("\n") == "end":
                break
            block.append(raw)
    return fields(block)


@dataclass(frozen=True)
class MapLocation:
    path: str
    name: str
    region: str
    parent: str
    prefix: str
    x: int
    y: int
    z: int


@dataclass
class TerrainMap:
    """Static walkability needed by farming route and arena estimates."""

    width: int
    height: int
    terrain: dict[tuple[int, int], int] = field(default_factory=dict)
    blocked: set[tuple[int, int]] = field(default_factory=set)

    def walkable(self, x: int, y: int) -> bool:
        return (
            0 <= x < self.width and 0 <= y < self.height and
            bool(self.terrain.get((x, y), 0) & 1) and
            (x, y) not in self.blocked
        )


@dataclass
class TerrainIndex:
    nodes: dict[str, TerrainMap] = field(default_factory=dict)


class LocationIndex:
    """Resolve internal map paths into regions and nearby named world tiles."""

    GENERIC_NAMES = {"world", "the world"}

    @staticmethod
    def world_coordinates(name: str) -> tuple[str, int, int, int] | None:
        """Parse supported coordinate-grid authored-map conventions."""
        match = re.fullmatch(
            r"(world|underground_city)_(-?\d+)_(-?\d+)(?:_(-?\d+))?",
            name,
        )
        if match is None:
            return None
        prefix, raw_x, raw_y, raw_z = match.groups()
        return prefix, int(raw_x), int(raw_y), int(raw_z or 0)

    def __init__(self, root: Path = ROOT):
        self.root = root
        self.region_names, self.region_parents = self._load_regions(
            root / "maps" / "regions.reg")
        self.maps: dict[str, MapLocation] = {}
        self.grids: dict[tuple[str, str, int], list[MapLocation]] = defaultdict(list)
        for path in source_map_files(root / "maps"):
            attrs = parse_map_header(path)
            relative = str(path.relative_to(root))
            coordinates = self.world_coordinates(path.name)
            parent = str(path.parent.relative_to(root))
            prefix = ""
            x = y = z = 0
            if coordinates is not None:
                prefix, x, y, z = coordinates
            location = MapLocation(
                path=relative,
                name=one(attrs, "name", path.name) or path.name,
                region=one(attrs, "region", "") or "",
                parent=parent,
                prefix=prefix,
                x=x,
                y=y,
                z=z,
            )
            self.maps[relative] = location
            if coordinates is not None:
                self.grids[(parent, prefix, z)].append(location)

    @staticmethod
    def _load_regions(path: Path) -> tuple[dict[str, str], dict[str, str]]:
        names = {}
        parents = {}
        current = None
        for raw in path.read_text(errors="replace").splitlines():
            key, separator, value = raw.partition(" ")
            if key == "region" and separator:
                current = value.strip()
            elif key == "longname" and separator and current:
                names[current] = value.strip()
            elif key == "parent" and separator and current:
                parents[current] = value.strip()
            elif raw == "end":
                current = None
        return names, parents

    @staticmethod
    def _normalized_region(value: str) -> str:
        return " ".join(re.sub(r"[_-]+", " ", value).casefold().split())

    def region_is_excluded(self, region: str, filters: tuple[str, ...]) -> bool:
        """Match IDs/names and inherit exclusions through the region tree."""
        normalized_filters = tuple(
            self._normalized_region(value) for value in filters if value.strip())
        current = region
        seen = set()
        while current and current not in seen:
            seen.add(current)
            candidates = (
                self._normalized_region(current),
                self._normalized_region(self.region_names.get(current, "")),
            )
            if any(query in candidate for query in normalized_filters
                   for candidate in candidates):
                return True
            current = self.region_parents.get(current, "")
        return False

    @staticmethod
    def _direction(dx: int, dy: int) -> str:
        vertical = "north" if dy < 0 else "south" if dy > 0 else ""
        horizontal = "west" if dx < 0 else "east" if dx > 0 else ""
        return vertical + horizontal if vertical and horizontal else vertical or horizontal

    def describe(self, paths: tuple[str, ...], fallback_region: str,
                 fallback_name: str) -> tuple[str, tuple[str, ...]]:
        members = [self.maps[path] for path in paths if path in self.maps]
        region_ids = {member.region for member in members if member.region}
        if len(region_ids) == 1:
            region_id = next(iter(region_ids))
            area = self.region_names.get(region_id, fallback_name)
        else:
            area = self.region_names.get(fallback_region, fallback_name)

        member_names = {member.name.casefold() for member in members}
        member_paths = {member.path for member in members}
        nearest: dict[str, tuple[int, str]] = {}
        for member in members:
            if not member.prefix:
                continue
            for candidate in self.grids.get((member.parent, member.prefix, member.z), []):
                if candidate.path in member_paths:
                    continue
                landmark = self.region_names.get(candidate.region, candidate.name)
                if (candidate.name.casefold() in member_names and
                        candidate.region in region_ids):
                    continue
                if landmark.casefold() in self.GENERIC_NAMES or landmark == area:
                    continue
                distance = abs(member.x - candidate.x) + abs(member.y - candidate.y)
                if not (1 <= distance <= 5):
                    continue
                direction = self._direction(member.x - candidate.x,
                                            member.y - candidate.y)
                if not direction:
                    continue
                previous = nearest.get(landmark)
                value = (distance, direction)
                if previous is None or value < previous:
                    nearest[landmark] = value

        landmarks = tuple(
            f"{distance} tile{'s' if distance != 1 else ''} {direction} of {name}"
            for name, (distance, direction) in sorted(
                nearest.items(), key=lambda item: (item[1][0], item[0]))[:3]
        )
        location = area
        if landmarks:
            location += "; " + ", ".join(landmarks)
        return location, landmarks
