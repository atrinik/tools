"""Per-map and per-zone difficulty report for map makers and map editors.

``python3 -m farming_analyzer report`` rates authored maps by level band and
combat style with the encounter model (``encounter.py``) and a documented
reference character, and lists hotspots and the reasons behind each rating.
``--json`` emits the schema documented in the README ("Difficulty report").
"""

from __future__ import annotations

import argparse
import json
import math
import re
from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path

from . import encounter as enc
from .analyzer import FarmingAnalyzer
from .config import PHYSICAL_ATTACKS, ROOT, SERVER_ROOT
from .models import AnalysisOptions
from .presentation import parse_time
from .sources import source_map_files

REPORT_SCHEMA = "atrinik.farming_analyzer.difficulty_report"
REPORT_SCHEMA_VERSION = 1
# Monsters this many levels above the band mark it as out of band.
BAND_ALLOWANCE = 5
# Default bands: the map's average monster level rounded to five, and five
# levels either side.
AUTO_OFFSETS = (-5, 0, 5)
AOE_TARGETS = 4


@dataclass(frozen=True)
class ReferenceCharacter:
    """A generic character per level band, scaled linearly with level.

    The defaults are calibrated on the playtester character Sera at level
    37 (333 HP, AC 58, about 25 melee DPS with a 3 s weapon, 36-50%
    physical protection, about 5.5 HP/s from minor healing). They describe a
    modestly geared character, not an optimal one.
    """

    hp_per_level: float = 9.0
    ac_per_level: float = 1.6
    dps_per_level: float = 0.7
    healing_per_level: float = 0.15
    physical_protection: int = 35
    speed: float = 1.0

    def options(self, level: int, base: AnalysisOptions) -> AnalysisOptions:
        damage = max(1.0, self.dps_per_level * level * 2.0)
        protections = tuple(sorted(
            (attack, self.physical_protection) for attack in PHYSICAL_ATTACKS))
        return AnalysisOptions(
            player_level=level, dps=damage / 2.0, seconds_per_kill=2.0,
            seconds_per_map=10.0, shop_sell_fraction=0.20,
            at_minute=base.at_minute, attack_type="physical_average",
            minimum_spawns=1, minimum_xp_fraction=0.0, max_level_gap=200,
            circuit_size=1, path_pattern=None, include_static=base.include_static,
            character_level=level, player_ac=round(self.ac_per_level * level),
            player_protections=protections, melee_damage=None, weapon_class=None,
            weapon_speed=None, weapon_class_range=20,
            player_attacks=tuple((attack, 25) for attack in PHYSICAL_ATTACKS),
            damage_per_attack=damage, attack_delay=2.0,
            max_health=self.hp_per_level * level, character_speed=self.speed,
            model_approach=False, healing_per_second=self.healing_per_level * level,
            kite_distance=base.kite_distance)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python3 -m farming_analyzer report",
        description="Rate authored maps by level band and combat style for map makers.")
    parser.add_argument("--content-root", type=Path, default=ROOT)
    parser.add_argument("--server-root", type=Path, default=SERVER_ROOT)
    parser.add_argument("--path", dest="path_pattern",
                        help="case-insensitive map-path regex (default: every map with monsters)")
    parser.add_argument("--exclude-region", action="append", default=[], metavar="NAME")
    parser.add_argument("--levels", default="auto",
                        help="comma-separated level bands, or 'auto' for each map's average "
                             "monster level rounded to 5 and 5 either side (default)")
    parser.add_argument("--styles", default=",".join(enc.STYLE_NAMES),
                        help=f"comma-separated styles (default: {','.join(enc.STYLE_NAMES)})")
    parser.add_argument("--time", type=parse_time, default=parse_time("12:00"), metavar="HH:MM")
    parser.add_argument("--include-static", action="store_true")
    parser.add_argument("--kite-distance", type=int, default=enc.DEFAULT_KITE_DISTANCE)
    defaults = ReferenceCharacter()
    parser.add_argument("--hp-per-level", type=float, default=defaults.hp_per_level)
    parser.add_argument("--ac-per-level", type=float, default=defaults.ac_per_level)
    parser.add_argument("--dps-per-level", type=float, default=defaults.dps_per_level)
    parser.add_argument("--healing-per-level", type=float, default=defaults.healing_per_level)
    parser.add_argument("--physical-protection", type=int,
                        default=defaults.physical_protection)
    parser.add_argument("--speed", type=float, default=defaults.speed,
                        help="displayed movement speed of the reference character")
    parser.add_argument("--json", action="store_true", help="emit the JSON report")
    return parser


