"""Format farming results for human-readable and grouped output."""

import argparse
import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass

from .config import SERVER_ATTACK_TYPES
from .experience import ExperienceModel
from .models import AnalysisOptions, MapResult


def parse_time(value: str) -> int:
    match = re.fullmatch(r"(\d{1,2}):(\d{2})", value)
    if match is None:
        raise argparse.ArgumentTypeError("time must be HH:MM")
    hour, minute = map(int, match.groups())
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise argparse.ArgumentTypeError("time must be between 00:00 and 23:59")
    return hour * 60 + minute


def parse_player_protection(value: str) -> tuple[str, int]:
    attack, separator, raw_amount = value.partition("=")
    if not separator or attack not in SERVER_ATTACK_TYPES:
        choices = ", ".join(SERVER_ATTACK_TYPES)
        raise argparse.ArgumentTypeError(f"protection must be TYPE=PERCENT; TYPE is one of {choices}")
    try:
        amount = int(raw_amount)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("protection percentage must be an integer") from exc
    if not (-100 <= amount <= 100):
        raise argparse.ArgumentTypeError("protection percentage must be between -100 and 100")
    return attack, amount


def parse_melee_attack(value: str) -> tuple[str, int]:
    attack, separator, raw_amount = value.partition("=")
    if not separator or attack not in SERVER_ATTACK_TYPES:
        choices = ", ".join(SERVER_ATTACK_TYPES)
        raise argparse.ArgumentTypeError(
            f"melee attack must be TYPE=PERCENT; TYPE is one of {choices}")
    try:
        amount = int(raw_amount)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("melee attack percentage must be an integer") from exc
    if not (0 <= amount <= 255):
        raise argparse.ArgumentTypeError("melee attack percentage must be between 0 and 255")
    return attack, amount


def _fmt_number(value: float, decimals: int = 0) -> str:
    if not math.isfinite(value):
        return "n/a"
    return f"{value:,.{decimals}f}"


def _fmt_money(value: float) -> str:
    """Format a copper-denominated value as Atrinik gold/silver/copper."""
    if not math.isfinite(value):
        return "n/a"
    copper = max(0, int(round(value)))
    gold, copper = divmod(copper, 10_000)
    silver, copper = divmod(copper, 100)
    parts = []
    if gold:
        parts.append(f"{gold:,}g")
    if silver:
        parts.append(f"{silver}s")
    if copper or not parts:
        parts.append(f"{copper}c")
    return " ".join(parts)


def _maneuver_label(value: float) -> str:
    if value >= 0.75:
        return "open"
    if value >= 0.60:
        return "roomy"
    if value >= 0.40:
        return "constrained"
    return "obstructed"


@dataclass(frozen=True)
class ResultGroup:
    """Similar candidates collapsed into one farming decision."""
    region: str
    level_band: int
    level_min: int
    level_max: int
    candidates: tuple[MapResult, ...]
    representative: MapResult

    @property
    def label(self) -> str:
        return self.representative.location


def group_farming_results(results: list[MapResult], level_span: int,
                          key=None) -> list[ResultGroup]:
    """Collapse route permutations by exact authored region and level tier."""
    metric = key or (lambda result: result.score)
    grouped: dict[tuple[str, int], list[MapResult]] = defaultdict(list)
    for result in results:
        level_band = int(result.avg_monster_level) // level_span * level_span
        identity = result.region or result.location or result.name
        grouped[(identity, level_band)].append(result)
    output = []
    for (region, level_band), candidates in grouped.items():
        representative = max(candidates, key=metric)
        output.append(ResultGroup(
            region=region,
            level_band=level_band,
            level_min=min(result.min_monster_level for result in candidates),
            level_max=max(result.max_monster_level for result in candidates),
            candidates=tuple(candidates),
            representative=representative,
        ))
    return sorted(output, key=lambda group: metric(group.representative), reverse=True)


