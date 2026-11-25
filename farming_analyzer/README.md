# Farming analyzer

The `farming_analyzer` package ranks repeatable farming locations directly
from the classic Atrinik server and authored content. In the standard Atrinik
workspace, it reads the sibling `classic/server` and `content` checkouts. It
scans source maps without collecting resources or changing runtime state.

The analyzer requires Python 3.11 or newer and uses only the Python standard
library. Initialize the workspace's classic cohort before running it so the
`classic` and shared `content@main` checkouts are present.

Run it from the Atrinik workspace root with a combat skill level and measured attack:

```sh
python3 -m tools.farming_analyzer 18 --damage-per-attack 48 --attack-delay 0.667
```

If those checkouts are elsewhere, select them explicitly. `--server-root`
names the classic server's `src` directory, while `--content-root` names the
checkout containing `arch/` and `maps/`:

```sh
python3 -m farming_analyzer 18 --damage-per-attack 48 --attack-delay 0.667 \
  --server-root ../classic/server/src --content-root ../content
```

Character level is not necessarily the relevant value. Atrinik awards combat
XP using the level of the killing skill, so supply that skill level.

Useful variants:

```sh
# Scheduled nighttime monsters.
python3 -m tools.farming_analyzer 18 --damage-per-attack 48 \
  --attack-delay 0.667 --time 00:00

# Use measured hit damage/rate and monster slash protection for kill-time estimates.
python3 -m tools.farming_analyzer 18 --damage-per-attack 48 \
  --attack-delay 0.667 --attack-type slash

# Model a single-target spell, including the full player+crystal burst and rest.
python3 -m tools.farming_analyzer 18 --damage-per-attack 48 --attack-delay 1.2 \
  --attack-type magic --mana-cost 8 --mana-regen 2.5 \
  --max-mana 180 --mana-crystal 500 --meditation

# Model an AoE spell that averages four monsters per cast.
python3 -m tools.farming_analyzer 18 --damage-per-attack 60 --attack-delay 1 \
  --attack-type fire --targets-per-attack 4 --mana-cost 14 \
  --mana-regen 2.5 --max-mana 180 --mana-crystal 500

# Require reasonably open terrain and inspect maneuverability as its own ranking.
python3 -m tools.farming_analyzer 18 --damage-per-attack 60 --attack-delay 1 \
  --targets-per-attack 4 --min-maneuverability 0.6 --ranking maneuverability

# Simulate the final melee stats shown in the player doll.
python3 -m tools.farming_analyzer 18 --melee-damage 50 --weapon-class 25 \
  --weapon-speed 2.0 --melee-attack slash=100

# Model incoming damage against the character's actual defence.
python3 -m tools.farming_analyzer 18 --damage-per-attack 48 --attack-delay 0.667 \
  --character-level 50 --character-speed 1.03 --max-health 850 --player-ac 31 \
  --player-protection slash=20 --player-protection pierce=12

# Inspect a map family and include map-reset-only bosses.
python3 -m tools.farming_analyzer 18 --damage-per-attack 48 --attack-delay 0.667 \
  --path 'old_outpost' --include-static

# Exclude an island or region by ID or human-readable name; repeat as needed.
python3 -m tools.farming_analyzer 18 --damage-per-attack 48 --attack-delay 0.667 \
  --exclude-region 'Eld Woods' \
  --exclude-region 'Strakewood Island'

# Disable adjacent world-tile circuits or emit JSON for further analysis.
python3 -m tools.farming_analyzer 18 --damage-per-attack 48 --attack-delay 0.667 \
  --circuit-size 1
python3 -m tools.farming_analyzer 18 --damage-per-attack 48 --attack-delay 0.667 \
  --json > farming-level-18.json
```

The default safety filter rejects any location containing an active monster
more than five levels above the higher of the supplied skill level and
`--character-level`. This lets a veteran character train a lower-level skill
in areas the character can survive. Change the allowance with
`--max-level-gap`. The default minimum average XP is 35% of the server's
per-kill XP cap; change it with `--min-xp-fraction`.

`--exclude-region NAME` matches case-insensitive region IDs and display names.
It also excludes child regions, so excluding `Eld Woods` removes both
`eld_woods_island` and its `clearhaven` child. The option may be repeated, and
excluded maps are removed before adjacent-map circuits and score normalization.

## Exact inputs

The analyzer reads these source-of-truth values on every invocation:

- `new_levels`, `lev_exp`, and `level_color`, then mirrors
  `calc_level_difference()` and `calc_skill_exp()`;
- spawn-point monsters, alternative weights, explicit levels, time schedules,
  and map headers from authored maps;
- archetype XP, HP, damage, attacks, protections, aggression, and treasure-list
  identifiers;
- monster HP, WC, and base damage scaling from `living_update_monster()`;
- melee hit rolls and attack-type damage from `attack_object()` and
  `attack_hit()`, combat movement speed from `set_mobile_speed()`, and the
  `speed_left`/`weapon_speed_left` scheduling in the main loop;
- player auto-attack timing from `player.action_attack`, including the server's
  conversion of internal weapon delay ticks to the seconds displayed by the
  client;
- all authored `.trs` treasure branches, including `chance`, `chance_fix`,
  `more`, `yes`/`no`, nested lists, difficulty gates, wealth, and explicit
  `rand_drop` inventory;
- spawn-point speed and chance gate, the configured server tick length, map
  reset defaults, and the shop's 20% selling multiplier.
- static collision terrain and blocking objects from authored maps, plus NPC
  faction ancestry and NPC/monster detection radii used to identify contested
  battle spawns.

