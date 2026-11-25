"""Encounter model: who joins a pull, how hard it hits, and how the map is laid out.

This module works on plain data so it can be tested without a content
checkout. ``FarmingAnalyzer`` converts authored spawns into
``EncounterSpawn`` records in one map's coordinate frame (neighbouring
tiled maps are shifted into that frame), and passes the map's walkable
tiles. Everything here is a documented heuristic, not a simulation of the
server. The server behaviour each heuristic stands for is cited by file and
line in the classic server source (``classic/server/src``):

- detection: an idle monster looks for an enemy within its ``item_power``
  tiles; a monster that already has an enemy or was attacked looks
  3 tiles further (``types/monster.c`` 1084-1100, ``find_nearest_enemy``).
  Sleeping or blind monsters look half as far; that is not modelled;
- leash: an engaged monster keeps its enemy while it stays within
  ``max(MAX_AGGRO_RANGE, item_power)`` tiles, and drops it only after
  ``MAX_AGGRO_TIME`` further checks out of range (``types/monster.c``
  558-580, ``include/global.h`` 175-179: range 9, time 12). It is reported
  as ``chase_range``; the estimate uses the style's bad-pull footprint in
  its place;
- linking: on every AI action with an enemy, a spawned monster rolls a one
  in ``monster_signal_chance[Int]`` chance (``server/living.c`` 154-162;
  zero means never) to wake idle monsters of other spawn points. Spawn
  points with the same ``title`` always answer; others answer when their
  monster is an ally standing within ``item_power * 1.5`` minus the
  caller's distance to its enemy (``types/monster.c`` 288-345 and
  351-420). A woken passive monster fights too. Directly placed monsters
  have no spawn-point record, so they neither call nor answer. Deviation:
  allies are monsters of the same faction; factions joined only through an
  alliance parent (``faction_is_alliance()``, ``server/faction.c`` 645) are
  not resolved;
- wandering: ``random_move`` monsters step in a random direction on each
  idle action, limited to ``item_race`` tiles horizontally and
  ``item_level`` tiles vertically from their spawn when either is set
  (``types/monster.c`` 1160-1225, ``move_randomly``);
- movement: ``set_mobile_speed()`` (``server/living.c`` 1851-1875) gives a
  monster twice its authored speed idle and four times while fighting;
  with ``slow_move`` once idle and three times fighting. One tile per
  action;
- casters and archers attack on their own AI actions from range
  (``types/monster.c`` 809-870), so stepping away does not stop them.

Line-of-sight, doors that open or close, scripted AI and live player
positions are not modelled.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from typing import Iterable

# Server constants mirrored as documented data (include/global.h 175-179).
MAX_AGGRO_RANGE = 9
# The server widens detection by 3 tiles only for a monster that already
# has an enemy or an attacker (types/monster.c 1092-1094). The bad pull
# applies the same 3 tiles to idle bystanders as a deliberate safety
# margin for a fight that drifts, a monster that was hit and lost its
# target, or a retreat; it has no server basis for an untouched monster.
ENGAGED_RADIUS_BONUS = 3
# Fight length used for wandering, ally calls and arrival times when the
# character cannot kill the target (infinite kill time). Such a pull is not
# farmable and costs infinite health whatever this value is.
FIGHT_HORIZON = 120.0
# A kiter escaping in open ground has eight directions; each pursuer beyond
# the first is assumed to close one, so nine or more slow melee attackers
# hit as if the character stood still.
KITE_ESCAPE_DIRECTIONS = 8
# Cardinal seam directions in the server's tiled-map index order.
SEAM_NAMES = {0: "north", 1: "east", 2: "south", 3: "west"}


@dataclass(frozen=True)
class StyleProfile:
    """How a character fights, and therefore how far a fight wanders."""

    name: str
    description: str
    # Tiles the fight moves around the pull square in an ordinary pull, and
    # in a bad one (stepping back to heal, being knocked around, kiting
    # further than planned).
    footprint: int
    worst_footprint: int
    # Kiting styles keep slower melee monsters at a distance.
    kites: bool = False
    # AoE styles damage several monsters with one attack.
    aoe: bool = False
    # Pack styles pick the pull square that gathers the most monsters
    # rather than the fewest.
    seeks_packs: bool = False


DEFAULT_KITE_DISTANCE = 4
# A wanderer or an ally link belongs to the bad (worst-case) pull when it is
# more likely than not to join it.
PLAUSIBLE = 0.5


def style_profiles(kite_distance: int = DEFAULT_KITE_DISTANCE) -> dict[str, StyleProfile]:
    """Return the supported combat styles, keyed by their CLI names."""
    kite = max(1, kite_distance)
    return {
        "melee": StyleProfile(
            "melee", "melee 1v1: single pulls, fight in place", 1, 3),
        "melee-pack": StyleProfile(
            "melee-pack", "melee against packs: pull a cluster and fight it", 2, 4,
            seeks_packs=True),
        # A single-target shooter opens from range and backs away along the
        # side it has cleared, so its ordinary footprint is small; the kite
        # distance is how far a bad pull drags it.
        "ranged-kite": StyleProfile(
            "ranged-kite", "ranged single target (bow or wand), kiting", 1, kite,
            kites=True),
        "aoe-kite": StyleProfile(
            "aoe-kite", "AoE caster kiting packs", kite, kite + 3,
            kites=True, aoe=True, seeks_packs=True),
    }


STYLE_NAMES = tuple(style_profiles())


@dataclass
class EncounterSpawn:
    """One authored monster source in a map's coordinate frame."""

    x: int
    y: int
    name: str
    level: int
    # Probability the spawn holds an aggressive monster (0 for passive).
    aggressive: float
    radius: int
    # Incoming DPS while adjacent, the player's kill time, and the existing
    # secondary-risk bonus (casting, bows, poison, ...) in HP.
    dps: float
    kill_seconds: float
    bonus: float = 0.0
    map_path: str = ""
    local_x: int = 0
    local_y: int = 0
    own_map: bool = True
    # Per-AI-action chance to wake allies (0 = never), and the spawn
    # point's ``title`` link group.
    link_chance: float = 0.0
    link_group: str = ""
    # Spawned by a spawn point (False for a directly placed monster).
    spawn_point: bool = True
    faction: str = ""
    # Movement in tiles per second while fighting and while idle.
    engaged_speed: float = 0.0
    idle_speed: float = 0.0
    # Wander rectangle in frame coordinates, inclusive, clipped to the
    # spawn's own map, or None for a monster that stays at its spawn.
    wander_box: tuple[int, int, int, int] | None = None
    wander_tiles: frozenset[tuple[int, int]] = frozenset()
    caster: bool = False
    ranged: bool = False
    damage_types: tuple[str, ...] = ()
    spells: tuple[str, ...] = ()
    melee_types: tuple[str, ...] = ()
    component: int | None = None
    _prefix: dict | None = field(default=None, repr=False, compare=False)

    @property
    def engaged_radius(self) -> int:
        return self.radius + ENGAGED_RADIUS_BONUS

    @property
    def chase_range(self) -> int:
        return max(MAX_AGGRO_RANGE, self.radius)

    @property
    def signal_radius(self) -> int:
        # A caller adjacent to its enemy reaches item_power * 1.5 - 1 tiles.
        return max(0, int(self.radius * 1.5) - 1)

    @property
    def shoots(self) -> bool:
        return self.caster or self.ranged

    def wander_fraction(self, x: int, y: int, reach: int) -> float:
        """Fraction of the wander area within ``reach`` tiles of (x, y)."""
        if not self.wander_tiles:
            return 0.0
        if self._prefix is None:
            self._prefix = _prefix_sums(self.wander_tiles)
        inside = _square_count(self._prefix, x - reach, y - reach, x + reach, y + reach)
        return inside / len(self.wander_tiles)