def render_text(results: list[MapResult], options: AnalysisOptions, limit: int,
                experience: ExperienceModel, warnings: set[str],
                rejections: list[tuple[str, str]] | None = None) -> str:
    if options.group_results:
        display_groups = group_farming_results(results, options.group_level_span)
    else:
        display_groups = [
            ResultGroup(
                result.region, int(result.avg_monster_level),
                result.min_monster_level, result.max_monster_level,
                (result,), result)
            for result in results
        ]
    shown_groups = display_groups[:limit]
    shown = [group.representative for group in shown_groups]
    if options.simulate_melee:
        offense = (
            f"melee DAM {options.melee_damage}, WC {options.weapon_class}/"
            f"{options.weapon_class_range}, weapon speed {options.weapon_speed:g}s, attacks "
            f"{', '.join(f'{name}={amount}%' for name, amount in options.player_attacks)}"
        )
    else:
        offense = (
            f"fixed {options.damage_per_attack:g} damage/attack every "
            f"{options.attack_delay:g}s = {options.dps:g} DPS, "
            f"attack {options.attack_type}"
        )
    if options.aoe_radius > 0:
        offense += f", topology-derived AoE radius {options.aoe_radius}"
    else:
        offense += f", {options.targets_per_attack} target(s)/attack"
    if options.targets_per_attack > 1 or options.aoe_radius > 0:
        offense += (
            f", passive pull efficiency {options.passive_pull_efficiency * 100.0:.0f}%")
    if options.simulate_mana:
        offense += (
            f", mana {options.mana_cost:g}/attack every {options.attack_delay:g}s, "
            f"regen {options.mana_regen:g}/s"
            f"{' with Meditation ramp' if options.meditation else ''}"
            f"{' after ' + format(options.meditation_delay, 'g') + 's combat delay' if options.meditation_delay else ''}, "
            f"stored {options.stored_mana:g}"
        )
    score_description = (
        "score = 40% estimated XP/hr + 15% estimated money/hr + "
        "10% estimated loot/hr + 25% safety + 10% maneuverability (normalized)"
        if options.ranking in {"balanced", "all"} else
        f"score = normalized {options.ranking} ranking"
    )
    lines = [
        f"Atrinik farming ranking — combat skill level {options.player_level}",
        f"Time {options.at_minute // 60:02d}:{options.at_minute % 60:02d}; {offense}; "
        f"spawn-check overhead {options.seconds_per_kill:g}s; "
        f"map overhead {options.seconds_per_map:g}s",
        f"Safety target: character L{options.character_level}, AC {options.player_ac}, "
        f"protections {', '.join(f'{name}={amount}%' for name, amount in options.player_protections) or 'none'}; "
        f"HP {f'{options.max_health:g}' if options.max_health > 0.0 else 'not supplied'}",
        f"Excluded regions: {', '.join(options.excluded_regions) or 'none'}",
        f"Kill XP cap: {experience.kill_cap(options.player_level):,}; {score_description}",
        (f"Presentation: grouped by exact region and {options.group_level_span}-level "
         "monster tier; each row is the best representative route"
         if options.group_results else
         "Presentation: individual map and circuit routes"),
        "",
    ]
    if not shown:
        lines.append("No maps matched the filters.")
        return "\n".join(lines)
    headers = ("#", "score", "similar", "mob L", "spawns", "packs", "ready/lap", "reward", "move", "pull", "aggro", "XP/kill", "level%",
               "XP/hr*", "money/hr*", "loot/hr*", "HP", "DPS-out", "kill-s", "hit", "hit%", "swings/s",
               "DPS-in", "dmg/kill", "danger", "respawn", "location")
    level_span = max(1, experience.new_levels[options.player_level + 1] -
                     experience.new_levels[options.player_level])
    rows = []
    for index, group in enumerate(shown_groups, 1):
        result = group.representative
        monster_levels = (str(group.level_min) if group.level_min == group.level_max else
                          f"{group.level_min}-{group.level_max}")
        rows.append((
            str(index), f"{result.score:.1f}", str(len(group.candidates)), monster_levels,
            f"{result.spawns:g}",
            f"{result.encounter_packs:g}×{result.average_pack_size:.1f}",
            f"{result.expected_kills_lap:.1f}",
            f"{result.reward_fraction * 100.0:.0f}%",
            f"{result.maneuverability * 100.0:.0f}%",
            f"{result.aoe_pullability * 100.0:.0f}%",
            f"{result.max_aggro_pack:g}",
            _fmt_number(result.avg_xp), f"{result.xp_clear / level_span * 100.0:.1f}%",
            _fmt_number(result.xp_hour),
            _fmt_money(result.money_hour), f"{result.loot_hour:.1f}",
            _fmt_number(result.avg_hp), f"{result.avg_player_damage_second:.1f}",
            _fmt_number(result.avg_kill_seconds, 1), f"{result.avg_hit_damage:.1f}",
            f"{result.avg_hit_chance * 100.0:.0f}%", f"{result.avg_attacks_second:.3f}",
            f"{result.avg_damage_second:.1f}", f"{result.avg_damage_taken:.1f}",
            f"{result.danger:.1f}",
            f"{result.respawn_seconds / 60.0:.1f}m" if math.isfinite(result.respawn_seconds) else "n/a",
            result.location,
        ))
    widths = [max(len(headers[i]), *(len(row[i]) for row in rows)) for i in range(len(headers))]
    lines.append("  ".join(headers[i].ljust(widths[i]) for i in range(len(headers))))
    lines.append("  ".join("-" * widths[i] for i in range(len(headers))))
    for row in rows:
        lines.append("  ".join(row[i].ljust(widths[i]) for i in range(len(headers))))
    if options.ranking == "all":
        views = {
            "XP": lambda item: item.xp_hour,
            "money": lambda item: item.money_hour,
            "loot": lambda item: item.loot_hour,
            "safety": lambda item: item.safety_score,
            "maneuverability": lambda item: item.maneuverability,
        }
        lines.extend(("", "Other ranking leaders:"))
        for label, key in views.items():
            if options.group_results:
                leaders = group_farming_results(
                    results, options.group_level_span, key)[:3]
            else:
                leaders = [
                    ResultGroup(
                        item.region, int(item.avg_monster_level),
                        item.min_monster_level, item.max_monster_level,
                        (item,), item)
                    for item in sorted(results, key=key, reverse=True)[:3]
                ]
            lines.append(
                f"  {label}: " + "; ".join(
                    f"{group.label} L{group.level_min}-{group.level_max} "
                    f"({_fmt_number(group.representative.xp_hour)} XP/hr, "
                    f"{_fmt_money(group.representative.money_hour)}/hr)"
                    for group in leaders))
    lines.extend(("", "Top-location details:"))
    for index, group in enumerate(shown_groups[: min(5, len(shown_groups))], 1):
        result = group.representative
        if options.simulate_melee:
            offense_detail = (
                f"{result.avg_player_hit_damage:.1f} damage/hit at "
                f"{result.avg_player_hit_chance * 100.0:.0f}% hit chance and "
                f"{result.avg_player_attacks_second:.3f} swings/s = "
                f"{result.avg_player_damage_second:.1f} outgoing DPS; "
                f"~{result.avg_kill_seconds:.1f}s per kill"
            )
        else:
            offense_detail = (
                f"fixed {options.dps:g} outgoing DPS after protection; "
                f"~{result.avg_kill_seconds:.1f}s per kill"
            )
        lines.extend((
            f"{index}. {group.label} — monsters L{group.level_min}-L{group.level_max}",
            f"   best route: {result.name} — {result.path}",
            (f"   grouped candidates: {len(group.candidates)} map/circuit route(s); "
             f"XP/hr {_fmt_number(min(item.xp_hour for item in group.candidates))}–"
             f"{_fmt_number(max(item.xp_hour for item in group.candidates))}; "
             f"scores {min(item.score for item in group.candidates):.1f}–"
             f"{max(item.score for item in group.candidates):.1f}"
             if len(group.candidates) > 1 else
             "   grouped candidates: this is the only route in its region/tier"),
            f"   full-population clear: {_fmt_number(result.xp_clear)} XP, "
            f"{result.loot_clear:.1f} loot packages, "
            f"{result.gear_clear:.2f} gear, {result.consumables_clear:.2f} consumables, "
            f"~{_fmt_money(result.money_clear)}; modeled clear {result.clear_seconds:.0f}s "
            f"({result.active_clear_seconds:.0f}s active + "
            f"{result.mana_rest_seconds:.0f}s mana rest); "
            f"highest monster L{result.max_monster_level}",
            f"   patrol: ~{result.expected_kills_lap:.1f}/{result.spawns:g} mobs ready "
            f"per {result.expected_lap_seconds:.0f}s steady-state lap "
            f"({result.spawn_availability * 100.0:.0f}% availability)",
            f"   offense: {offense_detail}",
            f"   targeting: ~{result.effective_targets_per_attack:.2f} target(s)/attack",
            f"   encounters: ~{result.encounter_packs:g} room-separated pack(s), "
            f"average {result.average_pack_size:.1f}, largest {result.largest_pack_size:g}; "
            f"pack-size target capacity {result.pack_target_capacity:.2f}",
            f"   terrain: {_maneuver_label(result.maneuverability)} "
            f"({result.maneuverability * 100.0:.0f}% maneuverability; "
            f"{result.arena_quality * 100.0:.0f}% room-arena quality, "
            f"{result.walkable_fraction * 100.0:.0f}% walkable, "
            f"{result.open_tile_fraction * 100.0:.0f}% fully open, "
            f"{result.clearance_fraction * 100.0:.0f}% with two-tile clearance)",
            (f"   competition: ~{result.competitor_count:g} NPC combatant spawn(s); "
             f"{result.contested_spawns:g}/{result.spawns:g} monster spawns contested; "
             f"player reward share {result.reward_fraction * 100.0:.0f}%"
             f"{' (contention adjustment disabled)' if not options.model_npc_contention else ''}"
             if result.competitor_count > 0.0 else
             "   competition: no authored NPC combatants competing for these spawns"),
            (f"   attacks: ~{result.attacks_clear / result.spawns:.2f} paid attack(s)/kill; "
             f"{result.attacks_clear:.1f} per full clear"
             if result.attacks_clear > 0.0 else
             "   attacks: continuous expected-hit melee model"),
            f"   safety: {result.avg_hit_damage:.1f} expected damage/hit at "
            f"{result.avg_hit_chance * 100.0:.0f}% hit chance and "
            f"{result.avg_attacks_second:.3f} swings/s = {result.avg_damage_second:.1f} "
            f"incoming DPS; ~{result.avg_damage_taken:.1f} damage per kill",
            f"   aggro: {result.aggressive_spawns:g} aggressive + "
            f"{result.passive_spawns:g} passive spawns; AoE pullability "
            f"{result.aoe_pullability * 100.0:.0f}%; likely simultaneous aggro "
            f"~{result.max_aggro_pack:g}; eight-tile proximity cluster "
            f"~{result.max_proximity_pack:g}",
            f"   monsters: {', '.join(result.monsters) or 'unknown'}",
            f"   danger: {', '.join(result.danger_flags) or 'ordinary melee'}; "
            f"sources: {', '.join(result.sources)}",
        ))
        if options.character_speed > 0.0:
            lines.append(
                f"   route: ~{result.route_steps:,} authored walkable tile steps = "
                f"{result.route_seconds:.0f}s at displayed speed {options.character_speed:g}"
            )
        if options.simulate_mana:
            lines.append(
                f"   mana: {result.mana_spent_clear:.0f} spent per clear; "
                f"~{result.burst_kills:.1f}/{result.spawns:g} mobs per full "
                f"{options.max_mana:g}+{options.mana_crystal:g} crystal burst"
            )
        if options.max_health > 0.0:
            lines.append(
                f"   health: ~{result.damage_clear:.0f}/{options.max_health:g} HP "
                f"({result.health_clear_fraction * 100.0:.0f}%) expected melee damage per "
                f"clear; ~{result.survivable_kills:.1f} average kills per full health bar"
            )
    lines.extend((
        "",
        "Estimation limits: starred hourly rates are steady-state patrol estimates. Spawn availability "
        "uses every spawn's source-authored discrete attempt cadence and grace probability with randomized "
        "phase, and solves it together "
        "with partially populated lap duration; it does not assume every spawn is ready on every lap. "
        "Rates still assume continuous "
        "access and immediate selling at 20% of "
        "authored base item value. Random magic/artifact value, identification, slaying/on-hit "
        "bonuses, monster equipment, situational attack-roll modifiers, blocking, spell/ranged cadence, "
        "quests/keys, other players, and shop restrictions are not simulated. Authored NPC-faction "
        "combatants reduce XP/corpse reward share when their and the monsters' detection ranges overlap; "
        "AI timing, exact damage contribution, and dynamic positions remain uncertain. Authored walkability, "
        "static blockers, room cores, narrow passages, local clearance, and coordinate-map seams are used "
        "for maneuverability, encounter packs, and routes. Room-forming walls are useful boundaries; "
        "blockers embedded inside usable space count as clutter. "
        "Dynamic obstacles are not modeled. For AoE, maneuverability scales only the extra targets beyond the first "
        "to represent gathering and kiting space; --ignore-maneuverability disables that terrain factor. "
        "The requested AoE target count is capped by the weighted sizes of room-separated packs. Authored "
        "unaggressive monsters then contribute only --passive-pull-efficiency of an aggressive "
        "monster toward those extra AoE targets because each must first be provoked; aggressive monsters "
        "acquire and follow the player themselves. "
        "Incoming melee damage uses the supplied character level, AC, protections, and modeled "
        "kill time. With --simulate-multiple-enemies it also charges concurrent exposure until each "
        "single-target or AoE attack group dies; otherwise it assumes one monster at a time. Likely simultaneous aggro "
        "counts monsters whose own authored detection radius reaches each pull point, without LOS or "
        "random ally-signal simulation, and can be bounded with --max-aggro-pack. The separately reported "
        "eight-tile proximity cluster is spawn density, not an assertion that all members engage. The supplied "
        "targets-per-attack value is an intended average before pack-size, terrain, and aggression adjustments. --aoe-radius "
        "instead derives an average from authored spawn proximity, but facing, walls within the effect, "
        "moving targets, and overkill remain uncertain. Mana regeneration uses discrete server ticks; "
        "--meditation applies the server's out-of-combat ramp after --meditation-delay. Casting and "
        "modeled combat reset the ramp. Native mana and crystal charge are separate: the crystal only "
        "discharges into missing native mana and only recharges from a full native pool, half a pool per "
        "application. Crystal applications are treated as instant optimal inputs. The supplied "
        "skill level is held constant. Spawn-point respawn is "
        "source-derived; map-reset-only monsters require the map to unload and are excluded unless "
        "--include-static is used.",
    ))
    if warnings:
        lines.append(f"Treasure-model warnings: {len(warnings)} (use --json to inspect derived values).")
    if rejections is not None:
        counts = Counter(reason for _path, reason in rejections)
        lines.extend(("", f"Rejected candidates: {len(rejections)}"))
        for reason, count in counts.most_common(12):
            lines.append(f"  {count}× {reason}")
        for path, reason in rejections[:20]:
            lines.append(f"  {path}: {reason}")
    return "\n".join(lines)