The movement conversion is anchored in `classic/server/src/socket/request.c` (raw
`CS_STAT_SPEED` and one-unit move cost), `classic/server/src/server/main.c`
(`speed_left` scheduling), and `classic/server/src/include/config.h` (the default
125,000 microsecond tick). Per-spawn event timing follows
`server/src/types/spawn_point.c` plus the merged spawn archetype/map values.
The AoE caveat follows `cast_cone()` in `server/src/server/spell_util.c` and
the wall-aware propagation in `server/src/types/cone.c`.

Normal spawn points have an expected renewal period of approximately 315
seconds with the current defaults: `0.125 / 0.00317 * 8`. Scheduled alternative
monsters reduce a spawn point's success probability when they are inactive.
Directly placed monsters do not renew this way; `--include-static` models their
map-reset time and labels them as `map-reset` sources.

Coordinate-named `world_X_Y[_Z]` and `underground_city_X_Y[_Z]` maps are also
assembled into connected circuits of up to four cardinally adjacent rooms or
tiles by default. Only maps at the
same depth (`Z`), with the same header name and region, are combined. A hole,
ladder, or other authored transition does not make two depths horizontally
adjacent. Set `--circuit-size 1` to rank individual maps only.

Ranked locations use the human-readable long name from `maps/regions.reg`.
For coordinate-named world maps, the analyzer also finds named map regions
within five tiles and reports the route's direction and Manhattan tile distance
from up to three nearest landmarks. For example, an internal route made from
`world_0_50`, `world_0_51`, `world_1_50`, and `world_1_51` is described as one
tile south of Asteria, one tile north of Centennial, and three tiles northwest
of Fort Sether. Internal map paths remain in the detailed and JSON output for
developers and map makers.

## Estimated inputs

XP per kill, authored monster HP/base damage, treasure probabilities, and spawn
cadence are source-derived. XP/hour and money/hour additionally require a
player model. Defaults are deliberately visible in the output:

- effective DPS: always derived as
  `--damage-per-attack / --attack-delay` in the fixed-damage model;
- character level: the supplied skill level, overridden by `--character-level`;
- maximum health: omitted unless supplied with `--max-health`; when present it
  converts expected route damage into health-bar usage and absolute survival
  scoring;
- player AC: character level, which is the server's naked base, overridden by
  `--player-ac`;
- zero player protection, with individual protections supplied by repeatable
  `--player-protection TYPE=PERCENT` options;
- two seconds of targeting/movement/looting allowance per spawn location,
  charged on patrol even when that spawn is empty;
- ten seconds of traversal overhead per map;
- average physical protection when converting raw HP to effective kill HP;
- direct generated currency plus 20% of expected authored base item value.

Text output formats money using the authored coin ratios (`100c = 1s`,
`100s = 1g`). JSON fields remain numeric copper values so they can be sorted
and processed without parsing display strings.

## Topology, AoE, and encounter simulation

`--character-speed` accepts the value displayed by the client. The server adds
that speed every tick and movement spends one unit, so route time is authored
walkable tile steps divided by `speed * MAX_TICKS` (currently eight ticks per
second). The analyzer compiles map terrain, verifies coordinate-map seams,
finds pairwise spawn distances, builds a closed nearest-neighbour patrol, and
improves it with two-edge route exchanges.
Without this option it retains the generic overhead model.

`--aoe-radius N` derives average targets per attack from authored spawn points
within N tiles; without it, `--targets-per-attack` supplies the manual live
average. The analyzer erodes the walkable collision mesh by one tile so narrow
doors and corridors separate the remaining room cores. Spawns assigned to the
same core form an encounter pack. The weighted pack sizes cap the target count,
so a nominal seven-target spell does not assume seven mobs can be collected
from several separate rooms. It scores room-core size and penalizes blocking
objects embedded within usable space, while treating walls around a spacious
room as useful encounter boundaries rather than clutter. It uses that maneuverability score
to scale only the additional AoE targets beyond the first: open ground stays
close to the entered average, while narrow or cluttered terrain makes large
pulls less achievable. `--ignore-maneuverability` disables that adjustment but
still reports the rating; `--min-maneuverability 0..1` excludes cramped spots.
It then applies authored monster aggression to those additional targets.
Aggressive monsters acquire and follow the player automatically, while an
`unaggressive 1` monster must first be attacked. Passive monsters therefore
contribute 20% as much to a sustainable large pull by default. Override that
measured/subjective cost with `--passive-pull-efficiency 0..1`; setting it to
one disables the aggression penalty.
This proximity model is suitable when the exact cast orientation and
pull position are unknown. The server source confirms that firestorm and
icestorm propagate directional cone objects around walls, so the report does
not pretend that a radius is an exact cone footprint.
`--simulate-multiple-enemies` applies likely
aggro-pack overlap to incoming damage, including the extra exposure while
targets are killed sequentially. These are estimates: spell cone orientation,
moving monsters, dynamic blockers, unusual room connections, and player-controlled pulls remain unknown.

When maximum health is supplied, balanced-ranking safety is based on the
largest likely simultaneous encounter rather than multiplying danger by every
monster on the complete route. This rewards layouts such as Underground City,
where doors and corridors separate several dense room packs and provide safe
space between fights. Total expected damage for the full clear is still shown
separately; `--simulate-multiple-enemies` remains the more conservative combat
exposure model within each pack.