def _levels(text: str) -> tuple[int, ...] | None:
    if text.strip().lower() == "auto":
        return None
    try:
        levels = tuple(sorted({int(item) for item in text.split(",") if item.strip()}))
    except ValueError as exc:
        raise SystemExit("levels must be 'auto' or comma-separated integers") from exc
    if not levels or any(not 1 <= level <= 200 for level in levels):
        raise SystemExit("levels must be between 1 and 200")
    return levels


def _round(value: float, digits: int = 3) -> float | None:
    return round(value, digits) if math.isfinite(value) else None


def _spawn_record(spawn: enc.EncounterSpawn, pull: enc.PullEstimate | None) -> dict:
    box = None
    if spawn.wander_box is not None:
        x0, y0, x1, y1 = spawn.wander_box
        box = {"x0": x0, "y0": y0, "x1": x1, "y1": y1, "tiles": len(spawn.wander_tiles)}
    return {
        "x": spawn.x, "y": spawn.y, "name": spawn.name, "level": spawn.level,
        "aggressive": _round(spawn.aggressive),
        "detection_radius": spawn.radius,
        "engaged_radius": spawn.engaged_radius,
        "chase_range": spawn.chase_range,
        "link_chance": _round(spawn.link_chance, 4),
        "link_group": spawn.link_group,
        "faction": spawn.faction,
        "engaged_speed": _round(spawn.engaged_speed),
        "idle_speed": _round(spawn.idle_speed),
        "wander": box,
        "caster": spawn.caster, "ranged": spawn.ranged,
        "damage_types": list(spawn.damage_types),
        "melee_types": list(spawn.melee_types),
        "spells": list(spawn.spells),
        "pull": None if pull is None else {
            "x": pull.x, "y": pull.y, "expected": _round(pull.expected, 2),
            "worst": pull.worst},
    }


def _terrain_record(terrain: enc.TerrainStructure) -> dict:
    record = asdict(terrain)
    record["doorways"] = [list(tile) for tile in terrain.doorways]
    record["open_field_center"] = (list(terrain.open_field_center)
                                   if terrain.open_field_center else None)
    for key in ("walkable_fraction", "open_fraction", "kite_room"):
        record[key] = _round(record[key])
    return record