def _prefix_sums(tiles: Iterable[tuple[int, int]]) -> dict:
    tiles = list(tiles)
    x0 = min(x for x, _y in tiles)
    y0 = min(y for _x, y in tiles)
    x1 = max(x for x, _y in tiles)
    y1 = max(y for _x, y in tiles)
    width = x1 - x0 + 1
    height = y1 - y0 + 1
    grid = [[0] * (width + 1) for _ in range(height + 1)]
    occupied = set(tiles)
    for row in range(height):
        running = 0
        for column in range(width):
            running += (x0 + column, y0 + row) in occupied
            grid[row + 1][column + 1] = grid[row][column + 1] + running
    return {"x0": x0, "y0": y0, "x1": x1, "y1": y1, "grid": grid}


def _square_count(prefix: dict, xa: int, ya: int, xb: int, yb: int) -> int:
    xa = max(xa, prefix["x0"])
    ya = max(ya, prefix["y0"])
    xb = min(xb, prefix["x1"])
    yb = min(yb, prefix["y1"])
    if xa > xb or ya > yb:
        return 0
    grid = prefix["grid"]
    ca, ra = xa - prefix["x0"], ya - prefix["y0"]
    cb, rb = xb - prefix["x0"] + 1, yb - prefix["y0"] + 1
    return grid[rb][cb] - grid[ra][cb] - grid[rb][ca] + grid[ra][ca]


def chebyshev(ax: int, ay: int, bx: int, by: int) -> int:
    return max(abs(ax - bx), abs(ay - by))


@dataclass(frozen=True)
class Fighter:
    """A monster in a pull.

    ``probability`` is the chance it takes part; DPS and kill time are
    conditional on that. ``arrival`` is when it starts hitting, in seconds
    after the pull begins, and ``bonus`` is a flat secondary-risk cost in HP.
    """

    probability: float
    dps: float
    kill_seconds: float
    bonus: float = 0.0
    arrival: float = 0.0


def pull_need(fighters: Iterable[Fighter], healing: float = 0.0,
              targets: float = 1.0) -> float:
    """Health a pull costs at its lowest point (the health trough).

    Expected-value timeline: every arrived monster hits for ``probability *
    dps`` until it dies, the character heals ``healing`` HP per second, and
    health lost cannot be negative (healing does not bank). The character
    kills one arrived monster at a time, choosing the one with the least
    kill seconds per incoming DPS (the order that loses the least health),
    and spends ``probability * kill_seconds / targets`` on it, since AoE
    styles damage ``targets`` monsters with each attack. The deepest deficit
    plus each monster's secondary-risk bonus is the need.
    """
    fighters = [item for item in fighters if item.probability > 0.0]
    if any(not math.isfinite(item.kill_seconds) and item.dps > 0.0 for item in fighters):
        return math.inf
    share = max(1.0, targets)
    work = [item.probability * (item.kill_seconds if math.isfinite(item.kill_seconds) else 0.0)
            / share for item in fighters]
    alive = set(range(len(fighters)))
    now = deficit = peak = 0.0
    while alive:
        arrived = [index for index in alive if fighters[index].arrival <= now + 1e-9]
        upcoming = [fighters[index].arrival for index in alive
                    if fighters[index].arrival > now + 1e-9]
        if not arrived:
            later = min(upcoming)
            deficit = max(0.0, deficit - healing * (later - now))
            now = later
            continue
        focus = min(arrived, key=lambda index: (
            work[index] / (fighters[index].probability * fighters[index].dps)
            if fighters[index].dps > 0.0 else math.inf, index))
        rate = sum(fighters[index].probability * fighters[index].dps
                   for index in arrived) - healing
        step = work[focus]
        if upcoming:
            step = min(step, min(upcoming) - now)
        deficit = max(0.0, deficit + rate * step)
        peak = max(peak, deficit)
        now += step
        work[focus] -= step
        if work[focus] <= 1e-9:
            alive.remove(focus)
    return peak + sum(item.probability * item.bonus for item in fighters)