NPC combatants whose faction descends from the source-authored `npcs` faction
compete for nearby monster spawns. When authored detection ranges overlap, the
analyzer reports the number of contested spawns and an estimated player reward
share, then applies that share to XP, corpses/loot, and money. It does not
pretend the NPC's exact live position or damage contribution is known. Use
`--ignore-npc-contention` for a hypothetical uncontested version of the map.
This follows `is_friend_of()` in `server/src/types/monster.c` and the recursive
enemy/parent checks in `server/src/server/faction.c`. In
`server/src/server/attack.c`, only a player-owned fatal hit enters the XP award
path, while an NPC fatal hit forces an empty corpse; the estimated share is the
uncertain probability that the player, rather than a competing NPC, lands it.

Spawn patrols use each source-authored processing interval and `last_grace`
attempt gate rather than an exponential renewal curve. Randomized spawn phases
are averaged analytically, then readiness, partial-lap combat, mana use, and
rest time are solved together.

## Approach danger

A spot is only as safe as the maps crossed to reach it. The approach search
runs over walkable components rather than whole maps: each map's walkable
tiles are split into 8-neighbour connected components, computed lazily for
the maps the search reaches and cached. A character can move:

- through a placed `type 66` exit (not one carried in a spawn point or
  container) from its own tile, or from an adjacent walkable tile when the
  exit tile is blocked. It lands at the exit's `hp`/`sp`, at the target's
  `enter_x`/`enter_y` when those are out of range (such as `-1`), or on an
  adjacent free tile when the landing tile is blocked, as
  `object_enter_map()` does. `slaying` resolves relative to the map, or from
  the map root when it starts with `/`. Stairs without `slaying` use
  `last_heal` (9 up, 10 down, or a horizontal direction) to pick the tiled
  map and keep their own position; an exit without `slaying` but with
  `hp`/`sp` moves within its own map. An auto-linked exit (no path, `hp`/`sp`
  of -1, non-zero `sub_type`) may lead to any exit of the same `sub_type`
  within five tiles, including on tiled neighbours, as `exit_find()` does.
  Scripts, keys and locks are not followed; doors count as open;
- across a tiled map edge or corner from an edge tile to the walkable tile
  beyond it. Tiling follows `derive_map_filename_tiles()` in classic
  `server/src/server/map.c`: header `tile_path_N` (direction `N - 1`) wins,
  otherwise any basename with two or three numeric words of at most three
  characters (`cave_2_1_-1`) derives its neighbours' names when those maps
  exist. Only the eight same-depth directions are walked; up/down tiles are
  used only by stairs, not as seams.

Origins are components:

- each placed savebed's component (free);
- every walkable component of each `--approach-origin MAP` (free). `MAP` may
  be written `/region/map`, `region/map`, or `maps/region/map`; an unknown
  map is an error. `--approach-origins-only` uses only these, for example
  "I start from my savebed";
- town-connected surface components (charged). Surface components (depth-0
  `world_X_Y` tiles) are grouped once, with union-find over seams between
  surface tiles in either direction. A group is town-connected when one of its components holds a
  savebed or is joined by an exit to or from a savebed map, such as an inn
  door. Islets, ship-only islands, and surface pockets entered only from
  below are therefore not origins. A charged surface origin costs its map's
  own danger, because the character must cross it to use its entrance.

The `--path` filter and `--exclude-region` do not hide approach maps.

A bottleneck search walks backwards from the components holding the spot's
spawns to an origin, minimizing the most dangerous map crossed, then the
number of components crossed, then their names, so the result is
deterministic. It crosses at most `--max-approach-maps` components between
origin and spot (default 16). A component is expanded again when reached
with fewer crossings, so a long safe path cannot block a shorter one that
fits the limit. Other components of the spot's own maps are free and are not
listed, because the spot's safety already covers them.

Each crossed component is charged for its map's worst aggressive encounter
among the spawns standing in that component or whose own detection radius
reaches one of its tiles by Chebyshev distance, so casters, archers, flyers
and swimmers behind rock, tree or water lines still count, reusing the
spot's monster, damage, hit-chance, kill-time and protection model. Spawns
whose own detection radius reaches one pull point fight together. That pack
is charged by sequential exposure: every living monster keeps attacking until
it dies, killed in the order that minimizes damage (ascending kill time per
incoming DPS), plus each monster's secondary-risk bonus. A spawn that is
aggressive with probability `p` is charged `p` times its conditional damage
and adds `p` times its kill time to the monsters after it. For `n` identical
monsters this charges `n(n + 1)/2` kills' worth of exposure, about
`(n + 1)/2` times the farming model's `n` (danger times pack size). That is
deliberate: a farmer chooses pulls and fights one monster at a time, while a
traveller crossing the map meets the whole pack at once and every monster
still alive keeps hitting. Without `--max-health`, the worst single
aggressive spawn is charged instead, matching the relative per-monster
safety model. Directly placed monsters count even without
`--include-static`, because they are present when a traveller loads the
map. Passive monsters are skipped. AoE is not credited on the approach.
Threats are cached per map and component for the current options.

The approach safety uses the same reference as the spot: `max_health /
approach_danger` with `--max-health`, otherwise the least dangerous eligible
spot's danger divided by `approach_danger`, capped at one. The reported
`safety_score`, and therefore the balanced score and `--ranking safety`, is
the lower of the spot and approach safeties. A spot with no path from an
origin within the limit keeps its own safety and sets `approach_unknown`;
`--unreachable-approach-safety SAFETY` (0 to 1) caps such spots instead.
Running past monsters, fight variance, and the server's poisoning pulses
(`attack_perform_poison()`: five to ten pulses of up to a third of maximum
HP) beyond the secondary-risk heuristic are not modeled, so a pack whose
expected damage is just inside one health bar still reports full safety.
`--ignore-approach` restores the spot-only score.

