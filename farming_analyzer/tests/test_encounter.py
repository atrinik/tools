"""Encounter model: pulls, packs, combat styles, terrain and the difficulty report."""

from __future__ import annotations

import io
import json
import math
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from farming_analyzer import encounter as enc
from farming_analyzer import (
    SERVER_ROOT,
    AnalysisOptions,
    FarmingAnalyzer,
    ROOT,
    MapResult,
    main,
)


def spawn(x: int, y: int, **changes) -> enc.EncounterSpawn:
    values = dict(name="brute", level=10, aggressive=1.0, radius=3, dps=10.0,
                  kill_seconds=20.0, engaged_speed=1.5, idle_speed=0.8)
    values.update(changes)
    return enc.EncounterSpawn(x, y, **values)


def field(width: int = 24, height: int = 24) -> set[tuple[int, int]]:
    return {(x, y) for x in range(width) for y in range(height)}


def model(spawns, walkable=None, style="melee", healing=0.0, aoe=1.0, width=24, height=24):
    walkable = field(width, height) if walkable is None else walkable
    terrain = enc.analyze_terrain(width, height, walkable)
    options = enc.EncounterOptions(enc.style_profiles()[style], healing, 8.0, aoe)
    return enc.estimate(list(spawns), walkable, terrain, options), options


class PullNeedTest(unittest.TestCase):
    def test_single_monster_costs_its_damage_above_healing(self):
        self.assertAlmostEqual(200.0, enc.pull_need([enc.Fighter(1.0, 10.0, 20.0)]))
        self.assertAlmostEqual(100.0, enc.pull_need([enc.Fighter(1.0, 10.0, 20.0)], 5.0))
        self.assertEqual(0.0, enc.pull_need([enc.Fighter(1.0, 4.0, 20.0)], 5.0))

    def test_pack_is_killed_in_the_cheapest_order(self):
        # Kill the 1 s/2 DPS monster first: 3 DPS for 1 s, then 1 DPS for 10 s.
        fighters = [enc.Fighter(1.0, 1.0, 10.0), enc.Fighter(1.0, 2.0, 1.0)]
        self.assertAlmostEqual(13.0, enc.pull_need(fighters))

    def test_late_arrivals_cost_less_and_aoe_divides_kill_time(self):
        together = enc.pull_need([enc.Fighter(1.0, 10.0, 20.0), enc.Fighter(1.0, 10.0, 20.0)])
        late = enc.pull_need([enc.Fighter(1.0, 10.0, 20.0),
                              enc.Fighter(1.0, 10.0, 20.0, arrival=10.0)])
        self.assertAlmostEqual(600.0, together)
        self.assertLess(late, together)
        self.assertAlmostEqual(300.0, enc.pull_need(
            [enc.Fighter(1.0, 10.0, 20.0), enc.Fighter(1.0, 10.0, 20.0)], targets=2.0))

    def test_unkillable_damaging_monster_is_infinite(self):
        self.assertTrue(math.isinf(enc.pull_need([enc.Fighter(1.0, 1.0, math.inf)])))
        self.assertEqual(0.0, enc.safety_from_need(math.inf, 100.0))

    def test_safety_scales_are_documented_shapes(self):
        self.assertEqual(1.0, enc.safety_from_need(0.0, 300.0))
        self.assertAlmostEqual(0.5, enc.safety_from_need(150.0, 300.0))
        self.assertEqual(0.0, enc.safety_from_need(450.0, 300.0))
        self.assertAlmostEqual(0.5, enc.bad_pull_safety(300.0, 300.0))
        self.assertAlmostEqual(0.25, enc.bad_pull_safety(900.0, 300.0))
        self.assertAlmostEqual(0.875, enc.blended_safety(1.0, 0.5))
        self.assertEqual("easy", enc.rating(0.9))
        self.assertEqual("deadly", enc.rating(0.1))