def build_report(analyzer: FarmingAnalyzer, args: argparse.Namespace) -> dict:
    """Return the JSON-ready difficulty report."""
    styles = tuple(item.strip() for item in args.styles.split(",") if item.strip())
    unknown = [item for item in styles if item not in enc.STYLE_NAMES]
    if unknown or not styles:
        raise SystemExit(f"unknown style(s): {', '.join(unknown) or 'none given'}; "
                         f"choose from {', '.join(enc.STYLE_NAMES)}")
    explicit = _levels(args.levels)
    reference = ReferenceCharacter(
        args.hp_per_level, args.ac_per_level, args.dps_per_level,
        args.healing_per_level, args.physical_protection, args.speed)
    probe = reference.options(1, _base_options(args))
    matcher = re.compile(args.path_pattern, re.IGNORECASE) if args.path_pattern else None
    map_prefix = analyzer.map_root.relative_to(analyzer.root).as_posix()
    # First pass: maps with hostile spawns and their monster levels, which do
    # not depend on the character.
    maps: dict[str, dict] = {}
    for path in source_map_files(analyzer.map_root):
        relative = str(path.relative_to(analyzer.root))
        if matcher and matcher.search(relative) is None:
            continue
        location = analyzer.locations.maps.get(relative)
        if location is not None and analyzer.locations.region_is_excluded(
                location.region, tuple(args.exclude_region)):
            continue
        key = "/" + path.relative_to(analyzer.map_root).as_posix()
        if key not in analyzer._world().nodes:
            continue
        spawns, _competitors = analyzer._spawns_cached(key, probe, args.include_static)
        if not spawns:
            continue
        levels = [profile.level for spawn in spawns for _p, profile in spawn.candidates]
        average = sum(spawn.weighted("level") for spawn in spawns) / len(spawns)
        bands = explicit or tuple(sorted({
            max(1, min(200, 5 * round(average / 5) + offset)) for offset in AUTO_OFFSETS}))
        node = analyzer._world().nodes[key]
        maps[key] = {
            "path": relative,
            "name": location.name if location else path.name,
            "region": location.region if location else "",
            "width": node.width, "height": node.height,
            "monster_levels": {"min": min(levels), "max": max(levels),
                               "average": round(average, 1)},
            "bands": bands, "ratings": [], "spawns": [], "hotspots": [], "terrain": None,
            "_spawn_count": len(spawns),
        }
    by_level: dict[int, list[str]] = defaultdict(list)
    for key, record in maps.items():
        for level in record["bands"]:
            by_level[level].append(key)
    for level in sorted(by_level):
        options = reference.options(level, _base_options(args))
        for key in by_level[level]:
            record = maps[key]
            spawns, _competitors = analyzer._spawns_cached(key, options, args.include_static)
            for style in styles:
                aoe = AOE_TARGETS if enc.style_profiles()[style].aoe else 1
                model = analyzer.map_encounter(key, spawns, options, style, aoe)
                if model is None:
                    continue
                encounter_options = analyzer.encounter_options(options, style, aoe)
                record["ratings"].append(_rating(model, encounter_options, options, level,
                                                 record["monster_levels"]["max"]))
                anchor = min(record["bands"], key=lambda band: (
                    abs(band - record["monster_levels"]["average"]), band))
                if level == anchor and style == styles[0]:
                    pulls = {pull.target: pull for pull in model.pulls}
                    record["terrain"] = _terrain_record(model.terrain)
                    record["spawns"] = [
                        _spawn_record(model.spawns[index], pulls.get(index))
                        for index in model.own]
                    record["hotspots"] = enc.hotspots(model)
                    record["hotspot_basis"] = {"level": level, "style": style}
    result_maps = []
    for key in sorted(maps, key=lambda item: maps[item]["path"]):
        record = maps[key]
        record.pop("_spawn_count")
        record["levels"] = list(record.pop("bands"))
        result_maps.append(record)
    return {
        "schema": REPORT_SCHEMA,
        "schema_version": REPORT_SCHEMA_VERSION,
        "generator": {"tool": "farming_analyzer", "command": "report",
                      "content_root": str(args.content_root)},
        "reference_character": {
            "hp": f"{reference.hp_per_level:g} x level",
            "ac": f"{reference.ac_per_level:g} x level",
            "dps": f"{reference.dps_per_level:g} x level",
            "healing_per_second": f"{reference.healing_per_level:g} x level",
            "physical_protection": reference.physical_protection,
            "speed": reference.speed,
            "aoe_targets": AOE_TARGETS,
            "kite_distance": args.kite_distance,
        },
        "styles": {name: profile.description
                   for name, profile in enc.style_profiles(args.kite_distance).items()
                   if name in styles},
        "rating_scale": {"easy": ">= 0.85", "fair": ">= 0.65", "hard": ">= 0.40",
                         "deadly": "> 0", "lethal": "0"},
        "maps": result_maps,
        "zones": _zones(result_maps, styles),
        "warnings": sorted(analyzer.source_warnings),
    }


def _base_options(args: argparse.Namespace) -> AnalysisOptions:
    return AnalysisOptions(
        player_level=1, dps=1.0, seconds_per_kill=2.0, seconds_per_map=10.0,
        shop_sell_fraction=0.2, at_minute=args.time, attack_type="physical_average",
        minimum_spawns=1, minimum_xp_fraction=0.0, max_level_gap=200, circuit_size=1,
        path_pattern=None, include_static=args.include_static, character_level=1,
        player_ac=1, player_protections=(), melee_damage=None, weapon_class=None,
        weapon_speed=None, weapon_class_range=20, player_attacks=(),
        kite_distance=args.kite_distance)


def _rating(model: enc.EncounterModel, encounter_options: enc.EncounterOptions,
            options: AnalysisOptions, level: int, max_level: int) -> dict:
    health = options.max_health
    expected = enc.safety_from_need(model.need, health)
    bad = enc.bad_pull_safety(model.worst_need, health)
    safety = enc.blended_safety(expected, bad)
    hardest = model.hardest()
    reasons = enc.reasons(model, encounter_options, health)
    out_of_band = max_level > level + BAND_ALLOWANCE
    if out_of_band:
        reasons.insert(0, f"monsters up to L{max_level}, above L{level}+{BAND_ALLOWANCE}")
    return {
        "level": level, "style": model.style,
        "safety": _round(safety), "expected_safety": _round(expected),
        "bad_pull_safety": _round(bad), "rating": enc.rating(safety),
        "expected_attackers": _round(model.expected_pack, 2),
        "mean_attackers": _round(model.mean_expected_pack, 2),
        "bad_pull_attackers": model.worst_pack,
        "expected_need": _round(model.need, 1),
        "bad_pull_need": _round(model.worst_need, 1),
        "health": health,
        "hardest_pull": None if hardest is None else {
            "x": hardest.x, "y": hardest.y,
            "target": [model.spawns[hardest.target].x, model.spawns[hardest.target].y],
            "monster": model.spawns[hardest.target].name},
        "out_of_band": out_of_band,
        "reasons": reasons,
    }