Each result (`results`, `groups[].representative`, and `rankings`) adds these
JSON fields; existing fields keep their names and types:

- `spot_safety_score`: the spot-only safety previously reported as
  `safety_score`;
- `approach_status`: `path` (an origin was found), `origin` (a spawn's
  component is itself an origin), `unreachable`, or `disabled`. `path` can
  come with an empty `approach_maps` when a charged surface origin leads
  straight into the spot; `approach_danger` is then that origin's danger;
- `approach_unknown`: true exactly when `approach_status` is `unreachable`;
- `approach_origin`: content-relative origin map, empty unless `path`;
- `approach_maps`: content-relative maps crossed, ordered from the origin
  towards the spot, excluding the origin and the spot's own maps;
- `approach_danger`: the charged danger of the worst approach map, including
  a charged surface origin;
- `approach_safety_score`: 0 to 1; 1 without a charged approach, or the
  `--unreachable-approach-safety` cap;
- `approach_worst_map`: the map that sets `approach_danger`;
- `approach_danger_flags`: attack and behaviour flags of the monsters in each
  charged map's worst encounter, summed over those maps (for example
  `fire×3`), plus a `MAP L<level> > allowed L<limit>` entry for any charged
  map whose monsters exceed the `--max-level-gap` allowance.

## Encounter model and combat styles

The older safety estimate multiplies one monster's danger by the largest
*direct* aggro pack (`max_aggro_pack`). Authored spawns are usually more
than three tiles apart, so that pack is almost always one, and with
`--max-health` every map whose single monster fits in one health bar scores
safety 1.0. In the Burnt Forest the playtester died four times on maps that
all scored 1.0. Packs of three to eight formed there from wanderers, chases
and retreats past other spawns. The encounter model (`encounter.py`) replaces
that estimate with explicit, documented heuristics. Each cites the classic
server code it stands for (`classic/server/src`); the analyzer reads that code
and the authored content as data and copies none of it.

**What it reads per spawn.** Position; aggressive or passive
(`unaggressive`); detection radius `item_power`, plus 3 for a monster that
already has an enemy or was attacked (`types/monster.c` 1084-1100); chase
range `max(9, item_power)`, since an engaged monster keeps its target until
it is that far away for more than 12 checks (`types/monster.c` 558-580,
`include/global.h` 175-179); the per-action ally-call chance
`1 / monster_signal_chance[Int]`, read from `server/living.c` 154-162 (zero
means never). Allies answer when they share the caller's faction and stand
within `item_power * 1.5 - 1` tiles of it, or when they sit on a spawn point
with the same `title`, which always answers (`types/monster.c` 288-420).
Then: `random_move` wanderers and their `item_race` x `item_level` box
(unbounded when both are 0; `types/monster.c` 1160-1225); movement speed
(2x authored speed idle, 4x or 3x with `slow_move` while fighting;
`stand_still` never moves); casters (`can_cast_spell`), whose `ability`
objects name a spell index in `include/spellist.h` whose cast archetype's
`attack_*` gives the damage types; and archers (`can_use_bow`, reported as
`missile`). Spawns on the eight tiled neighbours are shifted into the map's
frame and included when they come within 12 tiles of it, so a pull near a
seam sees them.

**Terrain.** From walkable tiles (terrain flags minus `no_pass` blockers;
doors count as open):

- walkable regions (8-connected);
- open tiles, where all 8 neighbours are walkable;
- open fields, connected tiles with a clear 5x5 square;
- **kite room**: the share of tiles with at least 6 of 8 walkable
  neighbours; past a crossable seam the neighbouring map counts as open;
- one-tile-wide corridor tiles, and **doorways** (corridor runs of at most
  two tiles);
- dead ends;
- crossable seam tiles per cardinal direction.

**A pull.** For each target spawn the character picks a pull square: a
walkable tile within the target's detection radius (adjacent for a passive
target; within the kite distance for kiting styles). A wanderer can be met
anywhere it roams. Single-pull styles take the square with the fewest
expected joiners, pack styles the most. During the fight, which lasts the
target's kill time:

- a static aggressive spawn joins when its radius reaches the pull square
  plus the style's footprint, and hits from the first second;
- a wanderer joins with the share of its walkable wander area within that
  reach, widened by its random-walk spread `sqrt(idle tiles per second x
  fight seconds)`. The part already within reach at the start hits at once,
  the rest arrives half-way through the fight;
- an ally joins with the chance that the target's call succeeds at least
  once in the fight (`1 - (1 - chance)^(actions)`), half-way through;
- melee monsters in another walkable region never join; casters and archers
  can (line of sight is not modelled).

The **bad pull** (worst case) uses the engaged radius (+3) and the style's
worst footprint, and adds every wanderer and ally call that is more likely
than not to join. Those beyond the ordinary reach arrive half-way through.

**The clear.** Pulls are taken easiest first. After each pull its expected
joiners are removed from the map, so a wanderer that joined an early pull is
not counted again. The map's `expected_pack` and `encounter_need` come from
the hardest pull whose target is still alive with probability at least 0.5.
This models arriving on a fully populated map, which is how the playtester
died. Steady-state respawn order is not modelled.

**Cost of a pull** (`encounter_need`, HP). An expected-value timeline: each
arrived monster hits for its incoming DPS (the same server-derived melee
model as the rest of the analyzer, against the character's AC and
protections) until it dies. The character kills arrived monsters one at a
time, cheapest first (kill seconds per DPS), and heals
`--healing-per-second` throughout without banking healing. The need is the
deepest health deficit plus each monster's secondary-risk bonus (casting,
bows, drain, poison, ...).