class TerrainTest(unittest.TestCase):
    def test_two_rooms_joined_by_a_doorway(self):
        # Two 5x5 rooms, x 0-4 and 6-10, joined through (5, 2).
        walkable = {(x, y) for x in range(5) for y in range(5)}
        walkable |= {(x, y) for x in range(6, 11) for y in range(5)}
        walkable.add((5, 2))
        terrain = enc.analyze_terrain(11, 5, walkable, {1: {(10, y) for y in range(5)}})
        self.assertEqual(1, terrain.regions)
        self.assertEqual(((5, 2),), terrain.doorways)
        self.assertEqual(1, terrain.corridor_tiles)
        self.assertEqual({"east": 5}, terrain.seams)
        self.assertGreater(terrain.kite_room, terrain.open_fraction)

    def test_open_field_and_dead_ends(self):
        walkable = field(12, 12) | {(12, 5), (13, 5)}
        terrain = enc.analyze_terrain(14, 12, walkable)
        self.assertEqual(1, terrain.dead_ends)
        self.assertEqual(64, terrain.open_field_tiles)
        self.assertIsNotNone(terrain.open_field_center)


class EncounterEstimateTest(unittest.TestCase):
    def test_sparse_spawns_are_single_pulls(self):
        built, _options = model([spawn(2, 2), spawn(12, 12), spawn(21, 21)])
        self.assertEqual(1.0, built.expected_pack)
        self.assertEqual(1.0, built.worst_pack)
        self.assertAlmostEqual(200.0, built.need)

    def test_spawns_two_apart_can_still_be_pulled_one_at_a_time(self):
        # With radius 3, a member of a two-tile grid is pulled from outside.
        built, _options = model([spawn(x, y) for x in (4, 6, 8) for y in (4, 6)])
        self.assertEqual(1.0, built.expected_pack)
        self.assertGreater(built.worst_pack, 2.0)

    def test_dense_spawns_form_packs_that_cost_more(self):
        dense = [spawn(x, y) for x in (4, 5, 6) for y in (4, 5)]
        built, _options = model(dense)
        sparse, _options = model([spawn(2, 2), spawn(12, 12), spawn(21, 21)])
        self.assertGreaterEqual(built.expected_pack, 2.0)
        self.assertGreater(built.worst_pack, built.expected_pack)
        self.assertGreater(built.need, sparse.need)
        safety = enc.blended_safety(enc.safety_from_need(built.need, 600.0),
                                    enc.bad_pull_safety(built.worst_need, 600.0))
        sparse_safety = enc.blended_safety(enc.safety_from_need(sparse.need, 600.0),
                                           enc.bad_pull_safety(sparse.worst_need, 600.0))
        self.assertLess(safety, sparse_safety)
        self.assertLess(sparse_safety, 1.0)

    def test_pull_square_avoids_neighbours(self):
        # A neighbour four tiles east: pulling from the west keeps it out.
        built, _options = model([spawn(10, 10), spawn(14, 10)])
        pull = next(pull for pull in built.pulls if pull.target == 0)
        self.assertLess(pull.x, 10)
        self.assertEqual(1.0, pull.expected)
        # The bad pull (engaged radius + 3 footprint) still reaches it.
        self.assertEqual(2.0, pull.worst)

    def test_wanderers_join_and_are_used_up_by_the_clear(self):
        wander = dict(wander_tiles=frozenset(field()), wander_box=(0, 0, 23, 23))
        built, _options = model([spawn(4, 4, **wander), spawn(20, 20, **wander),
                                 spawn(12, 12, **wander)])
        static, _options = model([spawn(4, 4), spawn(20, 20), spawn(12, 12)])
        self.assertEqual(1.0, static.expected_pack)
        self.assertGreater(built.expected_pack, 1.2)
        # A wanderer that joins an early pull is not there for a later one.
        self.assertLess(sum(built.weights), 3.0)
        # A lone wanderer is met where nothing else can join.
        alone, _options = model([spawn(4, 4), spawn(12, 12, **wander)])
        self.assertEqual(1.0, alone.expected_pack)

    def test_links_by_title_and_faction(self):
        caller = dict(link_chance=1 / 6, faction="monsters")
        far = spawn(20, 20, faction="monsters")
        unlinked, _options = model([spawn(4, 4, **caller), far])
        self.assertEqual(1.0, unlinked.pulls[0].expected)
        grouped, _options = model([spawn(4, 4, link_group="pack", **caller),
                                   spawn(20, 20, link_group="pack", **caller)])
        self.assertGreater(grouped.expected_pack, 1.9)
        # The clear takes a silent group member first, which calls no one.
        one_caller, _options = model([spawn(4, 4, link_group="pack", **caller),
                                      spawn(20, 20, faction="monsters", link_group="pack")])
        self.assertEqual(1.0, one_caller.expected_pack)
        # Allies inside the caller's signal radius answer without a title.
        near, _options = model([spawn(4, 4, **caller), spawn(7, 4, **caller)])
        self.assertGreater(near.expected_pack, 1.9)
        silent, _options = model([spawn(4, 4, link_group="pack", faction="monsters"),
                                  spawn(20, 20, link_group="pack")])
        self.assertEqual(1.0, silent.expected_pack)

    def test_walls_stop_melee_but_not_casters(self):
        # A wall column at x = 12 splits the map into two regions.
        walkable = {tile for tile in field() if tile[0] != 12}
        melee, _options = model([spawn(10, 10), spawn(14, 10)], walkable)
        caster, _options = model([spawn(10, 10), spawn(14, 10, caster=True,
                                                          damage_types=("fire",))], walkable)
        self.assertEqual(1.0, melee.worst_pack)
        self.assertEqual(2.0, caster.worst_pack)

    def test_kiting_avoids_slow_melee_but_not_fast_monsters_or_casters(self):
        slow = [spawn(x, y) for x in (4, 5, 6) for y in (4, 5)]
        melee, _options = model(slow)
        kite, _options = model(slow, style="ranged-kite")
        self.assertLess(kite.need, melee.need * 0.5)
        fast = [spawn(x, y, engaged_speed=16.0) for x in (4, 5, 6) for y in (4, 5)]
        fast_kite, _options = model(fast, style="ranged-kite")
        self.assertGreater(fast_kite.need, kite.need * 2.0)
        casters = [spawn(x, y, caster=True) for x in (4, 5, 6) for y in (4, 5)]
        caster_kite, _options = model(casters, style="ranged-kite")
        self.assertGreater(caster_kite.need, kite.need * 2.0)

    def test_pack_styles_seek_the_cluster_and_aoe_shares_kills(self):
        cluster = [spawn(x, y) for x in (4, 6, 8) for y in (4, 6)] + [spawn(20, 20)]
        # Two-tile spacing: the single-pull style isolates every member.
        single, _options = model(cluster)
        pack, _options = model(cluster, style="melee-pack")
        self.assertGreater(pack.expected_pack, single.expected_pack)
        aoe, _options = model(cluster, style="aoe-kite", aoe=4.0)
        kite_one, _options = model(cluster, style="aoe-kite", aoe=1.0)
        self.assertLess(aoe.need, kite_one.need)

    def test_healing_offsets_sustained_damage(self):
        built, _options = model([spawn(2, 2), spawn(12, 12)], healing=10.0)
        self.assertEqual(0.0, built.need)

    def test_hotspots_and_reasons_explain_the_map(self):
        dense = [spawn(x, y) for x in (4, 6, 8) for y in (4, 6)]
        dense.append(spawn(18, 18, caster=True, damage_types=("fire",), spells=("firestorm",)))
        dense.append(spawn(20, 4, wander_tiles=frozenset(field()), wander_box=(0, 0, 23, 23)))
        dense.append(spawn(27, 10, own_map=False, map_path="maps/next"))
        built, options = model(dense)
        kinds = {hotspot["kind"] for hotspot in enc.hotspots(built)}
        self.assertLessEqual({"hardest_pull", "dense_cluster", "caster", "wanderers"}, kinds)
        self.assertIn("seam_reach", kinds)
        lines = enc.reasons(built, options, 300.0)
        self.assertTrue(lines[0].startswith("8 spawns (8 aggressive)"))
        self.assertTrue(any("caster/ranged" in line and "fire" in line for line in lines))
        self.assertTrue(any("wanderer" in line for line in lines))