@dataclass(frozen=True)
class PullEstimate:
    """The best pull of one target spawn."""

    target: int
    x: int
    y: int
    expected: float
    worst: float
    need: float
    worst_need: float
    joiners: tuple[int, ...]
    worst_joiners: tuple[int, ...]


@dataclass(frozen=True)
class TerrainStructure:
    """Walkable layout of one map, from its authored walls and blockers."""

    width: int
    height: int
    walkable_tiles: int
    walkable_fraction: float
    regions: int
    largest_region: int
    open_fraction: float
    kite_room: float
    open_field_tiles: int
    open_field_center: tuple[int, int] | None
    corridor_tiles: int
    doorways: tuple[tuple[int, int], ...]
    dead_ends: int
    seams: dict[str, int]


def _components(tiles: set[tuple[int, int]],
                neighbours: tuple[tuple[int, int], ...]) -> list[set[tuple[int, int]]]:
    remaining = set(tiles)
    result = []
    while remaining:
        start = remaining.pop()
        component = {start}
        frontier = [start]
        while frontier:
            x, y = frontier.pop()
            for dx, dy in neighbours:
                tile = (x + dx, y + dy)
                if tile in remaining:
                    remaining.remove(tile)
                    component.add(tile)
                    frontier.append(tile)
        result.append(component)
    return result


EIGHT = ((-1, -1), (0, -1), (1, -1), (-1, 0), (1, 0), (-1, 1), (0, 1), (1, 1))
FOUR = ((0, -1), (1, 0), (0, 1), (-1, 0))


def component_labels(walkable: set[tuple[int, int]]) -> dict[tuple[int, int], int]:
    """Label walkable tiles by 8-neighbour connected region."""
    labels = {}
    for index, component in enumerate(
            sorted(_components(walkable, EIGHT), key=lambda item: min(item))):
        for tile in component:
            labels[tile] = index
    return labels


def analyze_terrain(width: int, height: int, walkable: set[tuple[int, int]],
                    seams: dict[int, set[tuple[int, int]]] | None = None) -> TerrainStructure:
    """Describe regions, open fields, corridors, doorways and seams.

    - regions: 8-neighbour connected walkable areas;
    - open tiles: every one of the 8 neighbours is walkable; an open field
      is a connected area of tiles with a clear 5x5 square around them,
      which is where kiting works;
    - corridor tiles: exactly two opposite cardinal neighbours are walkable,
      so the passage is one tile wide. A run of at most two corridor tiles
      is a doorway (a chokepoint between areas); longer runs are corridors;
    - dead ends: walkable tiles with a single walkable cardinal neighbour;
    - kite room: share of walkable tiles with at least 6 of 8 walkable
      neighbours, so a kiter can keep stepping away; beyond a crossable
      seam tile the neighbouring map counts as open;
    - seams: per cardinal direction with a tiled neighbour, the number of
      edge tiles that are walkable on both sides.
    """
    total = max(1, width * height)
    crossing = set().union(*(seams or {}).values()) if seams else set()

    def roomy(x: int, y: int) -> bool:
        count = 0
        for dx, dy in EIGHT:
            nx, ny = x + dx, y + dy
            inside = 0 <= nx < width and 0 <= ny < height
            if (nx, ny) in walkable or (not inside and (x, y) in crossing):
                count += 1
        return count >= 6

    regions = _components(walkable, EIGHT)
    open_tiles = {tile for tile in walkable
                  if all((tile[0] + dx, tile[1] + dy) in walkable for dx, dy in EIGHT)}
    clear = {tile for tile in walkable
             if all((tile[0] + dx, tile[1] + dy) in walkable
                    for dx in range(-2, 3) for dy in range(-2, 3))}
    fields = _components(clear, FOUR)
    largest_field = max(fields, key=len, default=set())
    corridor = set()
    dead_ends = 0
    for x, y in walkable:
        north, east, south, west = (
            (x + dx, y + dy) in walkable for dx, dy in FOUR)
        count = north + east + south + west
        if count == 1:
            dead_ends += 1
        if count == 2 and ((north and south) or (east and west)):
            corridor.add((x, y))
    doorways = []
    for run in _components(corridor, EIGHT):
        if len(run) <= 2:
            doorways.append(min(run))
    seam_counts = {}
    for direction, tiles in sorted((seams or {}).items()):
        if direction in SEAM_NAMES and tiles:
            seam_counts[SEAM_NAMES[direction]] = len(tiles)
    center = None
    if largest_field:
        cx = sum(x for x, _y in largest_field) / len(largest_field)
        cy = sum(y for _x, y in largest_field) / len(largest_field)
        center = min(largest_field, key=lambda tile: (
            (tile[0] - cx) ** 2 + (tile[1] - cy) ** 2, tile))
    return TerrainStructure(
        width, height, len(walkable), len(walkable) / total,
        sum(1 for region in regions if len(region) >= 4),
        max((len(region) for region in regions), default=0),
        len(open_tiles) / max(1, len(walkable)),
        sum(1 for tile in walkable if roomy(*tile)) / max(1, len(walkable)),
        len(largest_field), center, len(corridor),
        tuple(sorted(doorways)), dead_ends, seam_counts)


@dataclass(frozen=True)
class EncounterOptions:
    """Character inputs for one encounter estimate."""

    style: StyleProfile
    healing: float = 0.0
    # Player movement in tiles per second.
    player_speed: float = 8.0
    # Monsters damaged by each AoE attack (AoE styles only).
    aoe_targets: float = 1.0