**Combat styles** (`--combat-style`):

| Style | Footprint (bad pull) | Behaviour |
| --- | --- | --- |
| `melee` | 1 (3) | single pulls, fight in place |
| `melee-pack` | 2 (4) | pulls the cluster deliberately and fights it |
| `ranged-kite` | 1 (kite distance) | opens from range, single target, steps away |
| `aoe-kite` | kite distance (+3) | gathers packs; each attack hits `--targets-per-attack` (or the `--aoe-radius` estimate) |

Kiting styles keep a melee monster that is slower than the character away
except when cramped ground corners them, so its uptime is `1 - kite room`.
Stepping away costs attack time: the kill takes `1 + monster speed / player
speed` times longer. A monster at least as fast as the character, and every
caster or archer, hits at full rate in every style. A slow melee pack is
therefore cheap for a kiter and expensive for a melee healer. Player speed is
`--character-speed` (default 1.0) divided by the tick, about 8 tiles per
second at speed 1.0. `--kite-distance` defaults to 4.

**Safety.** With `--max-health`:

- expected-pull safety is `1 - need / HP` (the share of the health bar left
  at the trough);
- bad-pull safety is `1 / (1 + bad-pull need / HP)`, which stays ordered
  where the bad pull costs several health bars;
- `encounter_safety` is `0.75 x expected + 0.25 x bad pull`.

Without `--max-health`, both parts are relative to the cheapest pull of the
scan. Circuits take their hardest member.

**Backward compatibility.** Without `--combat-style`, `safety_score` and
every other existing field are unchanged. The encounter fields are reported
for the `melee` style with `encounter_applied: false`. With `--combat-style`,
`spot_safety_score` is the lower of the old estimate and `encounter_safety`,
and the approach cap applies as before. `--ignore-encounters` skips the
model. JSON output now carries `"schema_version": 2`; version 1 had no
version field. New result fields (in `results`, `groups[].representative`
and `rankings`):

- `encounter_style`, `encounter_applied`;
- `expected_pack`: attackers in the hardest expected pull;
  `mean_expected_pack`: across the clear; `worst_pack`: the bad pull;
- `encounter_need`, `encounter_worst_need` (HP);
- `encounter_safety`, `encounter_expected_safety`, `encounter_worst_safety`;
- `encounter_pull`: `[map, x, y]` of the hardest pull square;
- `encounter_reasons`: short sentences behind the rating;
- `wanderer_spawns`, `caster_spawns`, `ranged_spawns`, `linking_spawns`;
- `spawn_density` (spawns per 100 walkable tiles), `doorways`,
  `seam_spawns` (aggressive neighbour spawns whose engaged reach crosses
  the edge).

Example for the playtester (level 37 melee with minor healing):

```sh
python3 -m tools.farming_analyzer 37 --melee-damage 82 --weapon-class 44 \
  --weapon-speed 3.0 --character-level 37 --max-health 333 --player-ac 58 \
  --player-protection impact=38 --player-protection cleave=39 \
  --character-speed 0.8 --combat-style melee --healing-per-second 5.5
```

Not modelled: line of sight, doors opening and closing, scripted AI, pace,
circle and waypoint movement (`move_type`), monsters fleeing, steady-state
respawn order, ranged-attack cadence (a shooter's DPS uses its melee
cadence), and player decisions mid-fight.

## Difficulty report

`python3 -m tools.farming_analyzer report` rates authored maps for map makers
and map editors such as Tilewright. It has no player arguments. It rates
each map for a **reference character** per level band and each style:

- HP `9 x level`, AC `1.6 x level`, DPS `0.7 x level`, healing `0.15 x level`
  HP/s;
- 35% physical protection, speed 1.0, four AoE targets.

The defaults are calibrated on the playtester at level 37 (333 HP, AC 58,
about 25 melee DPS, 5.5 HP/s healing). Override them with `--hp-per-level`,
`--ac-per-level`, `--dps-per-level`, `--healing-per-level`,
`--physical-protection` and `--speed`.

```sh
python3 -m tools.farming_analyzer report --path 'world_1[5-8]_7[2-6]$'
python3 -m tools.farming_analyzer report --levels 20,30,40 \
  --styles melee,ranged-kite --exclude-region 'Strakewood Island' --json
```

`--levels auto` (the default) rates each map at its average monster level
rounded to 5, and 5 levels either side. `--time`, `--include-static` and
`--kite-distance` behave as in the ranking. Text output lists zones, then
maps with their ratings and top hotspots.

The JSON schema (`schema` `atrinik.farming_analyzer.difficulty_report`,
`schema_version` 1) is meant for editors to read. New fields may be added;
renamed or removed fields bump `schema_version`.

- `reference_character`, `styles` (name to description), `rating_scale`:
  `easy` ≥ 0.85, `fair` ≥ 0.65, `hard` ≥ 0.40, `deadly` > 0, `lethal` 0.
