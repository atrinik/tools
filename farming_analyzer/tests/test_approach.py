"""Approach-path danger on a synthetic authored world."""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from dataclasses import MISSING, fields, replace
from pathlib import Path
from unittest.mock import patch

from farming_analyzer.analyzer import ApproachThreat
from farming_analyzer import (
    SERVER_ROOT,
    AnalysisOptions,
    FarmingAnalyzer,
    ROOT,
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
Object caster
name dragon caster
type 80
monster 1
level 40
maxhp 30
dam 20
wc 30
ac 10
speed 0.5
weapon_speed 1
item_power 3
can_cast_spell 1
exp 2000
end
"""

SIZE = 6
ROOM = "underground_city"
DANGER = "circuit[underground_city_0_0 + underground_city_1_0]"
SAFE = "circuit[underground_city_5_0 + underground_city_6_0]"
LOST = "underground_city_9_9"


def _map(name: str, region: str, *, spawns: tuple[tuple[str, int, int], ...] = (),
         exits: tuple[tuple, ...] = (), extra: str = "",
         header: tuple[str, ...] = (), wall_x: int | None = None,
         wall_y: int | None = None) -> str:
    """Write a fully floored map; ``wall_x``/``wall_y`` leave a column/row bare.

    Exits are (target, x, y) or (target, x, y, hp, sp); without hp/sp the
    test exit archetype lands on the target's (0, 0).
    """
    lines = [
        "arch map", f"name {name}", f"width {SIZE}", f"height {SIZE}",
        "difficulty 10", f"region {region}", *header, "end",
    ]
    for y in range(SIZE):
        for x in range(SIZE):
            if x != wall_x and y != wall_y:
                lines += ["arch floor", f"x {x}", f"y {y}", "end"]
    for monster, x, y in spawns:
        lines += ["arch spawn_point", f"x {x}", f"y {y}",
                  f"arch {monster}", "type 83", "end", "end"]
    for target, x, y, *arrival in exits:
        lines += ["arch exit", f"x {x}", f"y {y}", f"slaying {target}"]
        if arrival:
            lines += [f"hp {arrival[0]}", f"sp {arrival[1]}"]
        lines += ["end"]
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
        # The surface tile has an inn door, so it is a town origin; it leads
        # into both dungeons.
        (maps / "world_0_0").write_text(_map(
            "Surface", "surface",
            exits=(("danger/entry", 1, 1), ("/safe/entry", 4, 4), ("inn", 0, 5))))
        (maps / "inn").write_text(_map(
            "Inn", "surface", exits=(("world_0_0", 0, 0),),
            extra="arch bed_save\nx 2\ny 2\nend\n"))
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
        # Rats behind no authored exit at all.
        (maps / "lost").mkdir()
        (maps / "lost" / LOST).write_text(_map("lost cave", "dungeon", spawns=rats))
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
        self.assertTrue(danger.approach_unknown)
        self.assertEqual((), danger.approach_danger_flags)
        self.assertEqual(danger.spot_safety_score, danger.safety_score)

    def test_disconnected_spot_is_flagged_and_optionally_capped(self):
        lost = self.results(self.options())[f"maps/lost/{LOST}"]
        self.assertEqual("unreachable", lost.approach_status)
        self.assertTrue(lost.approach_unknown)
        self.assertEqual(lost.spot_safety_score, lost.safety_score)
        capped = self.results(self.options(
            unreachable_approach_safety=0.3))[f"maps/lost/{LOST}"]
        self.assertEqual(0.3, capped.approach_safety_score)
        self.assertEqual(min(0.3, capped.spot_safety_score), capped.safety_score)
        reachable = self.results(self.options(
            unreachable_approach_safety=0.3))[SAFE]
        self.assertEqual(reachable.spot_safety_score, reachable.safety_score)

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
        origin = run("--approach-origin", "/maps/danger/underground_city_0_0")[DANGER]
        self.assertEqual("origin", origin["approach_status"])
        with self.assertRaises(SystemExit) as raised:
            run("--approach-origin", "danger/nowhere")
        self.assertIn("danger/nowhere", str(raised.exception))
        with self.assertRaises(SystemExit):
            run("--approach-origins-only")
        lost = run("--unreachable-approach-safety", "0.25")[f"maps/lost/{LOST}"]
        self.assertEqual(0.25, lost["approach_safety_score"])
        ignored = run("--ignore-approach")[DANGER]
        self.assertEqual("disabled", ignored["approach_status"])
        self.assertEqual(ignored["spot_safety_score"], ignored["safety_score"])


class ApproachGraphTest(unittest.TestCase):
    """Authored connectivity, origin handling and the bounded search."""

    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        root = Path(cls.directory.name)
        (root / "arch").mkdir()
        (root / "arch" / "test.arc").write_text(ARCHETYPES)
        maps = root / "maps"
        (maps / "g").mkdir(parents=True)
        (maps / "t" / "sub").mkdir(parents=True)
        (maps / "regions.reg").write_text("region r\nlongname R\nend\n")

        def write(path: str, **kwargs) -> None:
            (maps / path).write_text(_map(path, "r", **kwargs))

        # Reviewer repro: O->N->M->x2->x1->S at danger 0 and M->Y(50)->S.
        for source, targets in {
                "O": ("N",), "N": ("M",), "M": ("x2", "Y"), "x2": ("x1",),
                "x1": ("S",), "Y": ("S",), "S": ()}.items():
            write(f"g/{source}", exits=tuple((target, 0, 0) for target in targets))
        # Town: the bedroom's door joins the surface tile world_0_0, which is
        # therefore a charged origin; the savebed itself is free.
        write("world_0_0", exits=(
            ("t/via_world", 0, 0), ("t/only_world", 0, 1), ("t/bedroom", 0, 2),
            ("t/hall", 0, 3), ("t/vault", 0, 4, 1, 1), ("t/split", 0, 5, -1, -1),
            ("t/cave_7_0", 1, 0, 1, 1), ("t/paired", 1, 2, 1, 1)))
        write("t/bedroom", exits=(("via_world", 0, 0), ("../world_0_0", 1, 1)),
              extra="arch bed_save\nx 2\ny 2\nend\n")
        write("t/via_world")
        write("t/only_world")
        # An islet: a surface tile with no seam to a town. Its exit leads to
        # t/under, which is otherwise only reachable through the hall.
        write("world_5_5", exits=(("t/under", 2, 2),))
        write("t/under", exits=(("../world_5_5", 1, 1),))
        write("t/hall", exits=(("under", 1, 1),))
        # A walled-off surface pocket on a town tile: only its west half is
        # joined to the inn, the east half is entered from below.
        write("world_3_0", wall_x=3, exits=(("t/inn2", 1, 1), ("t/pocket", 5, 5)))
        write("t/inn2", exits=(("../world_3_0", 0, 0, 1, 1),),
              extra="arch bed_save\nx 2\ny 2\nend\n")
        write("t/pocket", exits=(("../world_3_0", 0, 0, 5, 5),))
        # A dungeon dead end: the vault's east half holds the only exit to
        # the secret room, but arrivals land in its west half.
        write("t/vault", wall_x=3, exits=(("secret", 5, 5),))
        write("t/secret", exits=(("vault", 0, 0, 5, 5),))
        # Arrival by enter_x/enter_y when the exit's hp/sp is -1.
        write("t/split", wall_x=3, header=("enter_x 5", "enter_y 5"),
              exits=(("east_spot", 5, 4), ("west_spot", 1, 1)))
        write("t/east_spot")
        write("t/west_spot")
        # Auto-linked exits: no path, hp/sp -1 and a shared sub_type. The pair
        # on t/paired joins its two halves; another pairs across a tile seam.
        def paired(x: int, y: int, sub_type: int) -> str:
            return (f"arch exit\nx {x}\ny {y}\nsub_type {sub_type}\n"
                    "hp -1\nsp -1\nend\n")

        write("t/paired", wall_x=3, exits=(("beyond", 5, 5),),
              extra=paired(1, 1, 7) + paired(5, 1, 7) + paired(1, 4, 8))
        write("t/beyond")
        write("t/pair_0_0", extra=paired(5, 2, 3))
        write("t/pair_1_0", extra=paired(1, 2, 3) + paired(2, 2, 4))
        # Walk-blocking lines at x=1 and x=10 split t/wide into three parts.
        # A caster at (3, 2) with detection radius 3 reaches across the first
        # line but not the far part.
        wide = ["arch map", "name wide", "width 16", f"height {SIZE}",
                "difficulty 10", "region r", "end"]
        for y in range(SIZE):
            for x in range(16):
                if x not in (1, 10):
                    wide += ["arch floor", f"x {x}", f"y {y}", "end"]
        wide += ["arch spawn_point", "x 3", "y 2", "arch caster", "type 83",
                 "end", "end"]
        (maps / "t" / "wide").write_text("\n".join(wide) + "\n")
        # Seams join only the components that touch across the edge.
        write("t/cave_7_0", wall_y=3)
        write("t/cave_8_0", wall_y=3)
        # A bed_save carried in a container does not make a savebed map.
        write("t/storeroom", extra="arch wall\nx 1\ny 1\n"
              "arch bed_save\nend\nend\n")
        # Path resolution, tile paths, nested exits and missing targets.
        write("t/sub/deep", exits=(("../up", 0, 0), ("/t/abs_target", 1, 1),
                                   ("nowhere", 2, 2)),
              header=("tile_path_2 ../tiled_east",))
        write("t/up")
        write("t/abs_target")
        write("t/tiled_east")
        write("t/nest", spawns=(("rat", 1, 1),),
              extra="arch spawn_point\nx 3\ny 3\n"
              "arch exit\nslaying hidden\nend\nend\n"
              "arch wall\nx 4\ny 4\narch exit\nslaying hidden\nend\nend\n")
        write("t/hidden")
        # Server-style tiling for any prefix: diagonals link, depths do not.
        write("t/cave_1_1")
        write("t/cave_2_2")
        write("t/cave_2_1_-1")
        write("t/cave_1_1_-1")
        cls.analyzer = FarmingAnalyzer(root, SERVER_ROOT)
        cls.template = ApproachDangerTest.options(path_pattern=None)

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def predecessors(self, key: str) -> tuple[str, ...]:
        """Maps with a move into any walkable part of ``key``."""
        labels = set(self.analyzer._components(key).values())
        return tuple(sorted({
            source for label in labels
            for source, _label in self.analyzer._predecessors((key, label))
            if source != key}))

    def approach(self, spot: str, threats: dict[str, float], **changes) -> MapResult:
        options = replace(self.template, **changes)
        required = {
            item.name: 0 for item in fields(MapResult)
            if item.default is MISSING and item.default_factory is MISSING}
        required.update(path=spot, name=spot, region="r")
        result = MapResult(**required, map_paths=(f"maps{spot}",))

        def threat(key, _options, _component=None):
            danger = threats.get(key, 0.0)
            return ApproachThreat(danger, danger, 1, ("fire×1",) if danger else ())

        with patch.object(self.analyzer, "_approach_threat", side_effect=threat):
            self.analyzer._apply_approach(result, options)
        return result

    def test_hop_limited_search_keeps_a_shorter_more_dangerous_path(self):
        result = self.approach(
            "/g/S", {"/g/Y": 50.0}, max_approach_maps=3,
            approach_origins=("/g/O",), approach_origins_only=True)
        self.assertEqual("path", result.approach_status)
        self.assertEqual(("maps/g/N", "maps/g/M", "maps/g/Y"), result.approach_maps)
        self.assertEqual(50.0, result.approach_danger)
        self.assertEqual("maps/g/Y", result.approach_worst_map)
        unlimited = self.approach(
            "/g/S", {"/g/Y": 50.0}, approach_origins=("maps/g/O",),
            approach_origins_only=True)
        self.assertEqual(0.0, unlimited.approach_danger)
        self.assertEqual(("maps/g/N", "maps/g/M", "maps/g/x2", "maps/g/x1"),
                         unlimited.approach_maps)

    def test_surface_entrances_are_charged_and_savebeds_are_free(self):
        threats = {"/world_0_0": 70.0, "/t/bedroom": 90.0}
        only_world = self.approach("/t/only_world", threats)
        self.assertEqual("path", only_world.approach_status)
        self.assertEqual((), only_world.approach_maps)
        self.assertEqual("maps/world_0_0", only_world.approach_origin)
        self.assertEqual(70.0, only_world.approach_danger)
        self.assertEqual("maps/world_0_0", only_world.approach_worst_map)
        self.assertEqual(("fire×1",), only_world.approach_danger_flags)
        via_bed = self.approach("/t/via_world", threats)
        self.assertEqual("maps/t/bedroom", via_bed.approach_origin)
        self.assertEqual(0.0, via_bed.approach_danger)
        explicit = self.approach(
            "/t/only_world", threats, approach_origins=("/world_0_0",),
            approach_origins_only=True)
        self.assertEqual(0.0, explicit.approach_danger)
        unreachable = self.approach(
            "/t/via_world", threats, approach_origins=("/g/O",),
            approach_origins_only=True)
        self.assertEqual("unreachable", unreachable.approach_status)
        self.assertTrue(unreachable.approach_unknown)

    def test_islet_surface_exit_does_not_count(self):
        self.assertFalse(self.analyzer._surface_origin(("/world_5_5", 0)))
        self.assertTrue(self.analyzer._surface_origin(("/world_0_0", 0)))
        under = self.approach("/t/under", {"/t/hall": 80.0})
        self.assertEqual("maps/world_0_0", under.approach_origin)
        self.assertEqual(("maps/t/hall",), under.approach_maps)
        self.assertEqual(80.0, under.approach_danger)

    def test_surface_pocket_entered_only_from_below_does_not_count(self):
        labels = self.analyzer._components("/world_3_0")
        west, east = labels[(1, 1)], labels[(5, 5)]
        self.assertNotEqual(west, east)
        self.assertTrue(self.analyzer._surface_origin(("/world_3_0", west)))
        self.assertFalse(self.analyzer._surface_origin(("/world_3_0", east)))
        pocket = self.approach("/t/pocket", {})
        self.assertEqual("unreachable", pocket.approach_status)

    def test_dungeon_dead_end_reachable_only_from_inside(self):
        secret = self.approach("/t/secret", {})
        self.assertEqual("unreachable", secret.approach_status)
        vault = self.analyzer._components("/t/vault")
        self.assertIn(("/t/secret", 0), self.analyzer._predecessors(
            ("/t/vault", vault[(5, 5)])))
        self.assertEqual((), tuple(
            node for node in self.analyzer._predecessors(("/t/vault", vault[(5, 5)]))
            if node[0] != "/t/secret"))

    def test_exit_arrival_uses_enter_x_and_enter_y(self):
        east = self.approach("/t/east_spot", {"/t/split": 5.0})
        self.assertEqual("path", east.approach_status)
        self.assertEqual(("maps/t/split",), east.approach_maps)
        self.assertEqual("unreachable", self.approach("/t/west_spot", {}).approach_status)

    def test_seams_join_only_touching_components(self):
        west, east = (self.analyzer._components(f"/t/cave_{x}_0") for x in (7, 8))
        north = (west[(1, 1)], "/t/cave_8_0", east[(1, 1)], True)
        south = (west[(1, 5)], "/t/cave_8_0", east[(1, 5)], True)
        edges = self.analyzer._out_edges("/t/cave_7_0")
        self.assertIn(north, edges)
        self.assertIn(south, edges)
        self.assertNotIn((west[(1, 1)], "/t/cave_8_0", east[(1, 5)], True), edges)
        self.assertEqual("path", self.approach("/t/cave_8_0", {}).approach_status)
        south_spot = replace(self.template)
        required = {
            item.name: 0 for item in fields(MapResult)
            if item.default is MISSING and item.default_factory is MISSING}
        required.update(path="s", name="s", region="r")
        result = MapResult(**required, map_paths=("maps/t/cave_8_0",),
                           spawn_points=(("maps/t/cave_8_0", 1, 5),))
        self.analyzer._apply_approach(result, south_spot)
        self.assertEqual("unreachable", result.approach_status)

    def test_paired_exits_link_same_sub_type_within_five_tiles(self):
        labels = self.analyzer._components("/t/paired")
        west, east = labels[(1, 1)], labels[(5, 1)]
        edges = self.analyzer._out_edges("/t/paired")
        self.assertIn((west, "/t/paired", east, False), edges)
        self.assertIn((east, "/t/paired", west, False), edges)
        self.assertEqual("path", self.approach("/t/beyond", {}).approach_status)
        self.assertEqual(
            (("/t/pair_1_0", 1, 2),),
            self.analyzer._paired_exits(
                "/t/pair_0_0", self.analyzer._world().nodes["/t/pair_0_0"].exits[0]))

    def test_threat_charges_spawns_whose_radius_reaches_the_component(self):
        labels = self.analyzer._components("/t/wide")
        west, middle, east = labels[(0, 0)], labels[(4, 4)], labels[(12, 0)]
        self.assertEqual(3, len({west, middle, east}))
        threat = self.analyzer._approach_threat
        behind_line = threat("/t/wide", self.template, west)
        own = threat("/t/wide", self.template, middle)
        far = threat("/t/wide", self.template, east)
        self.assertGreater(behind_line.pack_danger, 0.0)
        self.assertEqual(own.pack_danger, behind_line.pack_danger)
        self.assertIn("caster×1", behind_line.flags)
        self.assertEqual(0.0, far.pack_danger)
        self.assertEqual(own.pack_danger,
                         threat("/t/wide", self.template).pack_danger)

    def test_savebed_detection_ignores_carried_beds(self):
        self.assertEqual(
            {"/t/bedroom", "/t/inn2"},
            {key for key, _label in self.analyzer._savebed_nodes()})
        self.assertEqual(frozenset({"/world_0_0", "/world_3_0", "/world_5_5"}),
                         self.analyzer._map_index()[1])

    def test_exit_and_tile_path_resolution(self):
        self.assertEqual(("/t/sub/deep",), self.predecessors("/t/up"))
        self.assertEqual(("/t/sub/deep",), self.predecessors("/t/abs_target"))
        self.assertEqual(("/t/sub/deep",), self.predecessors("/t/tiled_east"))
        self.assertNotIn("/t/sub/nowhere", self.analyzer._map_index()[0])
        self.assertEqual("/t/up", FarmingAnalyzer._resolve_map_path(
            "/t/sub/deep", "../up"))
        self.assertEqual("/t/abs_target", FarmingAnalyzer._resolve_map_path(
            "/t/sub/deep", "/t/abs_target"))
        self.assertIsNone(FarmingAnalyzer._resolve_map_path("/t/sub/deep", "  "))

    def test_exits_carried_in_spawn_points_or_containers_are_ignored(self):
        self.assertEqual((), self.predecessors("/t/hidden"))
        self.assertEqual("unreachable", self.approach("/t/hidden", {}).approach_status)

    def test_server_tiling_links_diagonals_but_not_depths(self):
        self.assertEqual(("/t/cave_2_2",), self.predecessors("/t/cave_1_1"))
        self.assertEqual(("/t/cave_1_1",), self.predecessors("/t/cave_2_2"))
        self.assertEqual(("/t/cave_1_1_-1",), self.predecessors("/t/cave_2_1_-1"))
        self.assertEqual(("/t/cave_2_1_-1",), self.predecessors("/t/cave_1_1_-1"))
        self.assertEqual(("cave", 2, 1, -1),
                         FarmingAnalyzer._tile_coordinates("cave_2_1_-1"))
        self.assertIsNone(FarmingAnalyzer._tile_coordinates("ruins_0101"))
        self.assertIsNone(FarmingAnalyzer._tile_coordinates("cave_1"))

    def test_sequential_exposure_counts_partial_aggression_once(self):
        # Two certain monsters: the second is charged while the first dies.
        self.assertEqual(30.0, FarmingAnalyzer._sequential_exposure(
            [(1.0, 1.0, 10.0, 0.0), (1.0, 1.0, 10.0, 0.0)]))
        # A monster that is aggressive half the time costs half as much.
        self.assertEqual(5.0, FarmingAnalyzer._sequential_exposure(
            [(0.5, 1.0, 10.0, 0.0)]))

    def test_resolve_map_key_accepts_content_and_map_root_paths(self):
        for spelling in ("/t/up", "t/up", "maps/t/up", "/maps/t/up"):
            self.assertEqual("/t/up", self.analyzer.resolve_map_key(spelling))
        self.assertIsNone(self.analyzer.resolve_map_key("/t/missing"))


UNDERGROUND_CITY = (ROOT / "maps" / "shattered_islands" / "strakewood_island" /
                    "underground_city")


@unittest.skipUnless((UNDERGROUND_CITY / "underground_city_0_0").is_file(),
                     "requires the sibling content checkout")
class UndergroundCityEntranceTest(unittest.TestCase):
    """Regression for the 2026-11-14 deaths on the Underground City entrance."""

    @classmethod
    def setUpClass(cls):
        cls.analyzer = FarmingAnalyzer()

    @staticmethod
    def sera(max_health: float, **changes) -> AnalysisOptions:
        """Level 36 slash melee, no fire, acid or poison protection."""
        options = replace(
            ApproachDangerTest.options(path_pattern=None),
            player_level=36, character_level=36, player_ac=59, dps=0.0,
            damage_per_attack=0.0, attack_delay=0.0, melee_damage=65,
            weapon_class=46, weapon_speed=1.0, player_attacks=(("slash", 100),),
            player_protections=(("cleave", 46), ("cold", 9), ("impact", 42),
                                ("pierce", 41), ("slash", 57)),
            max_health=max_health)
        return replace(options, **changes)

    def test_entrance_slime_cluster_is_one_sequential_encounter(self):
        threat = self.analyzer._approach_threat(
            "/shattered_islands/strakewood_island/underground_city/"
            "underground_city_0_0", self.sera(322.0))
        # Three brown cave puddings and an ochre cave jelly at (17-23, 1-3)
        # all reach one pull point; killed in turn they deal ~288 damage.
        self.assertEqual(("fire×3", "acid×1", "poison×1"), threat.flags)
        self.assertGreater(threat.pack_danger, 244.0)
        self.assertLess(threat.pack_danger, 322.0)

    def test_spot_behind_the_entrance_loses_safety_at_measured_health(self):
        results = self.analyzer.scan(self.sera(
            244.0, circuit_size=1, path_pattern=r"underground_city_4_2$"))
        spot = next(result for result in results
                    if result.map_paths[0].endswith("underground_city_4_2"))
        self.assertIn(
            "maps/shattered_islands/strakewood_island/underground_city/"
            "underground_city_0_0", spot.approach_maps)
        self.assertEqual(1.0, spot.spot_safety_score)
        self.assertLess(spot.safety_score, 0.9)
        labels = {flag.split("×")[0] for flag in spot.approach_danger_flags}
        self.assertLessEqual({"fire", "acid", "poison"}, labels)

    def test_circuits_no_longer_use_the_inside_only_lake_exit(self):
        results = self.analyzer.scan(self.sera(
            244.0, path_pattern=r"underground_city_[0-4]_[0-4]$"))
        city = [result for result in results
                if "underground_city" in result.path and result.approach_status == "path"]
        self.assertTrue(city)
        # world_2_69's exit_green stands on a two-tile pocket reached only
        # from inside the city, so it is not an origin.
        self.assertFalse(any(result.approach_origin.endswith("/world_2_69")
                             for result in city))
        prefix = ("maps/shattered_islands/strakewood_island/underground_city/"
                  "underground_city_")
        for members in (("2_2", "2_3", "3_1", "3_2"), ("0_4", "1_2", "1_3", "1_4")):
            circuit = next(
                result for result in results
                if sorted(result.map_paths) == [prefix + member for member in members])
            self.assertTrue(
                prefix + "0_0" in circuit.approach_maps or
                prefix + "5_2_-1" in circuit.approach_maps, circuit.approach_maps)
            self.assertLess(circuit.safety_score, 0.9)
            labels = {flag.split("×")[0] for flag in circuit.approach_danger_flags}
            self.assertLessEqual({"fire", "acid", "poison"}, labels)


if __name__ == "__main__":
    unittest.main()
