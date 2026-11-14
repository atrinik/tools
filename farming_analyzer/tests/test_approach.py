"""Approach-path danger on a synthetic authored world."""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from farming_analyzer import (
    SERVER_ROOT,
    AnalysisOptions,
    FarmingAnalyzer,
    MapResult,
    main,
)

ARCHETYPES = """\
Object floor
terrain_type 1
end
Object wall
no_pass 1
end
Object exit
type 66
end
Object bed_save
type 106
end
Object spawn_point
type 81
last_grace 1
speed -0.01
end
Object rat
name rat
type 80
monster 1
level 10
maxhp 20
dam 2
wc 1
ac 1
speed 0.5
weapon_speed 1
item_power 2
exp 200
end
Object pudding
name cave pudding
type 80
monster 1
level 32
maxhp 8
dam 12
wc 30
ac 10
speed 0.5
weapon_speed 1
item_power 6
attack_fire 50
attack_acid 50
exp 2000
end
"""

SIZE = 6
ROOM = "underground_city"
DANGER = "circuit[underground_city_0_0 + underground_city_1_0]"
SAFE = "circuit[underground_city_5_0 + underground_city_6_0]"


def _map(name: str, region: str, *, spawns: tuple[tuple[str, int, int], ...] = (),
         exits: tuple[tuple[str, int, int], ...] = (), extra: str = "") -> str:
    lines = [
        "arch map", f"name {name}", f"width {SIZE}", f"height {SIZE}",
        "difficulty 10", f"region {region}", "end",
    ]
    for y in range(SIZE):
        for x in range(SIZE):
            lines += ["arch floor", f"x {x}", f"y {y}", "end"]
    for monster, x, y in spawns:
        lines += ["arch spawn_point", f"x {x}", f"y {y}",
                  f"arch {monster}", "type 83", "end", "end"]
    for target, x, y in exits:
        lines += ["arch exit", f"x {x}", f"y {y}", f"slaying {target}", "end"]
    return "\n".join(lines) + "\n" + extra