- `maps[]`, one per map with hostile spawns:
  - `path` (content-relative), `name`, `region`, `width`, `height`,
    `monster_levels` `{min, max, average}`, `levels` (bands rated);
  - `terrain`: `walkable_tiles`, `walkable_fraction`, `regions`,
    `largest_region`, `open_fraction`, `kite_room`, `open_field_tiles`,
    `open_field_center` `[x, y]` or null, `corridor_tiles`, `doorways`
    `[[x, y], ...]`, `dead_ends`, `seams` `{north|east|south|west: tiles}`;
  - `spawns[]`: `x`, `y`, `name`, `level`, `aggressive` (probability),
    `detection_radius`, `engaged_radius`, `chase_range`, `link_chance` (per AI
    action), `link_group`, `faction`, `engaged_speed`, `idle_speed` (tiles
    per second), `wander` (`{x0, y0, x1, y1, tiles}` or null), `caster`,
    `ranged`, `damage_types`, `melee_types`, `spells`, `pull`
    (`{x, y, expected, worst}`: the pull square in the modelled clear);
  - `hotspots[]`: `kind`, `x`, `y` (null for `seam_reach`), `spawns`,
    `monsters`, `reason`, plus kind-specific fields. Kinds:
    - `hardest_pull` (with `target`);
    - `dense_cluster`: aggressive spawns chained within engaged reach;
    - `wanderer_overlap` or `wanderers` (with `overlap` and `coverage`);
    - `caster` or `ranged` (with `damage_types`, `spells`, `passive`);
    - `guarded_chokepoint`: the three doorways most within engaged reach;
    - `seam_reach` (with `maps`);
  - `hotspot_basis` `{level, style}`: spawns and hotspots come from the band
    nearest the map's average monster level and the first style;
  - `ratings[]`, one per level and style: `level`, `style`, `safety`,
    `expected_safety`, `bad_pull_safety`, `rating`, `expected_attackers`,
    `mean_attackers`, `bad_pull_attackers`, `expected_need`,
    `bad_pull_need`, `health`, `hardest_pull` (`{x, y, target, monster}`),
    `out_of_band` (monsters more than 5 levels above the band), and `reasons`.
- `zones[]`: maps grouped by region and map name: `region`, `name`, `maps`,
  `monster_levels`, and `ratings[]` per level and style with `maps`,
  `min_safety`, `mean_safety`, `max_safety`, `rating` (of the minimum) and
  `hardest_map`.

Coordinates are map tiles in the map's own frame. Neighbour-map spawns are
not listed in `spawns`; they appear as a `seam_reach` hotspot.

## Encounter model: next increments

This first increment delivers the per-map encounter model, style-aware
safety and the report. Planned next steps, in order of value:

1. **Line of sight and doors**: use authored view blockers so walled
   rooms stop casters and detection, as `perception_object_visible()` does.
2. **Retreat paths**: walk the route from the pull square to the nearest
   exit or seam and charge the spawns within engaged reach of it, rather
   than a disc footprint. This is what turned the 2026-11-25 retreats into
   packs.
3. **Ranged cadence**: model spell `last_grace`/`magic` delays, the
   one-in-`Dex` cast roll, and bow fire chance instead of melee cadence for
   shooters, and use spell damage from `spellist.h` base and level damage.
4. **Steady state**: a second clear after respawn timing, for farming
   rather than arrival.
5. **Patrols**: `move_type` circle, pace and waypoint movement as wander
   areas.
6. **Zone routes**: rate a circuit along its traversal path, including the
   seam crossings between member maps.
7. **Tilewright**: an overlay of the JSON report (hotspots, pull squares,
   wander boxes, doorways) and per-edit re-rating.

## Profiles, rankings, diagnostics, and training

Save validated character arguments and reuse them:

```sh
python3 -m tools.farming_analyzer 10 ... --save-profile wizard.json
python3 -m tools.farming_analyzer 10 --profile wizard.json
```

Command-line arguments override profile defaults. Profiles intentionally omit
the skill level and output-only controls. Use `--ranking xp`, `money`, `loot`,
`safety`, or `balanced`; `--ranking all` prints the balanced table plus leaders
for every specialized view, including `maneuverability`. `--explain-rejected` reports map rejection reasons
in text and JSON.

Text output groups candidates by exact authored region and ten-level average
monster tier by default. A group keeps the best representative route and shows
the combined monster-level range, number of similar map/circuit candidates,
and their XP/hour and score ranges. This prevents overlapping permutations of
one Underground City floor or one outdoor zone from consuming the entire top
list. Child regions such as the deeper Underground City floors remain distinct,
and a broad region with materially different monster tiers gets multiple rows.
Change the tier width with `--group-level-span N`, or use `--show-all-routes`
to restore the exhaustive route-level table. JSON retains raw `results` and
adds compact `groups` summaries when grouping is enabled.

`--simulate-hours HOURS` advances absolute skill XP through the source-derived
level table and reruns the scan whenever the skill levels. Supply current
absolute XP with `--skill-xp`; otherwise the simulation starts at the beginning
of the supplied level.

Mana and AoE have no guessed defaults. `--targets-per-attack` defaults to one.
Enabling mana simulation requires the attack's mana cost and rate, mana
regenerated per real second, and the character's maximum mana.
`--mana-crystal` adds the crystal's full stored amount to the burst pool.

## Outgoing combat models

The fixed-damage model requires `--damage-per-attack` and `--attack-delay` and
divides damage by the delay in seconds to derive effective damage per second.
Damage should be the amount after accuracy but before the target's protection;
`--attack-type` selects the monster protection used to turn raw HP into
effective HP. This keeps damage per cast or swing distinct from DPS at the
command line.

Supplying all of `--melee-damage`, `--weapon-class`, and `--weapon-speed`
enables server-formula melee simulation instead. These are the final DAM, WC,
and weapon-speed values shown in the character's player doll; weapon speed is
in displayed seconds per swing. In this mode the analyzer does the following
for every monster level and spawn alternative:

1. Average the player's inclusive `rndm(DAM * 0.8 + 1, DAM)` roll.
2. Split damage using repeatable `--melee-attack TYPE=PERCENT` values and apply
   that monster's protection for each attack type.
