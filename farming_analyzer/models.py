"""Data models shared by farming analysis and presentation."""

import math
from dataclasses import dataclass, field

from .treasure import Loot


@dataclass
class MonsterProfile:
    archetype: str
    name: str
    level: int
    xp: float
    hp: float
    effective_hp: float
    player_hit_damage: float
    player_hit_chance: float
    player_attacks_second: float
    player_damage_second: float
    kill_seconds: float
    damage: float
    expected_hit_damage: float
    hit_chance: float
    attacks_second: float
    damage_second: float
    damage_taken: float
    danger: float
    aggro_radius: int
    loot: Loot
    flags: tuple[str, ...]
    attacks_to_kill: float = 0.0


@dataclass
class SpawnProfile:
    candidates: tuple[tuple[float, MonsterProfile], ...]
    respawn_seconds: float
    source: str
    x: int = 0
    y: int = 0
    aggressive_probability: float = 0.0
    attempt_seconds: float = math.inf
    attempt_probability: float = 0.0

    def weighted(self, attr: str) -> float:
        return sum(probability * getattr(profile, attr) for probability, profile in self.candidates)

    @property
    def loot(self) -> Loot:
        result = Loot()
        for probability, profile in self.candidates:
            result += probability * profile.loot
        return result


@dataclass(frozen=True)
class CompetitorProfile:
    x: int
    y: int
    aggro_radius: float
    probability: float


@dataclass
class MapResult:
    path: str
    name: str
    region: str
    difficulty: int
    spawns: float
    xp_clear: float
    avg_xp: float
    hp_clear: float
    effective_hp_clear: float
    avg_hp: float
    avg_damage: float
    danger: float
    respawn_seconds: float
    clear_seconds: float
    kills_hour: float
    xp_hour: float
    money_clear: float
    money_hour: float
    loot_clear: float
    loot_hour: float
    gear_clear: float
    consumables_clear: float
    max_monster_level: int
    avg_player_hit_damage: float
    avg_player_hit_chance: float
    avg_player_attacks_second: float
    avg_player_damage_second: float
    avg_kill_seconds: float
    avg_hit_damage: float
    avg_hit_chance: float
    avg_attacks_second: float
    avg_damage_second: float
    damage_clear: float
    avg_damage_taken: float
    aggressive_spawns: float = 0.0
    passive_spawns: float = 0.0
    max_aggro_pack: float = 0.0
    max_proximity_pack: float = 0.0
    score: float = 0.0
    monsters: tuple[str, ...] = ()
    danger_flags: tuple[str, ...] = ()
    sources: tuple[str, ...] = ()
    map_paths: tuple[str, ...] = ()
    location: str = ""
    nearby_landmarks: tuple[str, ...] = ()
    active_clear_seconds: float = 0.0
    mana_spent_clear: float = 0.0
    mana_rest_seconds: float = 0.0
    burst_kills: float = 0.0
    effective_targets_per_attack: float = 1.0
    health_clear_fraction: float = 0.0
    survivable_kills: float = math.inf
    expected_kills_lap: float = 0.0
    expected_lap_seconds: float = 0.0
    spawn_availability: float = 0.0
    route_steps: int = 0
    route_seconds: float = 0.0
    spawn_points: tuple[tuple[str, int, int], ...] = ()
    safety_score: float = 0.0
    spawn_events: tuple[tuple[float, float], ...] = ()
    attacks_clear: float = 0.0
    reward_fraction: float = 1.0
    competitor_count: float = 0.0
    contested_spawns: float = 0.0
    maneuverability: float = 1.0
    walkable_fraction: float = 1.0
    open_tile_fraction: float = 1.0
    clearance_fraction: float = 1.0
    aoe_pullability: float = 1.0
    arena_quality: float = 1.0
    encounter_packs: float = 1.0
    average_pack_size: float = 1.0
    largest_pack_size: float = 1.0
    pack_target_capacity: float = 1.0
    min_monster_level: int = 0
    avg_monster_level: float = 0.0


@dataclass(frozen=True)
class AnalysisOptions:
    player_level: int
    dps: float
    seconds_per_kill: float
    seconds_per_map: float
    shop_sell_fraction: float
    at_minute: int
    attack_type: str
    minimum_spawns: int
    minimum_xp_fraction: float
    max_level_gap: int
    circuit_size: int
    path_pattern: str | None
    include_static: bool
    character_level: int
    player_ac: int
    player_protections: tuple[tuple[str, int], ...]
    melee_damage: int | None
    weapon_class: int | None
    weapon_speed: float | None
    weapon_class_range: int
    player_attacks: tuple[tuple[str, int], ...]
    max_aggro_pack: int = 0
    targets_per_attack: int = 1
    mana_cost: float = 0.0
    attack_delay: float = 0.0
    mana_regen: float = 0.0
    max_mana: float = 0.0
    mana_crystal: float = 0.0
    excluded_regions: tuple[str, ...] = ()
    damage_per_attack: float = 0.0
    meditation: bool = False
    max_health: float = 0.0
    character_speed: float = 0.0
    aoe_radius: int = 0
    simulate_multiple_enemies: bool = False
    ranking: str = "balanced"
    meditation_delay: float = 0.0
    server_tick_seconds: float = 0.125
    model_npc_contention: bool = True
    model_maneuverability: bool = True
    minimum_maneuverability: float = 0.0
    passive_pull_efficiency: float = 0.20
    group_results: bool = True
    group_level_span: int = 10

    @property
    def simulate_melee(self) -> bool:
        return (self.melee_damage is not None and self.weapon_class is not None and
                self.weapon_speed is not None)

    @property
    def simulate_mana(self) -> bool:
        return self.mana_cost > 0.0

    @property
    def mana_use_second(self) -> float:
        return self.mana_cost * self.attack_rate

    @property
    def attack_rate(self) -> float:
        return 1.0 / self.attack_delay if self.attack_delay > 0.0 else 0.0

    @property
    def stored_mana(self) -> float:
        return self.max_mana + self.mana_crystal