ARCHETYPES = """\
Object floor
terrain_type 1
end
Object wall
no_pass 1
end
Object spawn_point
type 81
last_grace 1
speed -0.01
end
Object brute
name brute
type 80
monster 1
level 10
maxhp 60
dam 40
wc 10
ac 1
speed 0.05
weapon_speed 1
item_power 3
attack_impact 100
faction monsters
exp 200
end
Object deer
name deer
type 80
monster 1
level 10
maxhp 60
dam 40
wc 10
ac 1
speed 0.05
weapon_speed 1
item_power 3
attack_impact 100
random_move 1
faction monsters
exp 200
end
Object mage
name mage
type 80
monster 1
level 10
maxhp 60
dam 20
wc 10
ac 1
speed 0.05
weapon_speed 1
item_power 4
can_cast_spell 1
faction monsters
exp 200
end
Object ability_firestorm
type 110
end
Object firebreath
attack_fire 100
end
"""

SIZE = 24


def _map(name: str, spawns: tuple[tuple[str, int, int], ...], children: str = "") -> str:
    lines = ["arch map", f"name {name}", f"width {SIZE}", f"height {SIZE}",
             "difficulty 10", "region forest", "end"]
    for y in range(SIZE):
        for x in range(SIZE):
            lines += ["arch floor", f"x {x}", f"y {y}", "end"]
    for monster, x, y in spawns:
        lines += ["arch spawn_point", f"x {x}", f"y {y}", f"arch {monster}", "type 83"]
        if monster == "mage":
            lines += ["arch ability_firestorm", "end"]
        lines += ["end", "end"]
    return "\n".join(lines) + "\n" + children