def _zones(maps: list[dict], styles: tuple[str, ...]) -> list[dict]:
    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for record in maps:
        groups[(record["region"], record["name"])].append(record)
    zones = []
    for (region, name), members in sorted(groups.items()):
        ratings = []
        levels = sorted({rating["level"] for member in members for rating in member["ratings"]})
        for level in levels:
            for style in styles:
                rows = [(member["path"], rating) for member in members
                        for rating in member["ratings"]
                        if rating["level"] == level and rating["style"] == style]
                values = [rating["safety"] for _path, rating in rows
                          if rating["safety"] is not None]
                if not values:
                    continue
                hardest_path, hardest = min(rows, key=lambda item: (
                    item[1]["safety"] if item[1]["safety"] is not None else -1.0))
                ratings.append({
                    "level": level, "style": style, "maps": len(rows),
                    "min_safety": min(values),
                    "mean_safety": round(sum(values) / len(values), 3),
                    "max_safety": max(values),
                    "rating": enc.rating(min(values)),
                    "hardest_map": hardest_path,
                })
        zones.append({
            "region": region, "name": name,
            "maps": [member["path"] for member in members],
            "monster_levels": {
                "min": min(member["monster_levels"]["min"] for member in members),
                "max": max(member["monster_levels"]["max"] for member in members)},
            "ratings": ratings,
        })
    return zones


def render_text(report: dict) -> str:
    lines = [
        "Atrinik map difficulty report (encounter model, reference character "
        f"HP {report['reference_character']['hp']}, healing "
        f"{report['reference_character']['healing_per_second']} HP/s)",
        "Ratings: easy >= 85% safety, fair >= 65%, hard >= 40%, deadly > 0, lethal 0.",
        *(f"Warning: {warning}" for warning in report.get("warnings", ())),
        "",
    ]
    for zone in report["zones"]:
        levels = zone["monster_levels"]
        lines.append(f"{zone['name']} [{zone['region'] or 'no region'}] "
                     f"L{levels['min']}-{levels['max']}, {len(zone['maps'])} map(s)")
        for rating in zone["ratings"]:
            lines.append(
                f"  L{rating['level']:>3} {rating['style']:<12} {rating['rating']:<7} "
                f"safety {rating['min_safety']:.2f}-{rating['max_safety']:.2f}; "
                f"hardest {Path(rating['hardest_map']).name}")
    lines.append("")
    for record in report["maps"]:
        levels = record["monster_levels"]
        lines.append(f"{record['path']} — {record['name']} L{levels['min']}-{levels['max']}, "
                     f"{len(record['spawns'])} spawns, {record['width']}x{record['height']}")
        for rating in record["ratings"]:
            lines.append(
                f"  L{rating['level']:>3} {rating['style']:<12} {rating['rating']:<7} "
                f"{rating['safety']:.2f} (pull ~{rating['expected_attackers']:.1f}, bad "
                f"{rating['bad_pull_attackers']:g}): {rating['reasons'][1] if len(rating['reasons']) > 1 else ''}")
        for hotspot in record["hotspots"][:5]:
            where = (f" ({hotspot['x']}, {hotspot['y']})" if hotspot.get("x") is not None else "")
            lines.append(f"  * {hotspot['kind']}{where}: {hotspot['reason']}")
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    args = build_parser().parse_args(argv)
    if not (1 <= args.kite_distance <= 12):
        raise SystemExit("kite-distance must be between 1 and 12")
    if args.hp_per_level <= 0.0 or args.dps_per_level <= 0.0 or args.speed <= 0.0:
        raise SystemExit("hp, dps and speed per level must be positive")
    if args.healing_per_level < 0.0 or args.ac_per_level < 0.0:
        raise SystemExit("healing and AC per level cannot be negative")
    if not -100 <= args.physical_protection <= 95:
        raise SystemExit("physical protection must be between -100 and 95")
    analyzer = FarmingAnalyzer(args.content_root, args.server_root)
    report = build_report(analyzer, args)
    print(json.dumps(report, indent=2) if args.json else render_text(report))
    return 0