@dataclass
class EncounterModel:
    """Expected and worst pulls of one map for one combat style."""

    style: str
    spawns: list[EncounterSpawn]
    pulls: list[PullEstimate]
    terrain: TerrainStructure
    room: float
    # Chance each pull still happens (its target was not killed earlier as
    # a joiner), in clear order.
    weights: list[float] = field(default_factory=list)

    @property
    def own(self) -> list[int]:
        return [index for index, spawn in enumerate(self.spawns) if spawn.own_map]

    def _likely(self) -> list[PullEstimate]:
        """Pulls that happen more likely than not (their target survived)."""
        weights = self.weights or [1.0] * len(self.pulls)
        likely = [pull for pull, weight in zip(self.pulls, weights) if weight >= PLAUSIBLE]
        return likely or list(self.pulls)

    def hardest(self) -> PullEstimate | None:
        return max(self._likely(), key=lambda pull: (pull.need, pull.worst_need, pull.expected),
                   default=None)

    @property
    def expected_pack(self) -> float:
        return max((pull.expected for pull in self._likely()), default=0.0)

    @property
    def mean_expected_pack(self) -> float:
        weights = self.weights or [1.0] * len(self.pulls)
        if not self.pulls or sum(weights) <= 0.0:
            return 0.0
        return sum(weight * pull.expected
                   for weight, pull in zip(weights, self.pulls)) / sum(weights)

    @property
    def worst_pack(self) -> float:
        return max((pull.worst for pull in self._likely()), default=0.0)

    @property
    def need(self) -> float:
        return max((pull.need for pull in self._likely()), default=0.0)

    @property
    def worst_need(self) -> float:
        return max((pull.worst_need for pull in self._likely()), default=0.0)


def fight_seconds(spawn: EncounterSpawn, options: EncounterOptions,
                  room: float, attackers: float = 1.0) -> float:
    return spawn.kill_seconds / kite_attack_share(spawn, options, room, attackers)


def open_directions(attackers: float) -> float:
    """Share of escape directions still open: each attacker beyond the
    first closes one of ``KITE_ESCAPE_DIRECTIONS``."""
    return max(0.0, 1.0 - max(0.0, attackers - 1.0) / KITE_ESCAPE_DIRECTIONS)


def unkillable(spawn: EncounterSpawn) -> bool:
    return not math.isfinite(spawn.kill_seconds)


def unkillable_harmless(spawn: EncounterSpawn, aoe: bool = False) -> bool:
    """Cannot be killed, and will not hurt the character: skip it.

    A passive monster is left alone by single-target styles. An AoE style
    provokes every passive monster inside its footprint, so for AoE only a
    monster that deals no damage is harmless.
    """
    if not unkillable(spawn):
        return False
    if aoe:
        return spawn.dps <= 0.0
    return spawn.aggressive <= 0.0 or spawn.dps <= 0.0


def _provoked(other: EncounterSpawn, x: int, y: int, component: int | None,
              style: StyleProfile) -> float:
    """Chance an AoE fight at (x, y) hits, and so provokes, a passive monster.

    AoE styles damage everything inside their footprint (the kite
    distance), and a damaged monster turns on its attacker
    (``types/monster.c`` 479-512, ``attacked_by`` in ``find_enemy()``).
    The passive share of the spawn (``1 - aggressive``) joins from the
    first second.
    """
    if not style.aoe or other.aggressive >= 1.0:
        return 0.0
    if (component is not None and other.component is not None and
            other.component != component and not other.shoots):
        return 0.0
    if chebyshev(other.x, other.y, x, y) > style.footprint:
        return 0.0
    return 1.0 - other.aggressive


def horizon(seconds: float) -> float:
    """A finite, non-negative fight length for spreads and arrival times."""
    if not math.isfinite(seconds):
        return FIGHT_HORIZON
    return max(0.0, seconds)


def melee_uptime(spawn: EncounterSpawn, options: EncounterOptions,
                 room: float, attackers: float = 1.0) -> float:
    """Fraction of a fight in which this monster is hitting the character.

    Melee styles stand next to everything. Casters and archers hit from
    range whatever the style. A kiter keeps a melee monster that is slower
    than the character away only where there is kite room (``room``), and
    only while escape directions stay open: each attacker beyond the first
    closes one of ``KITE_ESCAPE_DIRECTIONS``. The avoided share is
    ``room * max(0, 1 - (attackers - 1) / 8)``, so a pack of nine or more
    hits as hard as it would a melee character. A monster at least as fast
    as the character cannot be kited.
    """
    if not options.style.kites or spawn.shoots:
        return 1.0
    if options.player_speed <= 0.0 or spawn.engaged_speed >= options.player_speed:
        return 1.0
    return 1.0 - room * open_directions(attackers)


def kite_attack_share(spawn: EncounterSpawn, options: EncounterOptions,
                      room: float, attackers: float = 1.0) -> float:
    """Share of time a kiter spends attacking rather than stepping away.

    Stepping away costs ``monster speed / player speed`` of the attack time,
    but only while the kiter can still step away: the penalty shrinks with
    the open escape directions, so a pack that pins the kiter costs the same
    time as standing and fighting.
    """
    if not options.style.kites or spawn.shoots or options.player_speed <= 0.0:
        return 1.0
    if spawn.engaged_speed >= options.player_speed:
        return 1.0
    return 1.0 / (1.0 + open_directions(attackers) *
                  spawn.engaged_speed / options.player_speed)