DENSE = "maps/forest/world_0_0"
SPARSE = "maps/forest/world_5_5"
CRYPT = "maps/forest/world_9_9"


class AnalyzerEncounterTest(unittest.TestCase):
    """The scan reports the encounter model and --combat-style applies it."""

    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        root = Path(cls.directory.name)
        (root / "arch").mkdir()
        (root / "arch" / "test.arc").write_text(ARCHETYPES)
        maps = root / "maps" / "forest"
        maps.mkdir(parents=True)
        (root / "maps" / "regions.reg").write_text("region forest\nlongname Forest\nend\n")
        dense = tuple(("brute", x, y) for x in (4, 5, 6) for y in (4, 5)) + (
            ("deer", 16, 16),)
        (maps / "world_0_0").write_text(_map("Thicket", dense))
        (maps / "world_5_5").write_text(_map(
            "Glade", (("brute", 2, 2), ("brute", 12, 12), ("brute", 21, 21))))
        (maps / "world_9_9").write_text(_map(
            "Crypt", (("mage", 4, 4), ("mage", 6, 4), ("brute", 20, 20))))
        cls.analyzer = FarmingAnalyzer(root, SERVER_ROOT)

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    @staticmethod
    def options(**changes) -> AnalysisOptions:
        options = AnalysisOptions(
            player_level=10, dps=6.0, seconds_per_kill=2.0, seconds_per_map=10.0,
            shop_sell_fraction=0.20, at_minute=12 * 60, attack_type="physical_average",
            minimum_spawns=1, minimum_xp_fraction=0.0, max_level_gap=5, circuit_size=1,
            path_pattern="forest", include_static=False, character_level=10,
            player_ac=10, player_protections=(), melee_damage=None, weapon_class=None,
            weapon_speed=None, weapon_class_range=20,
            player_attacks=(("impact", 25), ("cleave", 25), ("slash", 25), ("pierce", 25)),
            damage_per_attack=6.0, attack_delay=1.0, max_health=400.0,
            model_approach=False)
        return replace(options, **changes)

    def results(self, options: AnalysisOptions) -> dict[str, MapResult]:
        return {result.path: result for result in self.analyzer.scan(options)}

    def test_fields_are_reported_without_changing_safety(self):
        plain = self.results(self.options())
        ignored = self.results(self.options(model_encounters=False))
        for path in (DENSE, SPARSE):
            self.assertEqual(ignored[path].safety_score, plain[path].safety_score)
            self.assertEqual(ignored[path].max_aggro_pack, plain[path].max_aggro_pack)
            self.assertEqual("melee", plain[path].encounter_style)
            self.assertFalse(plain[path].encounter_applied)
            self.assertEqual("", ignored[path].encounter_style)
        self.assertGreaterEqual(plain[DENSE].expected_pack, 2.0)
        self.assertEqual(1.0, plain[SPARSE].expected_pack)
        self.assertEqual(1.0, plain[DENSE].wanderer_spawns)

    def test_combat_style_breaks_the_saturated_tie(self):
        old = self.results(self.options(max_health=4000.0))
        self.assertEqual(old[DENSE].safety_score, old[SPARSE].safety_score)
        styled = self.results(self.options(max_health=4000.0, combat_style="melee"))
        dense, sparse = styled[DENSE], styled[SPARSE]
        self.assertTrue(dense.encounter_applied)
        self.assertLess(dense.safety_score, sparse.safety_score)
        self.assertLess(dense.safety_score, 1.0)
        self.assertEqual(dense.safety_score, dense.spot_safety_score)
        self.assertEqual(min(1.0, dense.encounter_safety), dense.safety_score)

    def test_kiting_style_rates_the_slow_pack_safer(self):
        melee = self.results(self.options(combat_style="melee"))[DENSE]
        kite = self.results(self.options(combat_style="ranged-kite"))[DENSE]
        self.assertGreater(kite.encounter_safety, melee.encounter_safety)

    def test_caster_map_is_flagged_with_damage_types(self):
        crypt = self.results(self.options())[CRYPT]
        self.assertEqual(2.0, crypt.caster_spawns)
        self.assertTrue(any("caster/ranged" in line and "fire" in line
                            for line in crypt.encounter_reasons))
        spawns, _competitors = self.analyzer._spawns_cached(
            "/forest/world_9_9", self.options(), False)
        built = self.analyzer.map_encounter("/forest/world_9_9", spawns, self.options())
        casters = [hotspot for hotspot in enc.hotspots(built) if hotspot["kind"] == "caster"]
        self.assertEqual(2, len(casters))
        self.assertEqual(["fire"], casters[0]["damage_types"])
        self.assertEqual(["firestorm"], casters[0]["spells"])

    def test_relative_mode_without_health(self):
        results = self.results(self.options(max_health=0.0, combat_style="melee"))
        self.assertEqual(1.0, results[SPARSE].encounter_expected_safety)
        self.assertLess(results[DENSE].encounter_safety, results[SPARSE].encounter_safety)

    def test_cli_json_schema_version_and_validation(self):
        def run(*extra: str) -> dict:
            stdout = io.StringIO()
            with patch("sys.stdout", stdout):
                main(["10", "--damage-per-attack", "6", "--attack-delay", "1",
                      "--max-health", "400", "--min-spawns", "1",
                      "--min-xp-fraction", "0", "--path", "forest", "--circuit-size", "1",
                      "--show-all-routes", "--json", "--ignore-approach",
                      "--content-root", self.directory.name,
                      "--server-root", str(SERVER_ROOT), *extra])
            return json.loads(stdout.getvalue())

        payload = run("--combat-style", "melee", "--healing-per-second", "1")
        self.assertEqual(2, payload["schema_version"])
        self.assertEqual("melee", payload["assumptions"]["combat_style"])
        dense = next(item for item in payload["results"] if item["path"] == DENSE)
        for key in ("expected_pack", "worst_pack", "encounter_safety", "encounter_reasons",
                    "encounter_pull", "wanderer_spawns", "caster_spawns", "seam_spawns"):
            self.assertIn(key, dense)
        self.assertTrue(dense["encounter_applied"])
        with self.assertRaises(SystemExit):
            run("--healing-per-second", "-1")
        with self.assertRaises(SystemExit):
            run("--combat-style", "melee", "--ignore-encounters")
        with self.assertRaises(SystemExit):
            run("--kite-distance", "0")

    def test_difficulty_report_schema(self):
        stdout = io.StringIO()
        with patch("sys.stdout", stdout):
            main(["report", "--content-root", self.directory.name,
                  "--server-root", str(SERVER_ROOT), "--levels", "10",
                  "--styles", "melee,ranged-kite", "--json"])
        report = json.loads(stdout.getvalue())
        self.assertEqual("atrinik.farming_analyzer.difficulty_report", report["schema"])
        self.assertEqual(1, report["schema_version"])
        by_path = {record["path"]: record for record in report["maps"]}
        self.assertEqual({DENSE, SPARSE, CRYPT}, set(by_path))
        dense = by_path[DENSE]
        self.assertEqual({"melee", "ranged-kite"},
                         {rating["style"] for rating in dense["ratings"]})
        rating = dense["ratings"][0]
        for key in ("safety", "expected_safety", "bad_pull_safety", "rating",
                    "expected_attackers", "bad_pull_attackers", "hardest_pull", "reasons"):
            self.assertIn(key, rating)
        self.assertIn("dense_cluster", {hotspot["kind"] for hotspot in dense["hotspots"]})
        self.assertEqual(7, len(dense["spawns"]))
        deer = next(item for item in dense["spawns"] if item["name"] == "deer")
        self.assertEqual({"x0": 0, "y0": 0, "x1": 23, "y1": 23, "tiles": 576}, deer["wander"])
        self.assertEqual(9, deer["chase_range"])
        self.assertEqual(6, deer["engaged_radius"])
        self.assertIn("caster", {hotspot["kind"] for hotspot in by_path[CRYPT]["hotspots"]})
        melee = {rating["path"] if "path" in rating else path: rating
                 for path, record in by_path.items() for rating in record["ratings"]
                 if rating["style"] == "melee"}
        self.assertLess(melee[DENSE]["safety"], melee[SPARSE]["safety"])
        # Zones group maps by region and map name.
        zones = {zone["name"]: zone for zone in report["zones"]}
        self.assertEqual({"Thicket", "Glade", "Crypt"}, set(zones))
        thicket = zones["Thicket"]
        self.assertEqual([DENSE], thicket["maps"])
        self.assertEqual(melee[DENSE]["safety"], next(
            item["min_safety"] for item in thicket["ratings"] if item["style"] == "melee"))
        text = io.StringIO()
        with patch("sys.stdout", text):
            main(["report", "--content-root", self.directory.name,
                  "--server-root", str(SERVER_ROOT), "--levels", "10", "--styles", "melee"])
        self.assertIn("dense_cluster", text.getvalue())
        with self.assertRaises(SystemExit):
            main(["report", "--content-root", self.directory.name,
                  "--server-root", str(SERVER_ROOT), "--styles", "dance"])


