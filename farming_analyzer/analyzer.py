"""Source-derived farming location analysis."""

import math
import re
from collections import Counter, defaultdict, deque
from pathlib import Path
from typing import Iterable

from .config import (
    CONSUMABLE_TYPES,
    GEAR_TYPES,
    MONEY_TYPE,
    MONSTER_TYPE,
    PHYSICAL_ATTACKS,
    RANDOM_DROP_TYPE,
    ROOT,
    SERVER_ATTACK_TYPES,
    SERVER_ROOT,
    SPAWN_POINT_MOB_TYPE,
    SPAWN_POINT_TYPE,
    STATUS_ATTACK_TYPES,
)
from .experience import ExperienceModel
from .models import (
    AnalysisOptions,
    CompetitorProfile,
    MapResult,
    MonsterProfile,
    SpawnProfile,
)
from .sources import (
    LocationIndex,
    TerrainIndex,
    TerrainMap,
    _integer,
    _last,
    _number,
    fields,
    flatten,
    load_archetypes,
    merged_attrs,
    one,
    parse_blocks,
    source_map_files,
)
from .treasure import Loot, TreasureModel


class FarmingAnalyzer:
    def __init__(self, root: Path = ROOT, server_root: Path = SERVER_ROOT):
        self.root = root
        self.map_root = root / "maps"
        self.arch_root = root / "arch"
        self.server_root = server_root
        self.archetypes = load_archetypes(self.arch_root, self.root)
        self._load_artifacts()
        self.experience = ExperienceModel.load(self.server_root)
        self.treasure = TreasureModel.load(self.archetypes, root)
        self.locations = LocationIndex(root)
        self.tick_seconds = self._constant("MAX_TIME", 125000) / 1_000_000.0
        self.default_reset = self._constant("MAP_DEFAULTRESET", 7200)
        self._world_graph = None
        self._npc_factions = self._load_npc_factions()
        self.rejections: list[tuple[str, str]] = []

    def _load_npc_factions(self) -> set[str]:
        """Resolve authored faction ancestry rooted at the global NPC faction."""
        parents: dict[str, set[str]] = defaultdict(set)
        for path in self.map_root.rglob("*.factions"):
            stack: list[str] = []
            for raw in path.read_text(errors="replace").splitlines():
                line = raw.split("#", 1)[0].strip()
                if line.startswith("faction "):
                    faction = line.split(None, 1)[1]
                    if stack:
                        parents[faction].add(stack[-1])
                    stack.append(faction)
                elif line.startswith("parent ") and stack:
                    parents[stack[-1]].add(line.split(None, 1)[1])
                elif line == "end" and stack:
                    stack.pop()
        npc_factions = {"npcs"}
        changed = True
        while changed:
            changed = False
            for faction, direct_parents in parents.items():
                if faction not in npc_factions and direct_parents & npc_factions:
                    npc_factions.add(faction)
                    changed = True
        return npc_factions

    def _load_artifacts(self) -> None:
        for path in sorted(set(self.arch_root.rglob("*.art")) |
                           set(self.map_root.rglob("*.art"))):
            lines = path.read_text(errors="replace").splitlines()
            index = 0
            while index < len(lines):
                if not lines[index].startswith("artifact "):
                    index += 1
                    continue
                artifact = lines[index].split(" ", 1)[1]
                index += 1
                definition = None
                object_lines = []
                while index < len(lines) and not lines[index].startswith("artifact "):
                    line = lines[index]
                    if line.startswith("def_arch "):
                        definition = line.split(" ", 1)[1]
                    if line == "Object":
                        index += 1
                        while index < len(lines) and lines[index] != "end":
                            object_lines.append(lines[index] + "\n")
                            index += 1
                        break
                    index += 1
                attrs = dict(self.archetypes.get(definition or "", {}).get("attrs", {}))
                parsed = fields(object_lines)
                attrs.update({key: values[-1] for key, values in parsed.items() if values})
                self.archetypes[artifact] = {
                    "path": str(path.relative_to(self.root)),
                    "attrs": attrs,
                    "def_arch": definition,
                }

    def _constant(self, name: str, default: int) -> int:
        source = (self.server_root / "include" / "config.h").read_text(errors="replace")
        match = re.search(rf"^#define\s+{re.escape(name)}\s+(\d+)", source, re.MULTILINE)
        return int(match.group(1)) if match else default

    @staticmethod
    def _mana_cycle_timing(attacks: float, overhead_seconds: float,
                           options: AnalysisOptions) -> tuple[float, float, float]:
        """Simulate casts, native mana, crystal transfers, and regeneration.

        The state starts and ends with both pools full, making the returned
        duration sustainable across repeated patrols. Regeneration follows
        the server's eight-tick remainder mechanism. Crystal recharging is
        performed optimally during explicit rest only: native mana must be
        full and each application transfers at most half of it.
        """
        attacks = max(0.0, attacks)
        active_seconds = attacks * options.attack_delay + overhead_seconds
        if not options.simulate_mana or attacks <= 0.0:
            return active_seconds, 0.0, attacks
        if (options.mana_cost > options.max_mana or
                (options.mana_crystal > 0.0 and options.max_mana < 2.0)):
            return active_seconds, math.inf, 0.0

        tick = options.server_tick_seconds
        ticks_second = max(1, round(1.0 / tick))
        base_regen_value = max(1, round(options.mana_regen * 10.0))
        # Invert get_regen_value() for the displayed base value. This lets the
        # Meditation multiplier pass through the same affine conversion.
        base_regen_speed = max(20.0, 15.0 * base_regen_value - 10.0)
        native = options.max_mana
        crystal = options.mana_crystal
        remainder = 0
        tick_phase = 0
        tick_credit = 0.0
        since_combat = 0.0
        rest_seconds = 0.0
        attacks_done = 0.0
        first_burst = attacks
        refills = 0
        overhead_attack = overhead_seconds / attacks

        def recharge_crystal() -> None:
            nonlocal native, crystal
            if native + 1e-9 < options.max_mana or crystal >= options.mana_crystal:
                return
            transfer = min(options.mana_crystal - crystal, math.floor(native / 2.0))
            native -= transfer
            crystal += transfer

        def advance(duration: float, *, resting: bool) -> None:
            nonlocal native, crystal, remainder, tick_phase, tick_credit
            nonlocal since_combat, rest_seconds
            if resting:
                recharge_crystal()
            tick_credit += duration
            steps = max(0, math.floor(tick_credit / tick + 1e-9))
            tick_credit -= steps * tick
            for _step in range(steps):
                since_combat += tick
                tick_phase = (tick_phase + 1) % ticks_second
                effective_out = max(0.0, since_combat - options.meditation_delay)
                modifier = (min(10.0, 1.0 + effective_out / 10.0)
                            if options.meditation else 1.0)
                regen_value = int((base_regen_speed * modifier + 10.0) / 15.0)
                if tick_phase == 0:
                    remainder += regen_value
                add = 0
                if remainder >= ticks_second * 10:
                    add = int(remainder / (ticks_second * 10))
                elif remainder >= 10:
                    add = int(remainder / 10)
                if add:
                    remainder -= add * 10
                    native = min(options.max_mana, native + add)
                if resting:
                    recharge_crystal()
                    rest_seconds += tick

        remaining = attacks
        while remaining > 1e-9:
            unit = min(1.0, remaining)
            cost = options.mana_cost * unit
            if native + 1e-9 < cost and crystal > 0.0:
                transfer = min(options.max_mana - native, crystal)
                native += transfer
                crystal -= transfer
            if native + 1e-9 < cost:
                if refills == 0:
                    first_burst = attacks_done
                refills += 1
                while (native + 1e-9 < options.max_mana or
                       crystal + 1e-9 < options.mana_crystal):
                    advance(tick, resting=True)
                continue
            native -= cost
            attacks_done += unit
            remaining -= unit
            since_combat = 0.0
            advance((options.attack_delay + overhead_attack) * unit, resting=False)

        # Restore the exact starting state before the next patrol cycle.
        if (native + 1e-9 < options.max_mana or
                crystal + 1e-9 < options.mana_crystal):
            if refills == 0:
                first_burst = attacks_done
            while (native + 1e-9 < options.max_mana or
                   crystal + 1e-9 < options.mana_crystal):
                advance(tick, resting=True)
        return active_seconds, rest_seconds, first_burst

    @staticmethod
    def _patrol_estimate(count: float, respawn_seconds: float,
                         single_target_combat_seconds: float,
                         fixed_overhead: float, options: AnalysisOptions,
                         initial_seconds: float,
                         effective_targets: float | None = None,
                         spawn_events: tuple[tuple[float, float], ...] = ()) -> tuple[float, float]:
        """Solve the steady-state revisit interval for a farming patrol.

        A spawned monster remains available until the next visit. Mirror the
        discrete source-authored attempt cadence and grace probability for
        every spawn, including fractional phase averaged across independently
        scheduled points. The
        expected population changes the following lap's duration and mana
        rests, so solve those quantities together.
        """
        if count <= 0.0 or not math.isfinite(respawn_seconds):
            return 0.0, max(initial_seconds, 0.001)
        if not math.isfinite(initial_seconds):
            return 0.0, math.inf

        seconds = max(initial_seconds, fixed_overhead, 0.001)
        combat_per_kill = single_target_combat_seconds / max(count, 0.001)
        effective_targets = (min(float(options.targets_per_attack), count)
                             if effective_targets is None else effective_targets)
        route_encounters = math.ceil(count / effective_targets)
        route_overhead = (fixed_overhead +
                          route_encounters * options.seconds_per_kill)

        def availability_after(duration: float) -> float:
            if not spawn_events:
                # Compatibility for synthetic callers which provide only a
                # mean renewal time: use a memoryless continuous estimate.
                return 1.0 - math.exp(-duration / respawn_seconds)
            ready = 0.0
            for attempt_seconds, probability in spawn_events:
                if not math.isfinite(attempt_seconds) or probability <= 0.0:
                    continue
                attempts = duration / attempt_seconds
                whole = math.floor(attempts)
                phase = attempts - whole
                failure = ((1.0 - phase) * math.pow(1.0 - probability, whole) +
                           phase * math.pow(1.0 - probability, whole + 1.0))
                ready += 1.0 - failure
            return ready / count

        for _iteration in range(100):
            availability = availability_after(seconds)
            expected_kills = count * availability
            combat = expected_kills * combat_per_kill / effective_targets
            # Every spawn location still needs to be reached and inspected
            # when empty. Keep the full route overhead while scaling only
            # combat and mana consumption by the population actually ready.
            if options.simulate_mana:
                attacks = combat / options.attack_delay
                active, rest, _burst = FarmingAnalyzer._mana_cycle_timing(
                    attacks, route_overhead, options)
            else:
                active = route_overhead + combat
                rest = 0.0
            updated = active + rest
            if not math.isfinite(updated):
                return 0.0, math.inf
            if abs(updated - seconds) < 0.001:
                seconds = updated
                break
            # Damping keeps steep Meditation/capacity transitions stable.
            seconds = (seconds + updated) / 2.0

        availability = availability_after(seconds)
        return count * availability, max(seconds, 0.001)

    def _world(self):
        if self._world_graph is None:
            graph = TerrainIndex()
            for path in source_map_files(self.map_root):
                parsed = parse_blocks(path)
                header = parsed["header"]
                if header is None:
                    continue
                node = TerrainMap(
                    _integer(one(header["attrs"], "width")),
                    _integer(one(header["attrs"], "height")),
                )
                graph.nodes["/" + path.relative_to(self.map_root).as_posix()] = node
                for obj, parent in flatten(parsed["objects"]):
                    attrs = merged_attrs(obj, self.archetypes)
                    x = _integer(one(
                        obj["attrs"], "x",
                        one(parent["attrs"], "x", 0) if parent else 0,
                    ))
                    y = _integer(one(
                        obj["attrs"], "y",
                        one(parent["attrs"], "y", 0) if parent else 0,
                    ))
                    terrain = _integer(attrs.get("terrain_type"))
                    if terrain:
                        node.terrain[(x, y)] = node.terrain.get((x, y), 0) | terrain
                    # Doors, exits, and teleporters are traversable server-side.
                    if attrs.get("no_pass") == "1" and attrs.get("type") not in (
                            "20", "64", "66"):
                        node.blocked.add((x, y))
            self._world_graph = graph
        return self._world_graph

    def _maneuverability(
            self, relpath: str,
            spawn_points: list[tuple[int, int]],
    ) -> tuple[float, float, float, float, float, tuple[int, ...]]:
        """Score room-local arenas and partition spawns at narrow passages."""
        graph = self._world()
        node = graph.nodes.get("/" + relpath.removeprefix("maps/"))
        if node is None or node.width <= 0 or node.height <= 0:
            return 0.5, 0.0, 0.0, 0.0, 0.5, (len(spawn_points),)
        walkable = {
            (x, y) for y in range(node.height) for x in range(node.width)
            if node.walkable(x, y)
        }
        if not walkable:
            return 0.0, 0.0, 0.0, 0.0, 0.0, (len(spawn_points),)
        neighbors = (
            (-1, -1), (0, -1), (1, -1), (-1, 0),
            (1, 0), (-1, 1), (0, 1), (1, 1),
        )
        open_tiles = sum(
            all((x + dx, y + dy) in walkable for dx, dy in neighbors)
            for x, y in walkable)
        clearance_tiles = sum(
            all((x + dx, y + dy) in walkable
                for dx in range(-2, 3) for dy in range(-2, 3))
            for x, y in walkable)
        walkable_fraction = len(walkable) / (node.width * node.height)
        open_fraction = open_tiles / len(walkable)
        clearance_fraction = clearance_tiles / len(walkable)
        # A one-tile erosion leaves the centers of genuine rooms while
        # removing narrow doors and corridors. Its connected components are
        # therefore useful authored encounter arenas without map-name hints.
        room_core = {
            (x, y) for x, y in walkable
            if all((x + dx, y + dy) in walkable
                   for dx in (-1, 0, 1) for dy in (-1, 0, 1))
        }
        components: list[set[tuple[int, int]]] = []
        remaining = set(room_core)
        cardinal = ((1, 0), (-1, 0), (0, 1), (0, -1))
        while remaining:
            component = {remaining.pop()}
            frontier = list(component)
            while frontier:
                x, y = frontier.pop()
                for dx, dy in cardinal:
                    neighbor = x + dx, y + dy
                    if neighbor in remaining:
                        remaining.remove(neighbor)
                        component.add(neighbor)
                        frontier.append(neighbor)
            if len(component) >= 4:
                components.append(component)

        labels: dict[tuple[int, int], int] = {}
        frontier = deque()
        for index, component in enumerate(components):
            for point in component:
                labels[point] = index
                frontier.append(point)
        while frontier:
            x, y = frontier.popleft()
            for dx, dy in cardinal:
                neighbor = x + dx, y + dy
                if neighbor in walkable and neighbor not in labels:
                    labels[neighbor] = labels[(x, y)]
                    frontier.append(neighbor)

        pack_counts: Counter[int] = Counter()
        for x, y in spawn_points:
            label = labels.get((x, y))
            if label is None and components:
                label = min(
                    range(len(components)),
                    key=lambda index: min(
                        max(abs(x - cx), abs(y - cy))
                        for cx, cy in components[index]),
                )
            pack_counts[-1 if label is None else label] += 1
        pack_sizes = tuple(sorted(pack_counts.values(), reverse=True))
        if not pack_sizes:
            pack_sizes = (len(spawn_points),)

        if spawn_points and components:
            arena_quality = sum(
                amount * min(1.0, math.sqrt(len(components[index]) / 25.0))
                for index, amount in pack_counts.items() if index >= 0
            ) / len(spawn_points)
        else:
            arena_quality = min(1.0, math.sqrt(len(walkable) / 64.0))

        # Penalize obstacles embedded inside usable space (trees, furniture),
        # but not walls that form useful room boundaries.
        internal_obstacles = 0
        for x, y in node.blocked:
            adjacent = [
                (x + 1, y) in walkable, (x - 1, y) in walkable,
                (x, y + 1) in walkable, (x, y - 1) in walkable,
            ]
            diagonal = sum(
                (x + dx, y + dy) in walkable
                for dx in (-1, 0, 1) for dy in (-1, 0, 1)
                if dx != 0 or dy != 0)
            if (sum(adjacent) >= 3 or (adjacent[0] and adjacent[1]) or
                    (adjacent[2] and adjacent[3]) or diagonal >= 6):
                internal_obstacles += 1
        clutter_fraction = internal_obstacles / len(walkable)
        score = max(0.0, min(
            1.0, arena_quality * max(0.35, 1.0 - 4.0 * clutter_fraction)))
        return (score, walkable_fraction, open_fraction, clearance_fraction,
                arena_quality, pack_sizes)

    def _route_steps(self, result: MapResult) -> int | None:
        """Approximate a closed spawn patrol over authored walkable tiles."""
        if len(result.spawn_points) <= 1:
            return 0
        graph = self._world()
        allowed = {"/" + path.removeprefix("maps/") for path in result.map_paths}
        points = [("/" + path.removeprefix("maps/"), x, y)
                  for path, x, y in result.spawn_points]
        coordinates = {}
        reverse = {}
        for path in allowed:
            parsed = LocationIndex.world_coordinates(Path(path).name)
            if parsed is not None:
                prefix, x, y, z = parsed
                coordinates[path] = (prefix, x, y, z)
                reverse[(str(Path(path).parent), prefix, x, y, z)] = path

        def neighbors(state):
            path, x, y = state
            node = graph.nodes[path]
            for dx, dy in (
                    (1, 0), (-1, 0), (0, 1), (0, -1),
                    (1, 1), (1, -1), (-1, 1), (-1, -1)):
                target_path = path
                nx, ny = x + dx, y + dy
                if not (0 <= nx < node.width and 0 <= ny < node.height):
                    coordinate = coordinates.get(path)
                    if coordinate is None:
                        continue
                    prefix, cx, cy, z = coordinate
                    target_path = reverse.get((
                        str(Path(path).parent), prefix,
                        cx + (-1 if nx < 0 else 1 if nx >= node.width else 0),
                        cy + (-1 if ny < 0 else 1 if ny >= node.height else 0), z))
                    if target_path is None:
                        continue
                    target = graph.nodes[target_path]
                    nx = target.width - 1 if nx < 0 else 0 if nx >= node.width else nx
                    ny = target.height - 1 if ny < 0 else 0 if ny >= node.height else ny
                if graph.nodes[target_path].walkable(nx, ny):
                    yield target_path, nx, ny

        matrix = [[0] * len(points) for _point in points]
        for index, source in enumerate(points):
            distances = {source: 0}
            frontier = deque((source,))
            while frontier:
                state = frontier.popleft()
                for neighbor in neighbors(state):
                    if neighbor not in distances:
                        distances[neighbor] = distances[state] + 1
                        frontier.append(neighbor)
            for target_index, target in enumerate(points):
                if target not in distances:
                    return None
                matrix[index][target_index] = distances[target]

        best = math.inf
        for start in range(len(points)):
            remaining = set(range(len(points))) - {start}
            current = start
            distance = 0
            route = [start]
            while remaining:
                nxt = min(remaining, key=lambda item: matrix[current][item])
                distance += matrix[current][nxt]
                remaining.remove(nxt)
                current = nxt
                route.append(nxt)
            improved = True
            while improved:
                improved = False
                for left in range(1, len(route) - 1):
                    for right in range(left + 1, len(route)):
                        before = route[left - 1]
                        after = route[(right + 1) % len(route)]
                        old = matrix[before][route[left]] + matrix[route[right]][after]
                        new = matrix[before][route[right]] + matrix[route[left]][after]
                        if new < old:
                            route[left:right + 1] = reversed(route[left:right + 1])
                            improved = True
            closed = sum(
                matrix[route[index]][route[(index + 1) % len(route)]]
                for index in range(len(route)))
            best = min(best, closed)
        return int(best)

    def _apply_route_timing(self, result: MapResult,
                            options: AnalysisOptions) -> None:
        if options.character_speed <= 0.0:
            return
        steps = self._route_steps(result)
        if steps is None:
            self.rejections.append((result.path, "spawn locations are not mutually reachable"))
            result.score = -math.inf
            return
        result.route_steps = steps
        result.route_seconds = steps * self.tick_seconds / options.character_speed
        combat = result.avg_kill_seconds * result.spawns / result.effective_targets_per_attack
        encounters = math.ceil(result.spawns / result.effective_targets_per_attack)
        overhead = encounters * options.seconds_per_kill + result.route_seconds
        if options.simulate_mana:
            active, rest, burst_attacks = self._mana_cycle_timing(
                result.attacks_clear, overhead, options)
            spent = result.attacks_clear * options.mana_cost
            average_attacks_kill = (result.attacks_clear *
                                    result.effective_targets_per_attack / result.spawns)
            result.burst_kills = min(
                result.spawns,
                math.floor(burst_attacks / max(average_attacks_kill, 0.001)) *
                result.effective_targets_per_attack)
        else:
            active = combat + overhead
            spent = 0.0
            rest = 0.0
        result.active_clear_seconds = active
        result.mana_spent_clear = spent
        result.mana_rest_seconds = rest
        result.clear_seconds = active + rest
        expected, lap = self._patrol_estimate(
            result.spawns, result.respawn_seconds,
            result.avg_kill_seconds * result.spawns, result.route_seconds,
            options, result.clear_seconds, result.effective_targets_per_attack,
            result.spawn_events)
        result.expected_kills_lap = expected
        result.expected_lap_seconds = lap
        result.spawn_availability = expected / result.spawns
        result.kills_hour = expected * 3600.0 / lap
        clears = result.kills_hour / result.spawns
        result.xp_hour = result.xp_clear * clears * result.reward_fraction
        result.money_hour = result.money_clear * clears * result.reward_fraction
        result.loot_hour = result.loot_clear * clears * result.reward_fraction

    @staticmethod
    def _schedule_active(schedule: str, minute: int) -> bool:
        match = re.fullmatch(r"\s*(\d+):(\d+)\s*-\s*(\d+):(\d+)\s*", schedule)
        if match is None:
            return True
        start_hour, start_minute, end_hour, end_minute = map(int, match.groups())
        start = start_hour * 60 + start_minute
        end = end_hour * 60 + end_minute
        if start <= end:
            return start <= minute <= end
        return minute >= start or minute <= end

    @staticmethod
    def _attack_hit_chance(wc: int, wc_range: int, target_ac: int) -> float:
        """Mirror attack_object()'s WC/AC roll with no situational modifier."""
        wc_range = wc_range or 20
        threshold = target_ac - wc
        if threshold <= 1:
            return 1.0
        if threshold >= wc_range:
            return 1.0 / wc_range
        return (wc_range - threshold + 1) / wc_range

    @staticmethod
    def _typed_damage(rolled_damage: float, attacks: Iterable[tuple[str, int]],
                      protections: dict[str, int]) -> float:
        """Mirror attack_hit_attacktype() for direct-damage attack types."""
        result = 0.0
        for attack, amount in attacks:
            if amount <= 0 or attack in STATUS_ATTACK_TYPES:
                continue
            component = rolled_damage * amount / 100.0
            if rolled_damage > 0.0 and component < 1.0:
                component = 1.0
            result += component * (100.0 - protections.get(attack, 0)) / 100.0
        return result

    def _player_melee(self, attrs: dict[str, str], level: int, hp: float,
                      effective_hp: float,
                      options: AnalysisOptions) -> tuple[float, float, float, float, float]:
        """Return player hit, hit chance, swings/s, DPS, and kill time."""
        if not options.simulate_melee:
            kill_seconds = effective_hp / options.dps
            return 0.0, 0.0, 0.0, options.dps, kill_seconds

        assert options.melee_damage is not None
        assert options.weapon_class is not None
        assert options.weapon_speed is not None
        low_roll = int(options.melee_damage * 0.8 + 1.0)
        rolled_damage = (min(low_roll, options.melee_damage) + options.melee_damage) / 2.0
        protections = {
            attack: _integer(attrs.get(f"protect_{attack}"))
            for attack in SERVER_ATTACK_TYPES
        }
        expected_hit = self._typed_damage(
            rolled_damage, options.player_attacks, protections)
        monster_ac = _integer(attrs.get("ac")) + level
        hit_chance = self._attack_hit_chance(
            options.weapon_class, options.weapon_class_range, monster_ac)

        # player.c schedules the next auto-attack after weapon_speed server
        # ticks; the client displays that value divided by MAX_TICKS, so the
        # supplied character-sheet value is already seconds per swing.
        attacks_second = 1.0 / options.weapon_speed
        damage_second = expected_hit * hit_chance * attacks_second
        kill_seconds = math.inf if damage_second <= 0.0 else hp / damage_second
        return expected_hit, hit_chance, attacks_second, damage_second, kill_seconds

    def _melee_threat(self, attrs: dict[str, str], level: int, damage: int,
                      fight_seconds: float,
                      options: AnalysisOptions) -> tuple[float, float, float, float, float]:
        """Return expected hit, hit chance, swings/s, DPS, and damage per kill."""
        if damage <= 0:
            return 0.0, 0.0, 0.0, 0.0, 0.0

        # attack_object(): rndm(dam * 0.8 + 1.0, dam), whose floating lower
        # bound is converted to int before the inclusive server RNG call.
        low_roll = int(damage * 0.8 + 1.0)
        rolled_damage = (min(low_roll, damage) + damage) / 2.0
        if level > options.character_level:
            difference = level - options.character_level
            rolled_damage *= 1.0 + 0.5 * difference / min(20, options.character_level)

        attacks = tuple(
            (attack, max(0, _integer(attrs.get(f"attack_{attack}"))))
            for attack in SERVER_ATTACK_TYPES
        )
        expected_hit = self._typed_damage(
            rolled_damage, attacks, dict(options.player_protections))

        wc = _integer(attrs.get("wc")) + level + level // 3
        wc_range = _integer(attrs.get("wc_range"), 20) or 20
        hit_chance = self._attack_hit_chance(wc, wc_range, options.player_ac)

        # set_mobile_speed() uses 2x authored speed while idle and 4x with an
        # enemy (3x for FLAG_SLOW_MOVE). main.c advances weapon readiness once
        # per tick, while monster.c only swings on an available AI action.
        base_speed = abs(_number(attrs.get("speed")))
        combat_speed = base_speed * (3.0 if attrs.get("slow_move") == "1" else 4.0)
        weapon_speed = max(0.0, _number(attrs.get("weapon_speed")))
        attacks_second = min(combat_speed, weapon_speed) / self.tick_seconds
        damage_second = expected_hit * hit_chance * attacks_second
        if math.isinf(fight_seconds):
            damage_taken = math.inf if damage_second > 0.0 else 0.0
        else:
            damage_taken = damage_second * fight_seconds
        return expected_hit, hit_chance, attacks_second, damage_second, damage_taken

    def _levels(self, attrs: dict[str, str], map_difficulty: int) -> list[int]:
        base_level = max(1, min(200, _integer(attrs.get("level"), 1)))
        relative = _integer(attrs.get("item_condition"))
        if relative not in range(1, 7) or not (0 <= map_difficulty < len(self.experience.level_colors)):
            return [base_level]
        colors = self.experience.level_colors[map_difficulty]
        bounds = {
            1: (colors[0], colors[1] - 1),
            2: (colors[1], colors[2] - 1),
            3: (colors[2], colors[3] - 1),
            4: (colors[3], colors[4] - 1),
            5: (colors[4], colors[5] - 1),
            6: (colors[5], colors[5] + 1),
        }
        low, high = bounds[relative]
        low = max(base_level, min(low, 200))
        high = max(base_level, min(high, 200))
        return list(range(low, high + 1))

    def _monster_profile(self, node: dict, map_difficulty: int,
                         options: AnalysisOptions) -> MonsterProfile:
        attrs = merged_attrs(node, self.archetypes)
        levels = self._levels(attrs, map_difficulty)
        profiles = [self._monster_at_level(node, attrs, level, options) for level in levels]
        count = len(profiles)
        loot = Loot()
        for profile in profiles:
            loot += profile.loot * (1.0 / count)
        flags = tuple(sorted(set(flag for profile in profiles for flag in profile.flags)))
        return MonsterProfile(
            node["arch"], profiles[0].name, round(sum(p.level for p in profiles) / count),
            sum(p.xp for p in profiles) / count,
            sum(p.hp for p in profiles) / count,
            sum(p.effective_hp for p in profiles) / count,
            sum(p.player_hit_damage for p in profiles) / count,
            sum(p.player_hit_chance for p in profiles) / count,
            sum(p.player_attacks_second for p in profiles) / count,
            sum(p.player_damage_second for p in profiles) / count,
            sum(p.kill_seconds for p in profiles) / count,
            sum(p.damage for p in profiles) / count,
            sum(p.expected_hit_damage for p in profiles) / count,
            sum(p.hit_chance for p in profiles) / count,
            sum(p.attacks_second for p in profiles) / count,
            sum(p.damage_second for p in profiles) / count,
            sum(p.damage_taken for p in profiles) / count,
            sum(p.danger for p in profiles) / count,
            round(sum(p.aggro_radius for p in profiles) / count),
            loot, flags,
            sum(p.attacks_to_kill for p in profiles) / count,
        )

    def _monster_at_level(self, node: dict, attrs: dict[str, str], level: int,
                          options: AnalysisOptions) -> MonsterProfile:
        base_hp = max(1, _integer(attrs.get("maxhp"), 1))
        max_hp = (base_hp * (level + 3) + (level // 2) * base_hp) // 10
        authored_hp = _integer(attrs.get("hp"), -1)
        hp = max_hp if authored_hp < 0 else min(max_hp, authored_hp)
        base_damage = max(0, _integer(attrs.get("dam")))

        def level_damage(value: float) -> float:
            return 0.75 + value * 0.25 if value > 0 else 1.0

        damage = int(base_damage * (
            level_damage(level) + max(level_damage(level / 3.0) - 0.75, 0.0)
        ) * (0.925 + 0.05 * (level / 10.0)) / 10.0)
        if level <= 5:
            reduction = 1.0 - (0.35 / 5.0) * (6 - level)
            hp = max(1, int(hp * reduction))
            damage = max(1, int(damage * reduction))

        protections = [_integer(attrs.get(f"protect_{attack}")) for attack in PHYSICAL_ATTACKS]
        if options.attack_type == "physical_average":
            protection = sum(protections) / len(protections)
        else:
            protection = _integer(attrs.get(f"protect_{options.attack_type}"))
        protection = min(95, protection)
        effective_hp = hp / max(0.05, 1.0 - protection / 100.0)

        (player_hit, player_hit_chance, player_attacks_second, player_damage_second,
         kill_seconds) = self._player_melee(attrs, level, hp, effective_hp, options)
        if options.simulate_melee:
            attacks_to_kill = kill_seconds * player_attacks_second
        elif options.damage_per_attack > 0.0 and options.attack_delay > 0.0:
            attacks_to_kill = math.ceil(
                effective_hp / max(options.damage_per_attack, 0.001))
            kill_seconds = attacks_to_kill * options.attack_delay
        else:
            attacks_to_kill = 0.0
        expected_hit, hit_chance, attacks_second, damage_second, damage_taken = (
            self._melee_threat(attrs, level, damage, kill_seconds, options))

        flags = []
        danger_bonus = 0.0
        if attrs.get("can_cast_spell") == "1":
            flags.append("caster")
            danger_bonus += 20.0
        if attrs.get("can_use_bow") == "1":
            flags.append("ranged")
            danger_bonus += 12.0
        # `is_neutral` is alignment metadata, not an aggression control. Only
        # the server's `unaggressive` flag proves that a monster will wait for
        # the player to initiate combat.
        if attrs.get("unaggressive") == "1":
            flags.append("passive")
            danger_bonus -= 4.0
        special_weights = {"drain": 0.50, "poison": 0.18, "acid": 0.08,
                           "magic": 0.05, "fire": 0.03, "cold": 0.03}
        for attack, weight in special_weights.items():
            amount = _integer(attrs.get(f"attack_{attack}"))
            if amount:
                flags.append(attack)
                danger_bonus += amount * weight
        danger = max(1.0, damage_taken + danger_bonus)

        monster_exp = _integer(attrs.get("exp"))
        xp = self.experience.kill_xp(options.player_level, level, monster_exp)
        loot = self.treasure.evaluate(attrs.get("randomitems"), level)
        loot += self._explicit_drops(node)
        return MonsterProfile(
            node["arch"], attrs.get("name", node["arch"].replace("_", " ")),
            level, xp, hp, effective_hp, player_hit, player_hit_chance,
            player_attacks_second, player_damage_second, kill_seconds, damage,
            expected_hit, hit_chance, attacks_second, damage_second, damage_taken, danger,
            max(0, _integer(attrs.get("item_power"))), loot,
            tuple(sorted(set(flags))), attacks_to_kill)

    def _explicit_drops(self, monster: dict) -> Loot:
        result = Loot()
        for child in monster.get("children", []):
            attrs = merged_attrs(child, self.archetypes)
            if _integer(attrs.get("type")) != RANDOM_DROP_TYPE and child["arch"] != "rand_drop":
                continue
            denominator = max(1, _integer(attrs.get("container"), 1))
            probability = 1.0 / denominator
            for item in child.get("children", []):
                item_attrs = merged_attrs(item, self.archetypes)
                item_type = _integer(item_attrs.get("type"))
                nrof = max(1, _integer(_last(item["attrs"], "nrof", item_attrs.get("nrof", 1)), 1))
                value = _number(item_attrs.get("value")) * nrof
                loot = Loot(packages=1.0)
                if item_type == MONEY_TYPE:
                    loot.direct_money = value
                else:
                    loot.base_item_value = value
                    if item_type in GEAR_TYPES:
                        loot.gear = 1.0
                    if item_type in CONSUMABLE_TYPES:
                        loot.consumables = 1.0
                result += probability * loot
        return result

    @staticmethod
    def _hostile(attrs: dict[str, str]) -> bool:
        if (attrs.get("friendly") == "1" or
                attrs.get("no_attack") == "1" or
                attrs.get("invulnerable") == "1"):
            return False
        faction = attrs.get("faction")
        return faction in {None, "", "monsters"} and (
            attrs.get("monster") == "1" or _integer(attrs.get("type")) in
            {MONSTER_TYPE, SPAWN_POINT_MOB_TYPE})

    def _spawn_point(self, node: dict, map_difficulty: int,
                     options: AnalysisOptions) -> SpawnProfile | None:
        attrs = merged_attrs(node, self.archetypes)
        candidates = []
        total_weight = 0
        active_weight = 0
        for child in node.get("children", []):
            child_attrs = merged_attrs(child, self.archetypes)
            if _integer(child_attrs.get("type")) != SPAWN_POINT_MOB_TYPE:
                continue
            weight = max(1, _integer(child_attrs.get("object_int1"), 1))
            total_weight += weight
            if not self._hostile(child_attrs):
                continue
            if not self._schedule_active(child_attrs.get("spawn_time", ""), options.at_minute):
                continue
            profile = self._monster_profile(child, map_difficulty, options)
            candidates.append((weight, profile))
            active_weight += weight
        if not candidates or total_weight <= 0 or active_weight <= 0:
            return None
        normalized = tuple((weight / active_weight, profile) for weight, profile in candidates)
        speed = abs(_number(attrs.get("speed")))
        grace = max(1, _integer(attrs.get("last_grace"), 1))
        availability = active_weight / total_weight
        attempt_seconds = math.inf if speed <= 0 else self.tick_seconds / speed
        attempt_probability = availability / grace
        respawn = (math.inf if attempt_probability <= 0.0 else
                   attempt_seconds / attempt_probability)
        aggressive = sum(
            probability for probability, profile in normalized
            if "passive" not in profile.flags)
        return SpawnProfile(
            normalized, respawn, "spawn",
            _integer(attrs.get("x")), _integer(attrs.get("y")), aggressive,
            attempt_seconds, attempt_probability)

    def _static_monster(self, node: dict, map_difficulty: int,
                        reset_timeout: int, options: AnalysisOptions) -> SpawnProfile | None:
        attrs = merged_attrs(node, self.archetypes)
        if _integer(attrs.get("type")) != MONSTER_TYPE or not self._hostile(attrs):
            return None
        if not self._schedule_active(attrs.get("spawn_time", ""), options.at_minute):
            return None
        profile = self._monster_profile(node, map_difficulty, options)
        return SpawnProfile(
            ((1.0, profile),), float(reset_timeout), "map-reset",
            _integer(attrs.get("x")), _integer(attrs.get("y")),
            0.0 if "passive" in profile.flags else 1.0,
            float(reset_timeout), 1.0)

    def _competitor_spawn(self, node: dict,
                          options: AnalysisOptions) -> CompetitorProfile | None:
        """Return the expected NPC combatant occupying an authored spawn point."""
        attrs = merged_attrs(node, self.archetypes)
        total_weight = 0
        npc_weight = 0
        weighted_aggro = 0.0
        for child in node.get("children", []):
            child_attrs = merged_attrs(child, self.archetypes)
            if _integer(child_attrs.get("type")) != SPAWN_POINT_MOB_TYPE:
                continue
            weight = max(1, _integer(child_attrs.get("object_int1"), 1))
            total_weight += weight
            faction = child_attrs.get("faction", "")
            if (faction not in self._npc_factions or
                    child_attrs.get("no_attack") == "1" or
                    child_attrs.get("invulnerable") == "1" or
                    not self._schedule_active(
                        child_attrs.get("spawn_time", ""), options.at_minute)):
                continue
            npc_weight += weight
            weighted_aggro += weight * max(1, _integer(child_attrs.get("item_power"), 1))
        if total_weight <= 0 or npc_weight <= 0:
            return None
        return CompetitorProfile(
            _integer(attrs.get("x")), _integer(attrs.get("y")),
            weighted_aggro / npc_weight, npc_weight / total_weight)

    @staticmethod
    def _contention(spawns: list[SpawnProfile],
                    competitors: list[CompetitorProfile]) -> tuple[float, float]:
        """Estimate the player's reward share when NPCs can acquire the same mobs.

        Both actors use authored detection radii and can move after acquisition.
        Four extra tiles allow for movement between periodic enemy scans. Each
        NPC that can join a spawn's fight is treated as an equal reward claimant.
        """
        if not competitors:
            return 1.0, 0.0
        shares = []
        contested = 0.0
        for spawn in spawns:
            pressure = sum(
                competitor.probability
                for competitor in competitors
                if max(abs(spawn.x - competitor.x),
                       abs(spawn.y - competitor.y)) <=
                spawn.weighted("aggro_radius") + competitor.aggro_radius + 4.0
            )
            if pressure > 0.0:
                contested += 1.0
            shares.append(1.0 / (1.0 + pressure))
        return sum(shares) / len(shares), contested

    @staticmethod
    def _max_proximity_pack(spawns: list[SpawnProfile], radius: int = 8) -> float:
        """Measure the largest spawn-density component in one viewport."""
        if not spawns:
            return 0.0
        remaining = set(range(len(spawns)))
        maximum = 0.0
        while remaining:
            component = {remaining.pop()}
            frontier = list(component)
            while frontier:
                current = frontier.pop()
                source = spawns[current]
                joined = {
                    index for index in remaining
                    if max(abs(source.x - spawns[index].x),
                           abs(source.y - spawns[index].y)) <= radius
                }
                remaining.difference_update(joined)
                component.update(joined)
                frontier.extend(joined)
            maximum = max(maximum, float(len(component)))
        return maximum

    @staticmethod
    def _max_aggro_pack(spawns: list[SpawnProfile]) -> float:
        """Estimate direct simultaneous aggro at each authored pull point.

        The server checks each monster's own ``item_power`` detection radius.
        A chain of nearby spawn points does not itself propagate aggro across
        the whole chain, so the wider proximity component is reported
        separately instead of being treated as an encounter size.
        """
        maximum = 0.0
        for target in spawns:
            direct = sum(
                spawn.aggressive_probability
                for spawn in spawns
                if max(abs(target.x - spawn.x), abs(target.y - spawn.y)) <=
                spawn.weighted("aggro_radius"))
            if target.aggressive_probability < 1.0:
                direct += 1.0 - target.aggressive_probability
            maximum = max(maximum, direct)
        return maximum

    def analyze_map(self, path: Path, options: AnalysisOptions) -> MapResult | None:
        relpath = str(path.relative_to(self.root))
        parsed = parse_blocks(path)
        header = parsed.get("header")
        if header is None:
            return None
        header_attrs = header["attrs"]
        difficulty = _integer(one(header_attrs, "difficulty", 1), 1)
        reset_timeout = _integer(one(header_attrs, "reset_timeout", self.default_reset),
                                 self.default_reset)
        spawns: list[SpawnProfile] = []
        competitors: list[CompetitorProfile] = []
        for node, parent in flatten(parsed["objects"]):
            attrs = merged_attrs(node, self.archetypes)
            obj_type = _integer(attrs.get("type"))
            if obj_type == SPAWN_POINT_TYPE:
                spawn = self._spawn_point(node, difficulty, options)
                if spawn is not None:
                    spawns.append(spawn)
                competitor = self._competitor_spawn(node, options)
                if competitor is not None:
                    competitors.append(competitor)
            elif options.include_static and parent is None and obj_type == MONSTER_TYPE:
                spawn = self._static_monster(node, difficulty, reset_timeout, options)
                if spawn is not None:
                    spawns.append(spawn)
        if len(spawns) < options.minimum_spawns:
            self.rejections.append((relpath,
                                    f"{len(spawns)} spawns < minimum {options.minimum_spawns}"))
            return None
        max_aggro_pack = self._max_aggro_pack(spawns)
        max_proximity_pack = self._max_proximity_pack(spawns)
        if (options.max_aggro_pack and
                max_aggro_pack > options.max_aggro_pack):
            self.rejections.append((
                relpath, f"aggro pack {max_aggro_pack:g} > maximum {options.max_aggro_pack}"))
            return None
        max_monster_level = max(
            profile.level for spawn in spawns for _probability, profile in spawn.candidates)
        min_monster_level = min(
            profile.level for spawn in spawns for _probability, profile in spawn.candidates)
        survival_level = max(options.player_level, options.character_level)
        if max_monster_level > survival_level + options.max_level_gap:
            self.rejections.append((
                relpath, f"monster L{max_monster_level} > allowed L"
                f"{survival_level + options.max_level_gap}"))
            return None

        count = float(len(spawns))
        aggressive_spawns = sum(
            spawn.aggressive_probability for spawn in spawns)
        passive_spawns = count - aggressive_spawns
        aoe_pullability = (
            aggressive_spawns + passive_spawns * options.passive_pull_efficiency
        ) / count
        xp = sum(spawn.weighted("xp") for spawn in spawns)
        if xp / count < self.experience.kill_cap(options.player_level) * options.minimum_xp_fraction:
            self.rejections.append((
                relpath, f"average XP {xp / count:.0f} below "
                f"{options.minimum_xp_fraction:.0%} of kill cap"))
            return None
        hp = sum(spawn.weighted("hp") for spawn in spawns)
        effective_hp = sum(spawn.weighted("effective_hp") for spawn in spawns)
        player_hit = sum(spawn.weighted("player_hit_damage") for spawn in spawns)
        player_hit_chance = sum(spawn.weighted("player_hit_chance") for spawn in spawns)
        player_attacks_second = sum(
            spawn.weighted("player_attacks_second") for spawn in spawns)
        player_damage_second = sum(
            spawn.weighted("player_damage_second") for spawn in spawns)
        single_target_combat_seconds = sum(
            spawn.weighted("kill_seconds") for spawn in spawns)
        single_target_attacks = sum(
            spawn.weighted("attacks_to_kill") for spawn in spawns)
        damage = sum(spawn.weighted("damage") for spawn in spawns)
        expected_hit = sum(spawn.weighted("expected_hit_damage") for spawn in spawns)
        hit_chance = sum(spawn.weighted("hit_chance") for spawn in spawns)
        attacks_second = sum(spawn.weighted("attacks_second") for spawn in spawns)
        damage_second = sum(spawn.weighted("damage_second") for spawn in spawns)
        damage_clear = sum(spawn.weighted("damage_taken") for spawn in spawns)
        danger = sum(spawn.weighted("danger") for spawn in spawns) / count
        avg_monster_level = sum(
            spawn.weighted("level") for spawn in spawns) / count
        loot = Loot()
        for spawn in spawns:
            loot += spawn.loot
        money = loot.direct_money + options.shop_sell_fraction * loot.base_item_value
        (maneuverability, walkable_fraction, open_tile_fraction,
         clearance_fraction, arena_quality, pack_sizes) = self._maneuverability(
             relpath, [(spawn.x, spawn.y) for spawn in spawns])
        if maneuverability < options.minimum_maneuverability:
            self.rejections.append((
                relpath,
                f"maneuverability {maneuverability * 100.0:.0f}% < minimum "
                f"{options.minimum_maneuverability * 100.0:.0f}%"))
            return None
        effective_targets = min(float(options.targets_per_attack), count)
        if options.aoe_radius > 0:
            effective_targets = min(
                count,
                sum(sum(
                    max(abs(source.x - target.x), abs(source.y - target.y)) <=
                    options.aoe_radius
                    for target in spawns)
                    for source in spawns) / count,
            )
        pack_target_capacity = sum(
            size * min(effective_targets, size) for size in pack_sizes
        ) / count
        effective_targets = min(effective_targets, pack_target_capacity)
        if options.model_maneuverability and effective_targets > 1.0:
            # One target does not require a pull. Additional simultaneous
            # targets depend on having enough open ground to gather and kite.
            effective_targets = 1.0 + (effective_targets - 1.0) * maneuverability
        if effective_targets > 1.0:
            # Aggressive monsters acquire and follow the player on their own.
            # Unaggressive monsters must be individually provoked, so only a
            # configurable fraction of their contribution to a large pull is
            # considered sustainable.
            effective_targets = 1.0 + (
                effective_targets - 1.0) * aoe_pullability
        detected_reward_fraction, contested_spawns = self._contention(
            spawns, competitors)
        reward_fraction = (detected_reward_fraction
                           if options.model_npc_contention else 1.0)
        if options.simulate_multiple_enemies:
            # One-at-a-time damage already charges each mob for its own kill
            # time. Add only the extra concurrent exposure from mobs still
            # alive after each attack group; AoE removes a group together.
            remaining = min(max(max_aggro_pack, effective_targets), count)
            exposure = 0.0
            while remaining > 0.0:
                exposure += remaining
                remaining -= effective_targets
            overlap = exposure / max(min(max_aggro_pack, count), 1.0)
            damage_clear *= overlap
            danger *= overlap
        attacks_clear = single_target_attacks / effective_targets
        combat_seconds = (attacks_clear * options.attack_delay
                          if attacks_clear > 0.0 else
                          single_target_combat_seconds / effective_targets)
        encounters = math.ceil(count / effective_targets)
        overhead_seconds = encounters * options.seconds_per_kill + options.seconds_per_map
        active_clear_seconds = combat_seconds + overhead_seconds
        mana_spent = attacks_clear * options.mana_cost if options.simulate_mana else 0.0
        mana_rest_seconds = 0.0
        burst_kills = count
        if options.simulate_mana:
            active_clear_seconds, mana_rest_seconds, burst_attacks = (
                self._mana_cycle_timing(attacks_clear, overhead_seconds, options))
            average_attacks_kill = single_target_attacks / count
            completed_groups = math.floor(
                burst_attacks / max(average_attacks_kill, 0.001))
            burst_kills = min(count, completed_groups * effective_targets)
        clear_seconds = active_clear_seconds + mana_rest_seconds
        respawn_rate = sum(
            0.0 if not math.isfinite(spawn.respawn_seconds) else 1.0 / spawn.respawn_seconds
            for spawn in spawns)
        respawn_seconds = math.inf if respawn_rate <= 0 else count / respawn_rate
        expected_kills_lap, expected_lap_seconds = self._patrol_estimate(
            count, respawn_seconds, single_target_combat_seconds,
            options.seconds_per_map, options, clear_seconds, effective_targets,
            tuple((spawn.attempt_seconds, spawn.attempt_probability) for spawn in spawns))
        kills_hour = expected_kills_lap * 3600.0 / expected_lap_seconds
        clears_hour = kills_hour / count
        monster_counts: Counter[str] = Counter()
        flag_counts: Counter[str] = Counter()
        for spawn in spawns:
            for probability, profile in spawn.candidates:
                monster_counts[f"{profile.name} L{profile.level}"] += probability
                for flag in profile.flags:
                    flag_counts[flag] += probability
        return MapResult(
            relpath, one(header_attrs, "name", path.name) or path.name,
            one(header_attrs, "region", "") or "", difficulty, count, xp, xp / count,
            hp, effective_hp, hp / count, damage / count, danger, respawn_seconds,
            clear_seconds, kills_hour, xp * clears_hour * reward_fraction,
            money, money * clears_hour * reward_fraction,
            loot.packages, loot.packages * clears_hour * reward_fraction,
            loot.gear, loot.consumables,
            max_monster_level, player_hit / count, player_hit_chance / count,
            player_attacks_second / count, player_damage_second / count,
            single_target_combat_seconds / count, expected_hit / count, hit_chance / count,
            attacks_second / count, damage_second / count, damage_clear,
            damage_clear / count,
            aggressive_spawns=aggressive_spawns,
            passive_spawns=passive_spawns,
            max_aggro_pack=max_aggro_pack,
            max_proximity_pack=max_proximity_pack,
            monsters=tuple(f"{name}×{amount:g}" for name, amount in monster_counts.most_common(8)),
            danger_flags=tuple(f"{flag}×{amount:g}" for flag, amount in flag_counts.most_common()),
            sources=tuple(sorted({spawn.source for spawn in spawns})),
            map_paths=(relpath,),
            active_clear_seconds=active_clear_seconds,
            mana_spent_clear=mana_spent,
            mana_rest_seconds=mana_rest_seconds,
            burst_kills=burst_kills,
            effective_targets_per_attack=effective_targets,
            expected_kills_lap=expected_kills_lap,
            expected_lap_seconds=expected_lap_seconds,
            spawn_availability=expected_kills_lap / count,
            spawn_points=tuple((relpath, spawn.x, spawn.y) for spawn in spawns),
            spawn_events=tuple((spawn.attempt_seconds, spawn.attempt_probability)
                               for spawn in spawns),
            attacks_clear=attacks_clear,
            reward_fraction=reward_fraction,
            competitor_count=sum(item.probability for item in competitors),
            contested_spawns=contested_spawns,
            maneuverability=maneuverability,
            walkable_fraction=walkable_fraction,
            open_tile_fraction=open_tile_fraction,
            clearance_fraction=clearance_fraction,
            aoe_pullability=aoe_pullability,
            arena_quality=arena_quality,
            encounter_packs=float(len(pack_sizes)),
            average_pack_size=count / len(pack_sizes),
            largest_pack_size=float(max(pack_sizes)),
            pack_target_capacity=pack_target_capacity,
            min_monster_level=min_monster_level,
            avg_monster_level=avg_monster_level,
        )

    @staticmethod
    def _coordinate_key(result: MapResult) -> tuple[str, str, int, int, int] | None:
        path = Path(result.path)
        coordinates = LocationIndex.world_coordinates(path.name)
        if coordinates is None:
            return None
        prefix, x, y, z = coordinates
        return str(path.parent), prefix, x, y, z

    @staticmethod
    def _combine_circuit(members: list[MapResult], options: AnalysisOptions) -> MapResult:
        count = sum(member.spawns for member in members)
        effective_targets = sum(
            member.effective_targets_per_attack * member.spawns
            for member in members) / count
        xp = sum(member.xp_clear for member in members)
        hp = sum(member.hp_clear for member in members)
        effective_hp = sum(member.effective_hp_clear for member in members)
        damage_total = sum(member.avg_damage * member.spawns for member in members)
        player_hit_total = sum(
            member.avg_player_hit_damage * member.spawns for member in members)
        player_hit_chance_total = sum(
            member.avg_player_hit_chance * member.spawns for member in members)
        player_attacks_total = sum(
            member.avg_player_attacks_second * member.spawns for member in members)
        player_damage_second_total = sum(
            member.avg_player_damage_second * member.spawns for member in members)
        kill_seconds_total = sum(
            member.avg_kill_seconds * member.spawns for member in members)
        hit_damage_total = sum(member.avg_hit_damage * member.spawns for member in members)
        hit_chance_total = sum(member.avg_hit_chance * member.spawns for member in members)
        attacks_total = sum(member.avg_attacks_second * member.spawns for member in members)
        damage_second_total = sum(
            member.avg_damage_second * member.spawns for member in members)
        damage_clear = sum(member.damage_clear for member in members)
        danger_total = sum(member.danger * member.spawns for member in members)
        active_clear_seconds = sum(member.active_clear_seconds for member in members)
        attacks_clear = sum(member.attacks_clear for member in members)
        mana_spent = attacks_clear * options.mana_cost if options.simulate_mana else 0.0
        mana_rest_seconds = 0.0
        burst_kills = count
        if options.simulate_mana:
            combat_seconds = attacks_clear * options.attack_delay
            overhead_seconds = max(0.0, active_clear_seconds - combat_seconds)
            active_clear_seconds, mana_rest_seconds, burst_attacks = (
                FarmingAnalyzer._mana_cycle_timing(
                    attacks_clear, overhead_seconds, options))
            average_attacks_kill = attacks_clear * effective_targets / count
            burst_kills = min(
                count,
                math.floor(burst_attacks / max(average_attacks_kill, 0.001)) *
                effective_targets)
        clear_seconds = active_clear_seconds + mana_rest_seconds
        respawn_rate = sum(
            member.spawns / member.respawn_seconds
            for member in members if math.isfinite(member.respawn_seconds)
        )
        respawn_seconds = math.inf if respawn_rate <= 0 else count / respawn_rate
        expected_kills_lap, expected_lap_seconds = FarmingAnalyzer._patrol_estimate(
            count, respawn_seconds, kill_seconds_total,
            len(members) * options.seconds_per_map, options, clear_seconds,
            effective_targets,
            tuple(event for member in members for event in member.spawn_events))
        kills_hour = expected_kills_lap * 3600.0 / expected_lap_seconds
        clears_hour = kills_hour / count
        money = sum(member.money_clear for member in members)
        loot = sum(member.loot_clear for member in members)
        rewarded_xp = sum(
            member.xp_clear * member.reward_fraction for member in members)
        rewarded_money = sum(
            member.money_clear * member.reward_fraction for member in members)
        rewarded_loot = sum(
            member.loot_clear * member.reward_fraction for member in members)
        reward_fraction = rewarded_xp / xp if xp > 0.0 else 1.0
        paths = tuple(member.path for member in members)
        names = {member.name for member in members}
        regions = {member.region for member in members}
        monster_counts: Counter[str] = Counter()
        flag_counts: Counter[str] = Counter()
        for member in members:
            for rendered in member.monsters:
                label, separator, amount = rendered.rpartition("×")
                monster_counts[label if separator else rendered] += (
                    _number(amount, 1.0) if separator else 1.0)
            for rendered in member.danger_flags:
                label, separator, amount = rendered.rpartition("×")
                flag_counts[label if separator else rendered] += (
                    _number(amount, 1.0) if separator else 1.0)
        return MapResult(
            path="circuit[" + " + ".join(Path(path).name for path in paths) + "]",
            name=(members[0].name if len(names) == 1 else "Adjacent-map") + " circuit",
            region=members[0].region if len(regions) == 1 else "mixed",
            difficulty=max(member.difficulty for member in members),
            spawns=count, xp_clear=xp, avg_xp=xp / count,
            hp_clear=hp, effective_hp_clear=effective_hp, avg_hp=hp / count,
            avg_damage=damage_total / count, danger=danger_total / count,
            respawn_seconds=respawn_seconds, clear_seconds=clear_seconds,
            kills_hour=kills_hour, xp_hour=rewarded_xp * clears_hour,
            money_clear=money, money_hour=rewarded_money * clears_hour,
            loot_clear=loot, loot_hour=rewarded_loot * clears_hour,
            gear_clear=sum(member.gear_clear for member in members),
            consumables_clear=sum(member.consumables_clear for member in members),
            max_monster_level=max(member.max_monster_level for member in members),
            avg_player_hit_damage=player_hit_total / count,
            avg_player_hit_chance=player_hit_chance_total / count,
            avg_player_attacks_second=player_attacks_total / count,
            avg_player_damage_second=player_damage_second_total / count,
            avg_kill_seconds=kill_seconds_total / count,
            avg_hit_damage=hit_damage_total / count,
            avg_hit_chance=hit_chance_total / count,
            avg_attacks_second=attacks_total / count,
            avg_damage_second=damage_second_total / count,
            damage_clear=damage_clear,
            avg_damage_taken=damage_clear / count,
            aggressive_spawns=sum(
                member.aggressive_spawns for member in members),
            passive_spawns=sum(member.passive_spawns for member in members),
            max_aggro_pack=max(member.max_aggro_pack for member in members),
            max_proximity_pack=max(
                member.max_proximity_pack for member in members),
            monsters=tuple(
                f"{name}×{amount:g}" for name, amount in monster_counts.most_common(12)),
            danger_flags=tuple(
                f"{name}×{amount:g}" for name, amount in flag_counts.most_common()),
            sources=tuple(sorted(set(
                item for member in members for item in member.sources))),
            map_paths=tuple(
                path for member in members for path in member.map_paths),
            active_clear_seconds=active_clear_seconds,
            mana_spent_clear=mana_spent,
            mana_rest_seconds=mana_rest_seconds,
            burst_kills=burst_kills,
            effective_targets_per_attack=effective_targets,
            expected_kills_lap=expected_kills_lap,
            expected_lap_seconds=expected_lap_seconds,
            spawn_availability=expected_kills_lap / count,
            spawn_points=tuple(
                point for member in members for point in member.spawn_points),
            spawn_events=tuple(
                event for member in members for event in member.spawn_events),
            attacks_clear=attacks_clear,
            reward_fraction=reward_fraction,
            competitor_count=sum(member.competitor_count for member in members),
            contested_spawns=sum(member.contested_spawns for member in members),
            maneuverability=sum(
                member.maneuverability * member.spawns for member in members) / count,
            walkable_fraction=sum(
                member.walkable_fraction * member.spawns for member in members) / count,
            open_tile_fraction=sum(
                member.open_tile_fraction * member.spawns for member in members) / count,
            clearance_fraction=sum(
                member.clearance_fraction * member.spawns for member in members) / count,
            aoe_pullability=sum(
                member.aoe_pullability * member.spawns for member in members) / count,
            arena_quality=sum(
                member.arena_quality * member.spawns for member in members) / count,
            encounter_packs=sum(member.encounter_packs for member in members),
            average_pack_size=count / sum(
                member.encounter_packs for member in members),
            largest_pack_size=max(member.largest_pack_size for member in members),
            pack_target_capacity=sum(
                member.pack_target_capacity * member.spawns for member in members) / count,
            min_monster_level=min(member.min_monster_level for member in members),
            avg_monster_level=sum(
                member.avg_monster_level * member.spawns for member in members) / count,
        )

    def _circuits(self, maps: list[MapResult], options: AnalysisOptions) -> list[MapResult]:
        if options.circuit_size < 2:
            return []
        by_grid: dict[tuple[str, str, int, int, int], MapResult] = {}
        for result in maps:
            key = self._coordinate_key(result)
            if key is not None:
                by_grid[key] = result
        neighbors: dict[str, set[str]] = {result.path: set() for result in maps}
        by_path = {result.path: result for result in maps}
        for key, result in by_grid.items():
            parent, prefix, x, y, z = key
            for dx, dy in ((0, -1), (1, 0), (0, 1), (-1, 0)):
                other = by_grid.get((parent, prefix, x + dx, y + dy, z))
                if other is None or other.name != result.name or other.region != result.region:
                    continue
                neighbors[result.path].add(other.path)
        seen: set[frozenset[str]] = set()
        generated: dict[frozenset[str], MapResult] = {}
        frontier = {frozenset((path,)) for path, linked in neighbors.items() if linked}
        for _size in range(2, options.circuit_size + 1):
            next_frontier: set[frozenset[str]] = set()
            for group in frontier:
                candidates = set().union(*(neighbors[path] for path in group)) - set(group)
                for candidate in candidates:
                    expanded = group | {candidate}
                    if len(expanded) != _size or expanded in seen:
                        continue
                    seen.add(expanded)
                    next_frontier.add(expanded)
                    members = sorted((by_path[path] for path in expanded), key=lambda item: item.path)
                    generated[expanded] = self._combine_circuit(members, options)
            frontier = next_frontier
        maximal = []
        for group, result in generated.items():
            can_expand = set().union(*(neighbors[path] for path in group)) - set(group)
            if len(group) == options.circuit_size or not can_expand:
                maximal.append(result)
        return maximal

    @staticmethod
    def _score(results: list[MapResult], options: AnalysisOptions) -> list[MapResult]:
        if not results:
            return []
        maxima = {
            "xp": max(result.xp_hour for result in results) or 1.0,
            "money": max(result.money_hour for result in results) or 1.0,
            "loot": max(result.loot_hour for result in results) or 1.0,
        }
        finite_dangers = [result.danger for result in results if math.isfinite(result.danger)]
        safest = min(finite_dangers) if finite_dangers else 1.0
        for result in results:
            if options.max_health > 0.0:
                result.health_clear_fraction = result.damage_clear / options.max_health
                result.survivable_kills = (
                    options.max_health / result.avg_damage_taken
                    if result.avg_damage_taken > 0.0 else math.inf)
                # Survivability is governed by the largest simultaneous room
                # pull, not every monster along a route that offers safe space
                # between encounters. The optional overlap simulation has
                # already folded pack exposure into danger.
                encounter_multiplier = (
                    1.0 if options.simulate_multiple_enemies else
                    max(result.max_aggro_pack,
                        result.effective_targets_per_attack, 1.0))
                encounter_danger = result.danger * encounter_multiplier
                safety = (min(1.0, options.max_health /
                              max(encounter_danger, 0.001))
                          if math.isfinite(encounter_danger) else 0.0)
            else:
                safety = (min(1.0, safest / max(result.danger, 0.001))
                          if math.isfinite(result.danger) else 0.0)
            result.safety_score = safety
            components = {
                "xp": result.xp_hour / maxima["xp"],
                "money": result.money_hour / maxima["money"],
                "loot": result.loot_hour / maxima["loot"],
                "safety": safety,
                "maneuverability": result.maneuverability,
            }
            if options.ranking in components:
                result.score = 100.0 * components[options.ranking]
            else:
                result.score = 100.0 * (
                    0.40 * components["xp"] + 0.15 * components["money"] +
                    0.10 * components["loot"] + 0.25 * safety +
                    0.10 * components["maneuverability"])
        return sorted(results, key=lambda result: result.score, reverse=True)

    def scan(self, options: AnalysisOptions) -> list[MapResult]:
        self.rejections = []
        matcher = re.compile(options.path_pattern, re.IGNORECASE) if options.path_pattern else None
        results = []
        for path in source_map_files(self.map_root):
            relative = str(path.relative_to(self.root))
            if matcher and matcher.search(relative) is None:
                continue
            location = self.locations.maps.get(relative)
            if (location is not None and
                    self.locations.region_is_excluded(
                        location.region, options.excluded_regions)):
                self.rejections.append((relative, f"excluded region {location.region}"))
                continue
            result = self.analyze_map(path, options)
            if result is not None:
                results.append(result)
        circuits = self._circuits(results, options)
        combined = results + circuits
        for result in combined:
            self._apply_route_timing(result, options)
        combined = [result for result in combined if math.isfinite(result.score)]
        for result in combined:
            result.location, result.nearby_landmarks = self.locations.describe(
                result.map_paths, result.region, result.name)
        return self._score(combined, options)