def _join_probability(spawn: EncounterSpawn, x: int, y: int, reach: int,
                      sweep: float, component: int | None) -> float:
    if spawn.aggressive <= 0.0:
        return 0.0
    if (component is not None and spawn.component is not None and
            spawn.component != component and not spawn.shoots):
        return 0.0
    if spawn.wander_tiles:
        return spawn.aggressive * spawn.wander_fraction(x, y, reach + int(sweep))
    return spawn.aggressive if chebyshev(spawn.x, spawn.y, x, y) <= reach else 0.0


def _link_probability(caller: EncounterSpawn, other: EncounterSpawn,
                      seconds: float) -> float:
    """Chance ``caller`` wakes ``other`` during a fight of ``seconds``."""
    if caller.link_chance <= 0.0 or not caller.spawn_point or not other.spawn_point:
        return 0.0
    if not (caller.link_group and caller.link_group == other.link_group):
        if not caller.faction or caller.faction != other.faction:
            return 0.0
        if chebyshev(caller.x, caller.y, other.x, other.y) > caller.signal_radius:
            return 0.0
    actions = caller.engaged_speed * horizon(seconds)
    return 1.0 - (1.0 - caller.link_chance) ** actions


def estimate(spawns: list[EncounterSpawn], walkable: set[tuple[int, int]],
             terrain: TerrainStructure, options: EncounterOptions) -> EncounterModel:
    """Estimate the best pull of every spawn on the map (``own_map``).

    For a target spawn T the character picks a walkable pull square from
    which T engages: within T's detection radius when T is aggressive,
    adjacent when it is passive, or within kiting distance for kiting
    styles. Single-pull styles take the square with the fewest expected
    extra attackers; pack styles the most.

    At a pull square P, during a fight lasting T's (style-adjusted) kill
    time:

    - a static aggressive spawn joins when its detection radius reaches the
      fight's footprint (P plus the style's footprint);
    - a wanderer joins with the share of its wander area within that reach,
      widened by the random-walk spread ``sqrt(idle steps during the
      fight)``;
    - an ally joins with the chance that T's link rolls succeed at least
      once during the fight;
    - melee monsters in another walkable region cannot reach P.

    Monsters already within reach when the pull starts hit from the first
    second; wanderers that walk in later and called allies arrive, on
    average, half-way through T's fight.

    The bad (worst-case) pull uses a 3-tile margin on every radius (see
    ``ENGAGED_RADIUS_BONUS``) and the style's worst footprint, and adds every wanderer and ally link that is more
    likely than not to join; those beyond the ordinary reach arrive half-way
    through the fight.
    """
    labels = component_labels(walkable)
    for spawn in spawns:
        if spawn.component is None:
            spawn.component = labels.get((spawn.x, spawn.y))
            if spawn.component is None:
                around = sorted({labels[(spawn.x + dx, spawn.y + dy)] for dx, dy in EIGHT
                                 if (spawn.x + dx, spawn.y + dy) in labels})
                spawn.component = around[0] if len(around) == 1 else None
    style = options.style
    room = terrain.kite_room
    # A monster the character cannot kill and that cannot hurt or will not
    # attack is left alone: it is never pulled. An unkillable monster that
    # attacks and hurts makes its pull (and so the map) not farmable.
    own = [index for index, spawn in enumerate(spawns)
           if spawn.own_map and not unkillable_harmless(spawn, options.style.aoe)]
    alive = [1.0] * len(spawns)
    # First pass: every pull on the fully populated map, to order the clear.
    first = {index: _best_pull(index, spawns, alive, walkable, labels, options, room)
             for index in own}
    order = sorted(own, key=lambda index: (first[index][0].need, first[index][0].expected,
                                           spawns[index].y, spawns[index].x))
    pulls: list[PullEstimate] = []
    weights: list[float] = []
    for index in order:
        presence = alive[index]
        if presence <= 1e-6:
            continue
        pull, joined = _best_pull(index, spawns, alive, walkable, labels, options,
                                  room)
        pulls.append(pull)
        weights.append(presence)
        alive[index] = 0.0
        for other, probability in joined:
            alive[other] = max(0.0, alive[other] - probability)
    return EncounterModel(style.name, spawns, pulls, terrain, room, weights)