class ApproachDangerTest(unittest.TestCase):
    """A safe circuit is only as safe as the map crossed to reach it."""

    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        root = Path(cls.directory.name)
        (root / "arch").mkdir()
        (root / "arch" / "test.arc").write_text(ARCHETYPES)
        maps = root / "maps"
        (maps / "danger").mkdir(parents=True)
        (maps / "safe").mkdir()
        (maps / "regions.reg").write_text(
            "region surface\nlongname Surface\nend\n"
            "region dungeon\nlongname Dungeon\nend\n")
        # The surface world tile is an origin; it leads into both dungeons.
        (maps / "world_0_0").write_text(_map(
            "Surface", "surface",
            exits=(("danger/entry", 1, 1), ("/safe/entry", 4, 4))))
        rats = (("rat", 1, 1), ("rat", 4, 4))
        for dungeon, x, entry_spawns in (
                ("danger", 0, (("pudding", 2, 2), ("pudding", 3, 2),
                               ("pudding", 2, 3))),
                ("safe", 5, ())):
            first, second = f"{ROOM}_{x}_0", f"{ROOM}_{x + 1}_0"
            (maps / dungeon / "entry").write_text(_map(
                f"{dungeon} entry", "dungeon", spawns=entry_spawns,
                exits=(("../world_0_0", 0, 0), (first, 5, 5))))
            # Two seam-adjacent coordinate rooms form the farming circuit.
            # Only the first has an authored exit from the entry map.
            (maps / dungeon / first).write_text(_map(
                f"{dungeon} cave", "dungeon", spawns=rats,
                exits=(("entry", 0, 0),)))
            (maps / dungeon / second).write_text(_map(
                f"{dungeon} cave", "dungeon", spawns=rats))
        cls.analyzer = FarmingAnalyzer(root, SERVER_ROOT)

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    @staticmethod
    def options(**changes) -> AnalysisOptions:
        options = AnalysisOptions(
            player_level=10, dps=40.0, seconds_per_kill=2.0,
            seconds_per_map=10.0, shop_sell_fraction=0.20, at_minute=12 * 60,
            attack_type="physical_average", minimum_spawns=1,
            minimum_xp_fraction=0.0, max_level_gap=5, circuit_size=4,
            path_pattern=ROOM, include_static=False, character_level=10,
            player_ac=10, player_protections=(), melee_damage=None,
            weapon_class=None, weapon_speed=None, weapon_class_range=20,
            player_attacks=(("impact", 25), ("cleave", 25),
                            ("slash", 25), ("pierce", 25)),
            damage_per_attack=40.0, attack_delay=1.0, max_health=300.0,
        )
        return replace(options, **changes)

    def results(self, options: AnalysisOptions) -> dict[str, MapResult]:
        return {result.path: result for result in self.analyzer.scan(options)}

    def test_dangerous_approach_lowers_safety_and_is_reported(self):
        results = self.results(self.options())
        danger = results[DANGER]
        self.assertEqual("path", danger.approach_status)
        self.assertEqual("maps/world_0_0", danger.approach_origin)
        self.assertEqual(("maps/danger/entry",), danger.approach_maps)
        self.assertEqual("maps/danger/entry", danger.approach_worst_map)
        self.assertEqual(1.0, danger.spot_safety_score)
        self.assertGreater(danger.approach_danger, 300.0)
        self.assertAlmostEqual(300.0 / danger.approach_danger,
                               danger.approach_safety_score)
        self.assertEqual(danger.approach_safety_score, danger.safety_score)
        self.assertIn("fire×3", danger.approach_danger_flags)
        self.assertIn("acid×3", danger.approach_danger_flags)
        self.assertIn("entry L32 > allowed L15", danger.approach_danger_flags)

    def test_approach_threat_applies_character_protections(self):
        bare = self.results(self.options())[DANGER]
        protected = self.results(self.options(
            player_protections=(("acid", 50), ("fire", 50))))[DANGER]
        self.assertLess(protected.approach_danger, bare.approach_danger)
        self.assertGreater(protected.safety_score, bare.safety_score)

    def test_safe_approach_leaves_identical_circuit_unchanged(self):
        results = self.results(self.options())
        danger = results[DANGER]
        safe = results[SAFE]
        self.assertEqual(("maps/safe/entry",), safe.approach_maps)
        self.assertEqual(0.0, safe.approach_danger)
        self.assertEqual((), safe.approach_danger_flags)
        self.assertEqual(1.0, safe.approach_safety_score)
        self.assertEqual(safe.spot_safety_score, safe.safety_score)
        self.assertEqual(danger.spot_safety_score, safe.spot_safety_score)
        self.assertGreater(safe.safety_score, danger.safety_score)
        self.assertGreater(safe.score, danger.score)

    def test_coordinate_seams_extend_the_approach(self):
        results = self.results(self.options(circuit_size=1))
        far_room = next(result for result in results.values()
                        if result.map_paths == ("maps/danger/underground_city_1_0",))
        self.assertEqual(("maps/danger/entry", "maps/danger/underground_city_0_0"),
                         far_room.approach_maps)
        self.assertLess(far_room.safety_score, 1.0)

    def test_relative_safety_mode_also_charges_the_approach(self):
        results = self.results(self.options(max_health=0.0))
        danger = results[DANGER]
        self.assertLess(danger.safety_score, danger.spot_safety_score)

    def test_ignore_approach_and_explicit_origin(self):
        ignored = self.results(self.options(model_approach=False))
        danger = ignored[DANGER]
        self.assertEqual("disabled", danger.approach_status)
        self.assertEqual((), danger.approach_maps)
        self.assertEqual(danger.spot_safety_score, danger.safety_score)

        savebed = self.results(self.options(
            approach_origins=("maps/danger/underground_city_0_0",)))
        danger = savebed[DANGER]
        self.assertEqual("origin", danger.approach_status)
        self.assertEqual(danger.spot_safety_score, danger.safety_score)

    def test_unreachable_spot_keeps_its_own_safety(self):
        results = self.results(self.options(
            max_approach_maps=0))
        danger = results[DANGER]
        self.assertEqual("unreachable", danger.approach_status)
        self.assertEqual(danger.spot_safety_score, danger.safety_score)

    def test_cli_json_exposes_approach_fields_and_options(self):
        def run(*extra: str) -> dict:
            stdout = io.StringIO()
            with patch("sys.stdout", stdout):
                main([
                    "10", "--damage-per-attack", "40", "--attack-delay", "1",
                    "--max-health", "300", "--min-spawns", "1",
                    "--min-xp-fraction", "0", "--path", ROOM,
                    "--show-all-routes", "--json",
                    "--content-root", self.directory.name,
                    "--server-root", str(SERVER_ROOT), *extra,
                ])
            return {item["path"]: item for item in json.loads(
                stdout.getvalue())["results"]}

        danger = run()[DANGER]
        self.assertEqual(["maps/danger/entry"], danger["approach_maps"])
        self.assertEqual("maps/world_0_0", danger["approach_origin"])
        self.assertLess(danger["safety_score"], danger["spot_safety_score"])
        self.assertIn("fire×3", danger["approach_danger_flags"])
        origin = run("--approach-origin", "/danger/underground_city_0_0")[DANGER]
        self.assertEqual("origin", origin["approach_status"])
        ignored = run("--ignore-approach")[DANGER]
        self.assertEqual("disabled", ignored["approach_status"])
        self.assertEqual(ignored["spot_safety_score"], ignored["safety_score"])


if __name__ == "__main__":
    unittest.main()