3. Scale the monster's authored AC by its level as `living_update_monster()`
   does, then compute the player's WC hit probability using the server's
   default 20-point WC roll and guaranteed hit on the maximum roll. Override
   the roll size with `--weapon-class-range` only for a nonstandard character.
4. Convert displayed weapon speed to swings per second and multiply damage per
   hit by hit probability and swing rate.
5. Divide monster HP by that derived outgoing DPS to obtain per-monster kill
   time. Clear time, incoming damage exposure, XP/hour, loot/hour, money/hour,
   and the final score all use those individual kill times.

If `--melee-attack` is omitted, a concrete `--attack-type` becomes a 100%
attack of that type. The default `physical_average` becomes an even 25% split
across impact, cleave, slash, and pierce. Explicit attack percentages may sum
above 100 because the server attack array permits that. Fixed damage inputs and
melee simulation stats are mutually exclusive.

## AoE and mana cycles

`--targets-per-attack N` is a combat-source-independent average: it works with
fixed spell DPS today and with simulated melee attacks as AoE melee is added.
The derived DPS remains damage per second **per target**. The analyzer divides
single-target combat time by the terrain- and aggression-adjusted target average and charges one
movement/targeting/looting overhead per resulting group. This assumes the
remaining average is sustainable at that location; spell shape, positioning,
overkill, and moving targets remain approximate even though static map geometry
is included.

Mana simulation uses:

- `--mana-cost`: mana consumed by one attack or cast;
- `--attack-delay`: seconds between attacks/casts while dealing the entered damage;
- `--mana-regen`: mana regenerated per second during combat, traversal,
  looting, and rest;
- `--max-mana`: the character's full native mana pool;
- `--mana-crystal`: additional mana available from a full crystal;
- `--meditation`: during explicit rest, ramp regeneration from 1x base by 0.1x
  per out-of-combat second to the server's 10x cap after 90 seconds.
- `--meditation-delay`: keep regeneration at 1x for this many seconds after
  the last cast before the Meditation clock can advance. Use this to represent
  delayed projectiles, incoming attacks, lingering damage, or a measured live
  combat-state delay.

Fixed-damage attacks are quantized: each monster needs
`ceil(effective HP / damage per attack)` paid casts or swings. Mana spent is
that whole-cast count times mana cost, rather than fractional combat time times
an attack rate. Regeneration advances on source-derived server ticks using the
same integer remainder mechanism as the server.

Native mana and crystal charge are separate pools. When native mana cannot pay
the next cast, applying the crystal transfers only the missing native mana.
During explicit rest, the analyzer waits for native mana to become full and
then applies the crystal, transferring at most half the native pool per
application, exactly as `server/src/types/power_crystal.c` does. Applications
are assumed to be instant and optimally timed. Regeneration that reaches a full
native pool outside explicit rest is capped rather than flowing automatically
into the crystal.

With `--meditation`, every cast resets the out-of-combat timer. The multiplier
is `1 + seconds / 10`, capped at 10x. `--meditation-delay` holds it at 1x before
that ramp begins, modeling further combat events which the map alone cannot
predict. Without Meditation, regeneration remains at the supplied base rate.

The detail output also reports estimated burst kills: how many mobs can be
fought before the combined character and crystal pool is exhausted, after
combat-time regeneration. A small crystal can therefore require rests within
a clear while a larger one permits the same long-run mana deficit to be paid
after a larger batch. Stored mana does not create mana in a perpetual farm, so
capacity changes burst length. Each burst ends by restoring both pools to the
starting state, so the resulting patrol rate is sustainable. AoE improves both
time and mana efficiency because one paid attack damages the configured number
of targets.

The overall score normalizes eligible locations against the current scan and
weights XP/hour 45%, money/hour 20%, loot packages/hour 10%, and safety 25%.
Without `--max-health`, safety is relative to the least dangerous eligible
location. With health supplied, a route whose aggregate expected danger fits
within one full health bar receives full safety credit; routes exceeding that
budget lose safety credit in proportion to the overrun. The detail output also
shows expected melee HP consumed per clear and average kills per full health
bar. Healing, health regeneration, and consumable use are not assumed.
Incoming melee threat follows the server in these stages:

1. Scale authored `dam` for monster level exactly as
   `living_update_monster()` does.
2. Average the inclusive `rndm(dam * 0.8 + 1, dam)` damage roll and apply the
   server's bonus when monster level exceeds character level.
3. Split the roll by the monster's `attack_*` percentages, apply the supplied
   player protection for each type, and reproduce the server's one-damage
   minimum for a non-zero attack component.
4. Compute hit probability from scaled monster WC, `wc_range`, player AC, and
   the server's guaranteed hit on the maximum roll. Situational attack-roll
   adjustments are treated as zero.
5. In combat, use four times authored `speed` (three times for `slow_move`) as
   the AI-action rate. Weapon readiness advances by `weapon_speed` every server
   tick. Sustained swings per second are therefore
   `min(combat speed, weapon_speed) / tick length`.

The table exposes expected damage per successful hit, hit chance, sustained
swings/second, incoming DPS, and expected damage during one kill. Damage per
kill is incoming DPS multiplied by effective monster HP divided by the supplied
player DPS. This is the primary safety value, so high-damage fast attackers and
monsters that survive longer are ranked as less safe.

The final `danger` value adds the existing secondary-risk heuristic to damage
per kill: 20 for spellcasting, 12 for bows, half the drain percentage, 18% of
poison, 8% of acid, 5% of magic, and 3% of fire/cold; passive pull control
subtracts four. These additions cover effects and ranged/spell behavior that
cannot be reduced to the melee scheduler. The uncombined damage components
remain visible so the composite can be judged against a particular build.