def _best_pull(index: int, spawns: list[EncounterSpawn], alive: list[float],
               walkable: set[tuple[int, int]], labels: dict[tuple[int, int], int],
               options: EncounterOptions, room: float,
               ) -> tuple[PullEstimate, list[tuple[int, float]]]:
    """Best pull of one target with the monsters still ``alive`` (0..1 each)."""
    style = options.style
    targets = options.aoe_targets if style.aoe else 1.0
    target = spawns[index]
    raw_seconds = fight_seconds(target, options, room)
    farmable = math.isfinite(raw_seconds)
    seconds = horizon(raw_seconds)
    late = seconds / 2.0
    candidates = _pull_squares(target, walkable, style)
    x0 = min(x for x, _y in candidates)
    y0 = min(y for _x, y in candidates)
    x1 = max(x for x, _y in candidates)
    y1 = max(y for _x, y in candidates)
    # Only living spawns that could reach some candidate square matter.
    relevant = []
    for other_index, other in enumerate(spawns):
        presence = alive[other_index]
        if other_index == index or presence <= 1e-6:
            continue
        linked = _link_probability(target, other, seconds)
        if other.aggressive <= 0.0 and linked <= 0.0 and not style.aoe:
            continue
        sweep = math.sqrt(other.idle_speed * seconds) if other.wander_tiles else 0.0
        reach = max(other.radius + style.footprint + int(sweep),
                    other.engaged_radius + style.worst_footprint)
        gap = max(x0 - other.x, other.x - x1, y0 - other.y, other.y - y1, 0)
        if other.wander_tiles or gap <= reach or linked > 0.0:
            relevant.append((other_index, other, presence, linked, sweep))
    best = None
    for x, y in candidates:
        component = labels.get((x, y))
        joiners: list[tuple[int, float, float]] = []
        worst: list[tuple[int, float]] = []
        for other_index, other, presence, linked, sweep in relevant:
            reach = other.radius + style.footprint
            provoked = presence * _provoked(other, x, y, component, style)
            start = presence * _join_probability(other, x, y, reach, 0.0, component)
            direct = (presence * _join_probability(other, x, y, reach, sweep, component)
                      if other.wander_tiles else start)
            if provoked > 0.0:
                start = 1.0 - (1.0 - start) * (1.0 - provoked)
                direct = 1.0 - (1.0 - direct) * (1.0 - provoked)
            total = 1.0 - (1.0 - direct) * (1.0 - presence * linked)
            if total > 1e-6:
                joiners.append((other_index, start, total - start))
            if presence >= PLAUSIBLE and (
                    _worst_joins(other, x, y, component, style, sweep) or
                    linked >= PLAUSIBLE or provoked >= PLAUSIBLE):
                worst.append((other_index, 0.0 if start >= PLAUSIBLE else late))
        expected = 1.0 + sum(start + extra for _other, start, extra in joiners)
        distance = chebyshev(x, y, target.x, target.y)
        if style.seeks_packs:
            key = (-expected, -len(worst), -distance, y, x)
        else:
            key = (expected, len(worst), -distance, y, x)
        if best is None or key < best[0]:
            best = (key, x, y, joiners, worst, expected)
    assert best is not None
    _key, x, y, joiners, worst, expected = best
    expected_fighters = [(target, 1.0, 0.0)]
    for other, start, extra in joiners:
        if start > 0.0:
            expected_fighters.append((spawns[other], start, 0.0))
        if extra > 0.0:
            expected_fighters.append((spawns[other], extra, late))
    need = _cheaper_pull(expected_fighters, options, room, expected, targets)
    worst_need = _cheaper_pull(
        [(target, 1.0, 0.0)] + [(spawns[other], 1.0, arrival) for other, arrival in worst],
        options, room, 1.0 + len(worst), targets)
    if not farmable:
        # The character cannot kill the target: not a farmable pull.
        need = worst_need = math.inf
    pull = PullEstimate(
        index, x, y, expected, 1.0 + len(worst), need, worst_need,
        tuple(other for other, _start, _extra in joiners),
        tuple(other for other, _arrival in worst))
    return pull, [(other, start + extra) for other, start, extra in joiners]


def _pull_squares(target: EncounterSpawn, walkable: set[tuple[int, int]],
                  style: StyleProfile) -> list[tuple[int, int]]:
    """Walkable squares from which the character can start a fight with ``target``.

    An aggressive target engages within its detection radius, a passive one
    must be attacked from an adjacent square, and kiting styles can open
    from their kiting distance (bad-pull footprint). A wanderer can be met anywhere it roams, so
    every other square of its own-map wander area (sampled on a two-tile
    grid) is a candidate too.
    """
    pull_range = target.radius if target.aggressive > 0.0 else 1
    if style.kites:
        pull_range = max(pull_range, style.worst_footprint)
    squares = {
        (x, y) for x in range(target.x - pull_range, target.x + pull_range + 1)
        for y in range(target.y - pull_range, target.y + pull_range + 1)
        if (x, y) in walkable and (x, y) != (target.x, target.y)
    }
    if target.wander_tiles:
        squares |= {(x, y) for x, y in target.wander_tiles
                    if (x, y) in walkable and x % 2 == 0 and y % 2 == 0}
    return sorted(squares) or [(target.x, target.y)]


def _fighter(spawn: EncounterSpawn, probability: float, arrival: float,
             options: EncounterOptions, room: float, attackers: float = 1.0) -> Fighter:
    return Fighter(
        probability,
        spawn.dps * melee_uptime(spawn, options, room, attackers),
        fight_seconds(spawn, options, room, attackers),
        spawn.bonus, arrival)


def _cheaper_pull(fighters: list[tuple[EncounterSpawn, float, float]],
                  options: EncounterOptions, room: float, attackers: float,
                  targets: float) -> float:
    """Health trough of a pull; a kiter stands and fights when that is cheaper.

    ``fighters`` are (spawn, probability, arrival). For a kiting style the
    same pack is also costed standing still (full uptime, no stepping-away
    time) and the cheaper of the two is taken, so kiting never costs more
    than standing and fighting the same monsters.
    """
    kite = pull_need([_fighter(spawn, probability, arrival, options, room, attackers)
                      for spawn, probability, arrival in fighters],
                     options.healing, targets)
    if not options.style.kites:
        return kite
    standing = replace(options, style=replace(options.style, kites=False))
    stand = pull_need([_fighter(spawn, probability, arrival, standing, room, attackers)
                       for spawn, probability, arrival in fighters],
                      options.healing, targets)
    return min(kite, stand)


def _worst_joins(other: EncounterSpawn, x: int, y: int, component: int | None,
                 style: StyleProfile, sweep: float) -> bool:
    """Whether ``other`` belongs to the bad pull at (x, y).

    A static aggressive spawn joins when its radius plus the 3-tile margin
    reaches the worst footprint. A wanderer joins when it is more likely
    than not within that reach (widened by its random-walk spread) during
    the fight.
    """
    if other.aggressive <= 0.0:
        return False
    if (component is not None and other.component is not None and
            other.component != component and not other.shoots):
        return False
    reach = other.engaged_radius + style.worst_footprint
    if other.wander_tiles:
        return other.wander_fraction(x, y, reach + int(sweep)) >= PLAUSIBLE
    return chebyshev(other.x, other.y, x, y) <= reach