SHATTERED = ROOT / "maps" / "shattered_islands"


@unittest.skipUnless((SHATTERED / "world_16_74").is_file(),
                     "requires the sibling content checkout")
class BurntForestTest(unittest.TestCase):
    """Regression for the 2026-11-25 Burnt Forest deaths of the playtester."""

    @classmethod
    def setUpClass(cls):
        cls.analyzer = FarmingAnalyzer()

    @staticmethod
    def sera(**changes) -> AnalysisOptions:
        """Level 37 melee healer: her live kit on 2026-11-25."""
        options = AnalysisOptions(
            player_level=37, dps=0.0, seconds_per_kill=2.0, seconds_per_map=10.0,
            shop_sell_fraction=0.20, at_minute=12 * 60, attack_type="physical_average",
            minimum_spawns=1, minimum_xp_fraction=0.0, max_level_gap=100, circuit_size=1,
            path_pattern=r"shattered_islands/world_1[5-7]_7[2-6]$", include_static=False,
            character_level=37, player_ac=58,
            player_protections=(("cleave", 39), ("cold", 9), ("impact", 38),
                                ("pierce", 36), ("slash", 50)),
            melee_damage=82, weapon_class=44, weapon_speed=3.0, weapon_class_range=20,
            player_attacks=(("slash", 100),), max_health=333.0, character_speed=0.8,
            model_approach=False, combat_style="melee", healing_per_second=5.5)
        return replace(options, **changes)

    def results(self, options: AnalysisOptions) -> dict[str, MapResult]:
        return {Path(result.path).name: result for result in self.analyzer.scan(options)}

    def test_dense_world_16_74_forms_packs_and_is_not_saturated(self):
        old = self.results(self.sera(combat_style=""))["world_16_74"]
        self.assertEqual(1.0, old.max_aggro_pack)
        self.assertEqual(1.0, old.safety_score)
        dense = self.results(self.sera())["world_16_74"]
        self.assertGreaterEqual(dense.worst_pack, 2.0)
        self.assertGreater(dense.expected_pack, 1.0)
        self.assertLess(dense.encounter_safety, 1.0)
        self.assertLess(dense.safety_score, 1.0)
        self.assertEqual(2.0, dense.wanderer_spawns)

    def test_sparse_southern_maps_rate_safer(self):
        results = self.results(self.sera())
        dense = results["world_16_74"].safety_score
        for name in ("world_15_75", "world_15_76", "world_16_75", "world_16_76"):
            self.assertGreater(results[name].safety_score, dense, name)
        # The L38-40 map where she died twice rates hardest of all.
        self.assertLess(results["world_17_72"].safety_score, dense)

    def test_kiting_the_slow_treants_is_safer_than_melee(self):
        melee = self.results(self.sera())["world_16_74"]
        kite = self.results(self.sera(combat_style="ranged-kite"))["world_16_74"]
        self.assertGreater(kite.encounter_safety, melee.encounter_safety)

    def test_graveyard_skeleton_mages_are_flagged_at_night(self):
        options = self.sera(player_level=20, character_level=20, at_minute=0,
                            path_pattern=r"shattered_islands/world_14_74$")
        crypt = self.results(options)["world_14_74"]
        self.assertGreaterEqual(crypt.caster_spawns, 3.0)
        self.assertTrue(any("caster/ranged" in line and "fire" in line
                            for line in crypt.encounter_reasons))


if __name__ == "__main__":
    unittest.main()