Monster alignment and aggression are distinct. `is_neutral 1` means neutral
alignment and does not prevent a monster from attacking. Only
`unaggressive 1` marks a target as passive for pull and aggro modeling;
friendly, invulnerable, or `no_attack` objects are excluded as
non-combatants.

The analyzer reports two deliberately different density measures. **Likely
simultaneous aggro** uses each monster's source-authored `item_power` detection
radius at every spawn/pull point and is what `--max-aggro-pack` filters.
**Eight-tile proximity cluster** only describes how many spawn points are in a
viewport-connected pocket. It is useful route-density context, but does not
mean all of those monsters acquire the player together. Walls/line of sight,
monster movement, and the server's probabilistic ally signal can make a live
pull smaller or larger than the direct-radius estimate.

For the selected attack type, effective kill HP is
`raw HP / (1 - protection / 100)`, with protection capped at 95%. The default
uses the mean impact, cleave, slash, and pierce protection. Estimated clear time
is effective HP divided by per-target DPS and targets per attack, plus grouped
spawn-check overhead, per-map overhead, and any required mana rest. That value
is the full-population clear, useful for the first visit to a newly populated
route.

Sustainable hourly rates use a steady-state patrol calculation instead of
assuming every spawn is ready on every lap. The analyzer applies the authored
spawn cadence and its `last_grace` processing gate at each whole attempt boundary,
then averages a randomized fractional phase between boundaries. Expected ready
monsters determine the next lap's combat,
mana consumption, crystal-limited rests, and Meditation ramps; that new
duration changes readiness again. Per-map and grouped spawn-inspection overhead
remain charged for the full route because empty spawn locations must still be
reached and checked. The analyzer iterates until lap duration and expected
population agree. XP, loot packages, and money per hour use the resulting
expected kills per lap divided by sustainable lap time.

This is a discrete event expectation rather than an exponential renewal curve.
It captures the server gate and the delay between a monster respawning and the
patrol revisiting it, while averaging rather than guessing the unknown live
phase of each spawn point's ticks. The output exposes expected mobs ready per
lap, lap duration, and availability so the estimate can be audited.

The default incoming-damage estimate assumes one monster in sustained melee
range. `--simulate-multiple-enemies` adds concurrent exposure from the likely
aggro pack and removes one attack group at a time, so configured AoE reduces
that overlap. Blocking, situational hit-roll modifiers,
spell/ranged cadence, and explicit or randomized monster equipment are not
simulated. Player slaying bonuses, assassination, blocking, facing/backstab
modifiers, and on-hit status effects are also excluded from outgoing melee.
The model cannot infer real travel time, keys or quest access, shop
restrictions, competition, or the realized value of unidentified, magical,
cursed, or artifact drops. Treat hourly values as comparable planning
estimates, not guaranteed live measurements. A scan holds the supplied skill
level constant; if a route grants more than one level, rerun the analyzer at
the new level because the XP colors and cap will change during real play.

## Release asset

Each tools release attaches `atrinik-tools-farming-analyzer-<version>.tar.gz`
and its `SHA256SUMS`, so a consumer such as the autonomous playtester can pin
the analyzer by digest. The archive holds only `LICENSE` and `farming_analyzer/`
under one `atrinik-tools-farming-analyzer-<version>/` directory. It is built by
`scripts/release/package-farming-analyzer.sh` from the release tag with
`git archive` and `gzip -n`, so the same tag always yields the same bytes. The
analyzer stays standard-library only. Consumers supply `--content-root` and
`--server-root` from their own pinned content and Classic server sources.

## Validation

`test_encounter.py` covers the encounter model on synthetic spawns and
maps: pull cost, terrain structure, packs, wanderers, ally calls, walls,
styles and hotspots. It also checks the scan's backward compatibility, the
CLI and the report schema. With the content checkout present,
`BurntForestTest` checks the playtester's live level 37 melee-healer kit:
world_16_74 forms packs (bad pull at least 2) and rates below 1.0; the sparse
southern maps (world_15_75, world_15_76, world_16_75, world_16_76) rate
safer; world_17_72 rates hardest; kiting the slow treants rates safer than
melee; and the Forgotten Graveyard's night skeleton mages are flagged as
fire casters.

Run the focused regression suite from the repository root:

```sh
python3 -m unittest discover -s farming_analyzer/tests -t . -v
```

The fixtures are current authored maps and server tables. Tests cover the
level-18 XP cap and representative kills, server-derived incoming crocodile
damage and attack speed, player DAM/WC/weapon-speed simulation against a
crocodile, treasure branch expectations, spawn-point timing, scheduled
monsters, AoE clear-time and mana/crystal fight-rest cycles, Meditation's
server-derived refill ramp, damage/delay DPS derivation, partially populated
steady-state patrol laps, the deepest Old Outpost map, hierarchical region
exclusions, depth-safe world-map circuits, the four-tile Strakewood swamp
circuit, and the two-tile Forgotten Graveyard circuit. A synthetic world checks
that a safe circuit behind a dangerous entry map loses safety and reports
approach flags, while the same circuit behind a safe entry is unchanged, and
covers exits, tile paths, tiling, origins, and the bounded search. When the
content checkout is present, `UndergroundCityEntranceTest` checks a
Sera-like level 36 profile against the Underground City entrance's slime
cluster and approach routes. It is skipped without that checkout, so CI,
which checks out only this repository, does not run it.