def safety_from_need(need: float, health: float) -> float:
    """Expected-pull safety: share of the health bar left at the trough."""
    if health <= 0.0:
        return 1.0
    if not math.isfinite(need):
        return 0.0
    return max(0.0, min(1.0, 1.0 - need / health))


def bad_pull_safety(need: float, health: float) -> float:
    """Bad-pull safety: ``1 / (1 + need in health bars)``.

    The bad pull usually costs more than one health bar, where the linear
    form would read zero for every dense map. This form stays ordered:
    half a bar reads 0.67, one bar 0.5, three bars 0.25.
    """
    if health <= 0.0:
        return 1.0
    if not math.isfinite(need):
        return 0.0
    return 1.0 / (1.0 + max(0.0, need) / health)


# Weight of the expected pull versus the bad pull in the blended safety.
EXPECTED_WEIGHT = 0.75


def blended_safety(expected: float, worst: float) -> float:
    """``0.75 * expected-pull safety + 0.25 * bad-pull safety``."""
    return EXPECTED_WEIGHT * expected + (1.0 - EXPECTED_WEIGHT) * worst


def rating(safety: float) -> str:
    """Human label for a blended safety value."""
    if safety >= 0.85:
        return "easy"
    if safety >= 0.65:
        return "fair"
    if safety >= 0.40:
        return "hard"
    if safety > 0.0:
        return "deadly"
    return "lethal"


def hotspots(model: EncounterModel, limit: int = 12) -> list[dict]:
    """Designer-facing hotspots: clusters, wanderers, chokepoints, shooters."""
    spawns = model.spawns
    own = [index for index in model.own if spawns[index].aggressive > 0.0]
    result: list[dict] = []
    # Dense clusters: single-linkage over the engaged radius.
    remaining = set(own)
    while remaining:
        start = remaining.pop()
        cluster = {start}
        frontier = [start]
        while frontier:
            current = frontier.pop()
            near = {
                other for other in remaining
                if chebyshev(spawns[current].x, spawns[current].y,
                             spawns[other].x, spawns[other].y) <=
                max(spawns[current].engaged_radius, spawns[other].engaged_radius)
            }
            remaining -= near
            cluster |= near
            frontier.extend(near)
        if len(cluster) >= 3:
            members = sorted(cluster)
            cx = round(sum(spawns[i].x for i in members) / len(members))
            cy = round(sum(spawns[i].y for i in members) / len(members))
            result.append({
                "kind": "dense_cluster", "x": cx, "y": cy, "spawns": len(members),
                "monsters": sorted({spawns[i].name for i in members}),
                "reason": f"{len(members)} aggressive spawns each within engaged "
                          "detection reach of another; a pull or a retreat here "
                          "chains into a pack",
            })
    wanderers = [index for index in model.own if spawns[index].wander_tiles and
                 spawns[index].aggressive > 0.0]
    if wanderers:
        coverage: dict[tuple[int, int], int] = {}
        for index in wanderers:
            for tile in spawns[index].wander_tiles:
                coverage[tile] = coverage.get(tile, 0) + 1
        peak_tile, peak = max(coverage.items(), key=lambda item: (item[1], -item[0][1], -item[0][0]))
        walkable = max(1, model.terrain.walkable_tiles)
        own_coverage = sum(1 for (x, y) in coverage
                           if 0 <= x < model.terrain.width and 0 <= y < model.terrain.height)
        result.append({
            "kind": "wanderer_overlap" if peak >= 2 else "wanderers",
            "x": peak_tile[0], "y": peak_tile[1], "spawns": len(wanderers),
            "overlap": peak,
            "coverage": round(min(1.0, own_coverage / walkable), 3),
            "monsters": sorted({spawns[i].name for i in wanderers}),
            "reason": f"{len(wanderers)} aggressive wanderers roam "
                      f"{min(1.0, own_coverage / walkable):.0%} of the walkable map; "
                      f"up to {peak} overlap on one tile, so no pull square is "
                      "reliably clear",
        })
    guarded = []
    for x, y in model.terrain.doorways:
        guards = [index for index in own
                  if chebyshev(spawns[index].x, spawns[index].y, x, y) <=
                  spawns[index].engaged_radius]
        if guards:
            guarded.append((x, y, guards))
    # The three doorways with the most guards; forests have many tree gaps.
    for x, y, guards in sorted(guarded, key=lambda item: (-len(item[2]), item[1], item[0]))[:3]:
        if guards:
            result.append({
                "kind": "guarded_chokepoint", "x": x, "y": y, "spawns": len(guards),
                "monsters": sorted({spawns[i].name for i in guards}),
                "reason": f"doorway within engaged reach of {len(guards)} spawn(s); "
                          "retreating through it pulls them",
            })
    for index in model.own:
        spawn = spawns[index]
        if spawn.shoots:
            kind = "caster" if spawn.caster else "ranged"
            passive = spawn.aggressive <= 0.0
            result.append({
                "kind": kind, "x": spawn.x, "y": spawn.y, "spawns": 1,
                "monsters": [spawn.name], "damage_types": list(spawn.damage_types),
                "spells": list(spawn.spells), "passive": passive,
                "reason": f"{'passive ' if passive else ''}{spawn.name} attacks from range"
                          f"{' with ' + ', '.join(spawn.damage_types) if spawn.damage_types else ''}"
                          f"; kiting does not avoid it{' once provoked' if passive else ''}",
            })
    seam_spawns = seam_reachers(model)
    if seam_spawns:
        result.append({
            "kind": "seam_reach", "x": None, "y": None, "spawns": len(seam_spawns),
            "monsters": sorted({spawns[i].name for i in seam_spawns}),
            "maps": sorted({spawns[i].map_path for i in seam_spawns}),
            "reason": f"{len(seam_spawns)} spawn(s) on adjacent maps can reach "
                      "this map's edge tiles",
        })
    hardest = model.hardest()
    if hardest is not None:
        target = spawns[hardest.target]
        result.append({
            "kind": "hardest_pull", "x": hardest.x, "y": hardest.y,
            "spawns": round(hardest.expected, 2),
            "monsters": [target.name],
            "target": [target.x, target.y],
            "reason": f"best square to pull {target.name} at ({target.x}, {target.y}) "
                      f"still expects {hardest.expected:.1f} attackers "
                      f"(worst {hardest.worst:g})",
        })
    order = {"hardest_pull": 0, "dense_cluster": 1, "wanderer_overlap": 2,
             "caster": 3, "ranged": 3, "guarded_chokepoint": 4, "wanderers": 5,
             "seam_reach": 6}
    result.sort(key=lambda item: (order.get(item["kind"], 9), -float(item["spawns"] or 0)))
    return result[:limit]


