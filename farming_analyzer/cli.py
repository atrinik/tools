"""Command-line parsing, validation, profiles, and JSON output."""

import argparse
import json
import sys
from dataclasses import asdict, replace
from pathlib import Path

from .analyzer import FarmingAnalyzer
from .config import ATTACK_TYPES, PHYSICAL_ATTACKS, ROOT, SERVER_ROOT
from .models import AnalysisOptions
from .presentation import (
    group_farming_results,
    parse_melee_attack,
    parse_player_protection,
    parse_time,
    render_text,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("level", type=int, help="combat skill level used by calc_skill_exp")
    parser.add_argument("--content-root", type=Path, default=ROOT,
                        help="authored-content checkout (default: sibling content)")
    parser.add_argument("--server-root", type=Path, default=SERVER_ROOT,
                        help="classic server src directory (default: sibling classic/server/src)")
    parser.add_argument("--top", type=int, default=20, help="number of ranked maps to print")
    parser.add_argument("--time", type=parse_time, default=parse_time("12:00"), metavar="HH:MM",
                        help="in-game time used for scheduled spawns (default: 12:00)")
    parser.add_argument("--damage-per-attack", type=float,
                        help="effective damage per attack/cast after accuracy; requires --attack-delay")
    parser.add_argument("--targets-per-attack", type=int, default=1,
                        help="average monsters damaged by each attack (default: 1)")
    parser.add_argument("--mana-cost", type=float,
                        help="mana spent per attack; enables the mana/rest model")
    parser.add_argument("--attack-delay", type=float,
                        help="seconds between attacks or spell casts while fighting")
    parser.add_argument("--mana-regen", type=float,
                        help="mana regenerated per second, including while resting")
    parser.add_argument("--max-mana", type=float,
                        help="character mana available at the start of a burst")
    parser.add_argument("--mana-crystal", type=float, default=0.0,
                        help="extra mana stored in a full mana crystal (default: 0)")
    parser.add_argument("--meditation", action="store_true",
                        help="apply the server's Meditation regen ramp while resting")
    parser.add_argument("--meditation-delay", type=float, default=0.0,
                        help="seconds after the last cast during which combat keeps Meditation at 1x")
    parser.add_argument("--melee-damage", type=int,
                        help="final character-sheet melee DAM; enables melee simulation")
    parser.add_argument("--weapon-class", type=int,
                        help="final character-sheet melee WC; enables melee simulation")
    parser.add_argument("--weapon-speed", type=float,
                        help="character-sheet melee weapon speed in seconds per swing")
    parser.add_argument("--weapon-class-range", type=int, default=20,
                        help="server melee WC roll range (default: 20)")
    parser.add_argument("--melee-attack", action="append", type=parse_melee_attack,
                        default=[], metavar="TYPE=PERCENT",
                        help="outgoing attack-type percentage; may be repeated")
    parser.add_argument("--character-level", type=int,
                        help="character level used for incoming monster damage (default: level)")
    parser.add_argument("--max-health", type=float,
                        help="full character HP used for route-survival scoring")
    parser.add_argument("--character-speed", type=float,
                        help="movement speed displayed by the client (for example 1.03)")
    parser.add_argument("--player-ac", type=int,
                        help="player AC used for monster hit chance (default: character level)")
    parser.add_argument("--player-protection", action="append", type=parse_player_protection,
                        default=[], metavar="TYPE=PERCENT",
                        help="player protection used for incoming damage; may be repeated")
    parser.add_argument("--attack-type", choices=("physical_average",) + ATTACK_TYPES,
                        default="physical_average",
                        help="fixed-damage protection or default simulated melee attack type")
    parser.add_argument("--seconds-per-kill", type=float, default=2.0,
                        help="movement/targeting/looting allowance per spawn location")
    parser.add_argument("--seconds-per-map", type=float, default=10.0,
                        help="fixed traversal overhead for each clear")
    parser.add_argument("--shop-sell-fraction", type=float, default=0.20)
    parser.add_argument("--min-spawns", type=int, default=3)
    parser.add_argument("--min-xp-fraction", type=float, default=0.35,
                        help="minimum average XP/kill as a fraction of the kill cap")
    parser.add_argument("--max-level-gap", type=int, default=5,
                        help="exclude if a monster exceeds max(skill, character level)+gap")
    parser.add_argument("--max-aggro-pack", type=int, default=0,
                        help="exclude maps whose likely direct simultaneous aggro exceeds this size; 0 disables")
    parser.add_argument("--aoe-radius", type=int, default=0,
                        help="derive average targets per attack from spawn proximity within this tile radius")
    parser.add_argument("--simulate-multiple-enemies", action="store_true",
                        help="model overlapping incoming damage from likely aggro packs")
    parser.add_argument("--ignore-npc-contention", dest="model_npc_contention",
                        action="store_false",
                        help="do not reduce rewards where NPC factions compete for monsters")
    parser.add_argument("--ignore-maneuverability", dest="model_maneuverability",
                        action="store_false",
                        help="report terrain spaciousness but do not reduce achievable AoE targets")
    parser.add_argument("--min-maneuverability", type=float, default=0.0,
                        help="exclude locations below this terrain score from 0 to 1")
    parser.add_argument("--passive-pull-efficiency", type=float, default=0.20,
                        help="relative AoE-pull contribution of unaggressive mobs from 0 to 1 (default: 0.20)")
    parser.add_argument("--ranking", choices=("balanced", "xp", "money", "loot", "safety",
                                               "maneuverability", "all"),
                        default="balanced", help="ranking view to display (default: balanced)")
    parser.add_argument("--show-all-routes", dest="group_results", action="store_false",
                        help="show every overlapping map/circuit instead of one representative per zone tier")
    parser.add_argument("--group-level-span", type=int, default=10,
                        help="monster-level tier width used to group candidates (default: 10)")
    parser.add_argument("--explain-rejected", action="store_true",
                        help="report why candidate maps were excluded")
    parser.add_argument("--simulate-hours", type=float, default=0.0,
                        help="simulate training and rerank whenever the skill levels")
    parser.add_argument("--skill-xp", type=int,
                        help="current absolute skill XP for training simulation")
    parser.add_argument("--profile", type=Path,
                        help="load analyzer arguments from a JSON character profile")
    parser.add_argument("--save-profile", type=Path,
                        help="save the validated character arguments as JSON")
    parser.add_argument("--circuit-size", type=int, default=4,
                        help="also rank connected coordinate-map circuits up to this size; 1 disables")
    parser.add_argument("--path", dest="path_pattern", help="case-insensitive map-path regex")
    parser.add_argument("--exclude-region", action="append", default=[], metavar="NAME",
                        help="exclude a region/island ID or name; may be repeated")
    parser.add_argument("--include-static", action="store_true",
                        help="include monsters that only return after map reset/unload")
    parser.add_argument("--json", action="store_true", help="emit machine-readable results")
    return parser


def simulate_training(analyzer: FarmingAnalyzer, options: AnalysisOptions,
                      hours: float, initial_xp: int | None) -> list[dict]:
    remaining = hours * 3600.0
    level = options.player_level
    xp = float(initial_xp if initial_xp is not None
               else analyzer.experience.new_levels[level])
    stages = []
    while remaining > 0.001 and level + 1 < len(analyzer.experience.new_levels):
        stage_options = replace(options, player_level=level)
        results = analyzer.scan(stage_options)
        if not results or results[0].xp_hour <= 0.0:
            stages.append({"level": level, "status": "no eligible route"})
            break
        route = results[0]
        target = analyzer.experience.new_levels[level + 1]
        needed = max(0.0, target - xp)
        seconds = needed / route.xp_hour * 3600.0
        used = min(remaining, seconds)
        gained = route.xp_hour * used / 3600.0
        stages.append({
            "level": level, "hours": used / 3600.0, "xp_gained": gained,
            "xp_hour": route.xp_hour, "route": route.location,
            "path": route.path,
        })
        xp += gained
        remaining -= used
        if used + 0.001 < seconds:
            break
        level += 1
        xp = max(xp, float(target))
    return stages


def main(argv: list[str] | None = None) -> int:
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    profile_parser = argparse.ArgumentParser(add_help=False)
    profile_parser.add_argument("--profile", type=Path)
    profile_args, _unknown = profile_parser.parse_known_args(raw_argv)
    parser = build_parser()
    if profile_args.profile is not None:
        try:
            profile_defaults = json.loads(profile_args.profile.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            raise SystemExit(f"cannot load profile: {exc}") from exc
        if not isinstance(profile_defaults, dict):
            raise SystemExit("profile must contain a JSON object")
        parser.set_defaults(**profile_defaults)
    args = parser.parse_args(raw_argv)
    analyzer = FarmingAnalyzer(args.content_root, args.server_root)
    maximum_level = min(len(analyzer.experience.level_exp) - 1,
                        len(analyzer.experience.new_levels) - 2)
    if not (1 <= args.level <= maximum_level):
        raise SystemExit(f"level must be between 1 and {maximum_level}")
    character_level = args.character_level if args.character_level is not None else args.level
    player_ac = args.player_ac if args.player_ac is not None else character_level
    melee_values = (args.melee_damage, args.weapon_class, args.weapon_speed)
    simulate_melee = all(value is not None for value in melee_values)
    if any(value is not None for value in melee_values) and not simulate_melee:
        raise SystemExit("melee simulation requires --melee-damage, --weapon-class, and --weapon-speed")
    if simulate_melee and args.damage_per_attack is not None:
        raise SystemExit("fixed damage inputs cannot be combined with melee simulation stats")
    if not simulate_melee and (args.damage_per_attack is None or args.attack_delay is None):
        raise SystemExit(
            "fixed damage simulation requires --damage-per-attack and --attack-delay")
    if args.damage_per_attack is not None and args.damage_per_attack <= 0.0:
        raise SystemExit("damage per attack must be positive")
    if args.attack_delay is not None and args.attack_delay <= 0.0:
        raise SystemExit("attack delay must be positive")
    dps = (args.damage_per_attack / args.attack_delay
           if args.damage_per_attack is not None else 0.0)
    if args.melee_attack and not simulate_melee:
        raise SystemExit("--melee-attack requires melee simulation stats")
    if ((not simulate_melee and dps <= 0.0) or args.seconds_per_kill < 0 or
            args.seconds_per_map < 0):
        raise SystemExit(
            "derived DPS must be positive and time overheads cannot be negative")
    mana_specific_values = (args.mana_cost, args.mana_regen, args.max_mana)
    simulate_mana = (all(value is not None for value in mana_specific_values) and
                     args.attack_delay is not None)
    if (any(value is not None for value in mana_specific_values) or
            args.mana_crystal != 0.0) and not simulate_mana:
        raise SystemExit(
            "mana simulation requires --mana-cost, --attack-delay, --mana-regen, and --max-mana")
    if (args.attack_delay is not None and args.damage_per_attack is None and
            args.mana_cost is None):
        raise SystemExit("--attack-delay requires --damage-per-attack or mana simulation")
    if args.meditation and not simulate_mana:
        raise SystemExit("--meditation requires mana simulation")
    if args.meditation_delay < 0.0:
        raise SystemExit("meditation delay cannot be negative")
    if args.meditation_delay and not args.meditation:
        raise SystemExit("--meditation-delay requires --meditation")
    if simulate_mana and (args.mana_cost <= 0.0 or args.mana_regen <= 0.0 or
                          args.max_mana < 0.0):
        raise SystemExit(
            "mana cost and mana regen must be positive; max mana cannot be negative")
    if simulate_mana and args.mana_cost > args.max_mana:
        raise SystemExit("mana cost cannot exceed native max mana; crystals only refill that pool")
    if args.mana_crystal > 0.0 and args.max_mana < 2.0:
        raise SystemExit("native max mana must be at least 2 to recharge a crystal")
    if args.mana_crystal < 0.0:
        raise SystemExit("mana crystal capacity cannot be negative")
    if args.max_health is not None and args.max_health <= 0.0:
        raise SystemExit("max health must be positive")
    if args.character_speed is not None and args.character_speed <= 0.0:
        raise SystemExit("character speed must be positive")
    if args.aoe_radius < 0:
        raise SystemExit("AoE radius cannot be negative")
    if args.simulate_hours < 0.0:
        raise SystemExit("simulate-hours cannot be negative")
    if args.skill_xp is not None and args.skill_xp < 0:
        raise SystemExit("skill XP cannot be negative")
    if args.skill_xp is not None and args.simulate_hours <= 0.0:
        raise SystemExit("--skill-xp requires --simulate-hours")
    if not (0.0 <= args.shop_sell_fraction <= 1.0):
        raise SystemExit("shop sell fraction must be between 0 and 1")
    if (args.top < 1 or args.min_spawns < 1 or args.max_level_gap < 0 or
            args.max_aggro_pack < 0):
        raise SystemExit("top/min-spawns must be positive and max-level-gap cannot be negative")
    if args.targets_per_attack < 1:
        raise SystemExit("targets-per-attack must be positive")
    if not (0.0 <= args.min_xp_fraction <= 1.0):
        raise SystemExit("min-xp-fraction must be between 0 and 1")
    if not (0.0 <= args.min_maneuverability <= 1.0):
        raise SystemExit("min-maneuverability must be between 0 and 1")
    if not (0.0 <= args.passive_pull_efficiency <= 1.0):
        raise SystemExit("passive-pull-efficiency must be between 0 and 1")
    if not (1 <= args.circuit_size <= 8):
        raise SystemExit("circuit-size must be between 1 and 8")
    if not (1 <= args.group_level_span <= 50):
        raise SystemExit("group-level-span must be between 1 and 50")
    if not (1 <= character_level <= maximum_level):
        raise SystemExit(f"character level must be between 1 and {maximum_level}")
    if (args.skill_xp is not None and
            not (analyzer.experience.new_levels[args.level] <= args.skill_xp <
                 analyzer.experience.new_levels[args.level + 1])):
        raise SystemExit("skill XP must fall within the supplied skill level")
    if simulate_melee and (args.melee_damage <= 0 or args.weapon_class < 0 or
                           args.weapon_speed <= 0.0):
        raise SystemExit("melee damage/weapon speed must be positive and weapon class non-negative")
    if args.weapon_class_range < 1:
        raise SystemExit("weapon class range must be positive")
    player_protections = tuple(sorted(dict(args.player_protection).items()))
    if args.melee_attack:
        player_attacks = tuple(sorted(dict(args.melee_attack).items()))
    elif args.attack_type == "physical_average":
        player_attacks = tuple((attack, 25) for attack in PHYSICAL_ATTACKS)
    else:
        player_attacks = ((args.attack_type, 100),)
    options = AnalysisOptions(
        args.level, dps, args.seconds_per_kill, args.seconds_per_map,
        args.shop_sell_fraction, args.time, args.attack_type, args.min_spawns,
        args.min_xp_fraction, args.max_level_gap, args.circuit_size,
        args.path_pattern, args.include_static, character_level, player_ac,
        player_protections, args.melee_damage, args.weapon_class,
        args.weapon_speed, args.weapon_class_range, player_attacks,
        args.max_aggro_pack,
        args.targets_per_attack,
        args.mana_cost or 0.0,
        args.attack_delay or 0.0,
        args.mana_regen or 0.0,
        args.max_mana or 0.0,
        args.mana_crystal,
        tuple(args.exclude_region),
        args.damage_per_attack or 0.0,
        args.meditation,
        args.max_health or 0.0,
        args.character_speed or 0.0,
        args.aoe_radius,
        args.simulate_multiple_enemies,
        args.ranking,
        args.meditation_delay,
        analyzer.tick_seconds,
        args.model_npc_contention,
        args.model_maneuverability,
        args.min_maneuverability,
        args.passive_pull_efficiency,
        args.group_results,
        args.group_level_span,
    )
    results = analyzer.scan(options)
    initial_rejections = list(analyzer.rejections)
    training = simulate_training(
        analyzer, options, args.simulate_hours, args.skill_xp) if args.simulate_hours else []
    if args.save_profile is not None:
        excluded = {
            "top", "json", "path_pattern", "include_static", "profile",
            "save_profile", "explain_rejected", "simulate_hours", "skill_xp",
            "level", "group_results", "group_level_span", "content_root",
            "server_root",
        }
        profile = {
            key: value for key, value in vars(args).items()
            if key not in excluded
        }
        try:
            args.save_profile.write_text(json.dumps(profile, indent=2) + "\n")
        except OSError as exc:
            raise SystemExit(f"cannot save profile: {exc}") from exc
    if args.json:
        assumptions = asdict(options)
        assumptions["combat_model"] = (
            "melee_simulation" if options.simulate_melee else "damage_divided_by_attack_delay")
        assumptions["mana_model"] = "burst_and_regeneration" if options.simulate_mana else "disabled"
        if options.simulate_melee:
            assumptions["dps"] = None
        payload = {
            "assumptions": assumptions,
            "kill_xp_cap": analyzer.experience.kill_cap(args.level),
            "score_weights": {"xp_hour": 0.40, "money_hour": 0.15,
                              "loot_hour": 0.10, "safety": 0.25,
                              "maneuverability": 0.10},
            "results": [asdict(result) for result in results[:args.top]],
            "warnings": sorted(analyzer.treasure.warnings),
            "training": training,
        }
        if options.group_results:
            payload["groups"] = [
                {
                    "region": group.region,
                    "label": group.label,
                    "level_band": group.level_band,
                    "level_min": group.level_min,
                    "level_max": group.level_max,
                    "candidate_count": len(group.candidates),
                    "xp_hour_min": min(item.xp_hour for item in group.candidates),
                    "xp_hour_max": max(item.xp_hour for item in group.candidates),
                    "representative": asdict(group.representative),
                }
                for group in group_farming_results(
                    results, options.group_level_span)[:args.top]
            ]
        if options.ranking == "all":
            payload["rankings"] = {
                label: [asdict(result) for result in sorted(
                    results, key=key, reverse=True)[:args.top]]
                for label, key in {
                    "balanced": lambda item: item.score,
                    "xp": lambda item: item.xp_hour,
                    "money": lambda item: item.money_hour,
                    "loot": lambda item: item.loot_hour,
                    "safety": lambda item: item.safety_score,
                    "maneuverability": lambda item: item.maneuverability,
                }.items()
            }
        if args.explain_rejected:
            payload["rejections"] = [
                {"path": path, "reason": reason}
                for path, reason in initial_rejections]
        print(json.dumps(payload, indent=2))
    else:
        rendered = render_text(
            results, options, args.top, analyzer.experience,
            analyzer.treasure.warnings,
            initial_rejections if args.explain_rejected else None)
        if training:
            rendered += "\n\nTraining simulation:"
            for stage in training:
                if "hours" not in stage:
                    rendered += f"\n  L{stage['level']}: {stage['status']}"
                    continue
                rendered += (
                    f"\n  L{stage['level']}: {stage['hours']:.2f}h at "
                    f"{stage['route']} ({stage['xp_hour']:,.0f} XP/hr, "
                    f"+{stage['xp_gained']:,.0f} XP)")
        print(rendered)
    return 0