def seam_reachers(model: EncounterModel) -> list[int]:
    """Aggressive spawns on adjacent maps whose engaged reach crosses the edge."""
    width, height = model.terrain.width, model.terrain.height

    def outside(x: int, y: int) -> int:
        return max(max(0, -x, x - (width - 1)), max(0, -y, y - (height - 1)))

    result = []
    for index, spawn in enumerate(model.spawns):
        if spawn.own_map or spawn.aggressive <= 0.0:
            continue
        reach = spawn.engaged_radius
        if outside(spawn.x, spawn.y) <= reach or any(
                outside(x, y) <= reach for x, y in spawn.wander_tiles):
            result.append(index)
    return result


def reasons(model: EncounterModel, options: EncounterOptions,
            health: float) -> list[str]:
    """Short sentences explaining a rating, most important first."""
    spawns = model.spawns
    terrain = model.terrain
    own = model.own
    lines = []
    hardest = model.hardest()
    aggressive = [index for index in own if spawns[index].aggressive > 0.0]
    walkable = max(1, terrain.walkable_tiles)
    lines.append(
        f"{len(own)} spawns ({len(aggressive)} aggressive) on {terrain.width}x{terrain.height}"
        f" ({len(own) * 100.0 / walkable:.1f} per 100 walkable tiles)")
    if hardest is not None:
        target = spawns[hardest.target]
        joined = sorted({spawns[i].name for i in hardest.joiners})
        lines.append(
            f"hardest pull: {target.name} from ({hardest.x}, {hardest.y}) expects "
            f"{hardest.expected:.1f} attackers, worst {hardest.worst:g}"
            + (f" (joined by {', '.join(joined)})" if joined else ""))
        alive_dps = sum(spawns[i].dps * melee_uptime(spawns[i], options, model.room,
                                                     hardest.worst)
                        for i in (hardest.target,) + hardest.worst_joiners)
        if health > 0.0:
            lines.append(
                f"expected pull costs {hardest.need:.0f} of {health:g} HP "
                f"(worst {hardest.worst_need:.0f}); the bad pull deals {alive_dps:.1f} DPS "
                f"against {options.healing:g} HP/s healing")
        else:
            lines.append(
                f"expected pull costs {hardest.need:.0f} HP (worst "
                f"{hardest.worst_need:.0f}); up to {alive_dps:.1f} DPS in against "
                f"{options.healing:g} HP/s healing")
    immune = sorted({spawns[index].name for index in own
                     if unkillable(spawns[index]) and
                     not unkillable_harmless(spawns[index], options.style.aoe)})
    if immune:
        lines.insert(1, "not farmable: the character cannot kill " + ", ".join(immune))
    skipped = sorted({spawns[index].name for index in own
                      if unkillable_harmless(spawns[index], options.style.aoe)})
    if skipped:
        lines.append("left alone (cannot be killed, passive or harmless): "
                     + ", ".join(skipped))
    wanderers = [index for index in aggressive if spawns[index].wander_tiles]
    if wanderers:
        lines.append(f"{len(wanderers)} aggressive wanderer(s) roam the map")
    shooters = [index for index in own if spawns[index].shoots]
    if shooters:
        types = sorted({kind for i in shooters for kind in spawns[i].damage_types})
        lines.append(
            f"{len(shooters)} caster/ranged spawn(s)"
            + (f" dealing {', '.join(types)}" if types else "")
            + "; they hit from range in every style")
    linkers = [index for index in aggressive if spawns[index].link_chance > 0.0]
    if linkers:
        best = max(spawns[i].link_chance for i in linkers)
        lines.append(
            f"{len(linkers)} spawn(s) can call allies (up to 1 in {round(1 / best)} per action)")
    if options.style.kites:
        melee = [index for index in aggressive if not spawns[index].shoots]
        if melee:
            slow = [index for index in melee
                    if spawns[index].engaged_speed < options.player_speed]
            if slow:
                crowd = hardest.expected if hardest is not None else 1.0
                uptime = sum(melee_uptime(spawns[i], options, model.room, crowd)
                             for i in slow) / len(slow)
                lines.append(
                    f"{len(slow)} melee spawn(s) slower than the character; kiting "
                    f"keeps them off for {1 - uptime:.0%} of the hardest pull "
                    f"({model.room:.0%} of walkable tiles have kite room, "
                    f"~{crowd:.1f} attackers closing escape directions)")
            fast = len(melee) - len(slow)
            if fast:
                lines.append(f"{fast} melee spawn(s) as fast as the character cannot be kited")
    if terrain.doorways:
        lines.append(f"{len(terrain.doorways)} doorway chokepoint(s)")
    if terrain.seams:
        lines.append("crossable seams: " + ", ".join(
            f"{name} {count}" for name, count in terrain.seams.items()))
    seam = seam_reachers(model)
    if seam:
        lines.append(f"{len(seam)} spawn(s) across seams can reach the edge")
    return lines
