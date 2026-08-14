"""Focused regression tests for the source-derived farming analyzer."""

from __future__ import annotations

import io
import json
import math
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from farming_analyzer import (
    AnalysisOptions,
    FarmingAnalyzer,
    LocationIndex,
    ROOT,
    SERVER_ROOT,
    _fmt_money,
    flatten,
    group_farming_results,
    main,
    one,
    parse_blocks,
    simulate_training,
)


class FarmingAnalyzerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.analyzer = FarmingAnalyzer()

    @staticmethod
    def options(*, minute: int = 12 * 60, circuit_size: int = 1,
                path_pattern: str | None = None) -> AnalysisOptions:
        return AnalysisOptions(
            player_level=18,
            dps=54.0,
            seconds_per_kill=2.0,
            seconds_per_map=10.0,
            shop_sell_fraction=0.20,
            at_minute=minute,
            attack_type="physical_average",
            minimum_spawns=1,
            minimum_xp_fraction=0.0,
            max_level_gap=100,
            circuit_size=circuit_size,
            path_pattern=path_pattern,
            include_static=False,
            character_level=18,
            player_ac=18,
            player_protections=(),
            melee_damage=None,
            weapon_class=None,
            weapon_speed=None,
            weapon_class_range=20,
            player_attacks=(("impact", 25), ("cleave", 25),
                            ("slash", 25), ("pierce", 25)),
        )

    def test_default_sources_use_split_classic_workspace_checkouts(self):
        self.assertEqual("content-1x", ROOT.name)
        self.assertEqual(ROOT.parent / "classic" / "server" / "src", SERVER_ROOT)
        self.assertTrue((ROOT / "maps" / "regions.reg").is_file())
        self.assertTrue((SERVER_ROOT / "server" / "exp.c").is_file())

    def test_level_18_server_xp_formula_and_cap(self):
        xp = self.analyzer.experience
        self.assertEqual(22_500, xp.kill_cap(18))
        self.assertEqual(0, xp.kill_xp(18, 12, 105))
        self.assertEqual(16_800, xp.kill_xp(18, 16, 105))
        self.assertEqual(19_992, xp.kill_xp(18, 17, 105))
        self.assertEqual(18_468, xp.kill_xp(18, 17, 97))
        self.assertEqual(22_500, xp.kill_xp(18, 18, 102))

    def test_money_format_uses_gold_silver_and_copper(self):
        self.assertEqual("0c", _fmt_money(0))
        self.assertEqual("50c", _fmt_money(50))
        self.assertEqual("1s 50c", _fmt_money(150))
        self.assertEqual("1g", _fmt_money(10_000))
        self.assertEqual("1g 1s 50c", _fmt_money(10_150))
        self.assertEqual("12,345g 67s 89c", _fmt_money(123_456_789))

    def test_treasure_package_expectations_match_server_branches(self):
        treasure = self.analyzer.treasure
        self.assertAlmostEqual(1.3227, treasure.evaluate("mob_fire", 16).packages, places=3)
        self.assertAlmostEqual(1.3283, treasure.evaluate("mob_crocodile", 20).packages,
                               places=3)
        self.assertAlmostEqual(1.3190, treasure.evaluate("mob_frog", 20).packages,
                               places=3)

    def test_crocodile_threat_matches_server_damage_and_speed_formulas(self):
        node = {"arch": "crocodile", "attrs": {}, "children": []}
        attrs = self.analyzer.archetypes["crocodile"]["attrs"]
        profile = self.analyzer._monster_at_level(node, attrs, 20, self.options())

        self.assertEqual(39, profile.damage)
        self.assertAlmostEqual(37.4722, profile.expected_hit_damage, places=4)
        self.assertEqual(1.0, profile.hit_chance)
        self.assertAlmostEqual(0.304, profile.attacks_second, places=3)
        self.assertAlmostEqual(11.3916, profile.damage_second, places=4)
        self.assertAlmostEqual(46.621, profile.damage_taken, places=3)

        slow_attrs = dict(attrs)
        slow_attrs["speed"] = "-0.005"
        slow_profile = self.analyzer._monster_at_level(
            node, slow_attrs, 20, self.options())
        self.assertAlmostEqual(0.160, slow_profile.attacks_second, places=3)
        self.assertAlmostEqual(0.55, self.analyzer._attack_hit_chance(30, 20, 40))

    def test_player_melee_stats_drive_hit_chance_dps_and_exposure(self):
        node = {"arch": "crocodile", "attrs": {}, "children": []}
        attrs = self.analyzer.archetypes["crocodile"]["attrs"]
        options = replace(
            self.options(),
            melee_damage=50,
            weapon_class=25,
            weapon_speed=2.0,
            player_attacks=(("slash", 100),),
        )
        profile = self.analyzer._monster_at_level(node, attrs, 20, options)

        self.assertAlmostEqual(45.5, profile.player_hit_damage)
        self.assertAlmostEqual(0.70, profile.player_hit_chance)
        self.assertAlmostEqual(0.50, profile.player_attacks_second)
        self.assertAlmostEqual(15.925, profile.player_damage_second)
        self.assertAlmostEqual(13.8776, profile.kill_seconds, places=4)
        self.assertAlmostEqual(
            profile.damage_second * profile.kill_seconds,
            profile.damage_taken,
        )

        protected_attrs = dict(attrs)
        protected_attrs["protect_slash"] = "20"
        protected = self.analyzer._monster_at_level(
            node, protected_attrs, 20, options)
        self.assertAlmostEqual(36.4, protected.player_hit_damage)
        self.assertLess(protected.player_damage_second, profile.player_damage_second)

    def test_explicit_artifact_drop_uses_authored_probability_and_value(self):
        path = ROOT / "maps" / "shattered_islands" / "world_3_69"
        parsed = parse_blocks(path)
        thrakir = next(
            node for node, _parent in flatten(parsed["objects"])
            if one(node["attrs"], "name") == "Thrakir"
        )
        drop = self.analyzer._explicit_drops(thrakir)
        self.assertAlmostEqual(1 / 30, drop.packages)
        self.assertAlmostEqual(125_000 / 30, drop.base_item_value)

    def test_old_outpost_deep_matches_known_level_18_totals(self):
        path = (ROOT / "maps" / "shattered_islands" / "strakewood_island" /
                "old_outpost" / "old_outpost_0202")
        result = self.analyzer.analyze_map(path, self.options())
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(14, result.spawns)
        self.assertEqual(282_168, result.xp_clear)
        self.assertEqual(2_821, result.hp_clear)
        self.assertAlmostEqual(39.6, result.avg_damage, places=1)
        self.assertAlmostEqual(18.6, result.loot_clear, places=1)
        self.assertAlmostEqual(315.46, result.respawn_seconds, places=1)
        self.assertEqual(14, len(result.spawn_events))
        attempt_seconds, probability = result.spawn_events[0]
        self.assertAlmostEqual(0.125 / 0.00317, attempt_seconds, places=3)
        self.assertAlmostEqual(1.0 / 8.0, probability)

    def test_old_outpost_spell_uses_whole_casts_and_exact_mana(self):
        path = (ROOT / "maps" / "shattered_islands" / "strakewood_island" /
                "old_outpost" / "old_outpost_0101")
        options = replace(
            self.options(), player_level=12, character_level=26,
            damage_per_attack=26.0, attack_delay=1.2,
            mana_cost=9.0, mana_regen=1.7, max_mana=70.0,
            mana_crystal=100.0, meditation=True)
        result = self.analyzer.analyze_map(path, options)
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(132.0, result.attacks_clear)
        self.assertEqual(1_188.0, result.mana_spent_clear)
        self.assertAlmostEqual(7.2, result.avg_kill_seconds)
        self.assertGreaterEqual(result.burst_kills, 4.0)
        self.assertLess(result.burst_kills, 5.0)

    def test_aoe_and_mana_crystal_model_fight_rest_cycles(self):
        path = (ROOT / "maps" / "shattered_islands" / "strakewood_island" /
                "old_outpost" / "old_outpost_0202")
        cycle_options = replace(
            self.options(), seconds_per_kill=30.0,
            damage_per_attack=54.0, attack_delay=1.0)
        baseline = self.analyzer.analyze_map(path, cycle_options)
        aoe = self.analyzer.analyze_map(
            path, replace(cycle_options, targets_per_attack=4,
                          model_maneuverability=False))
        mana_options = replace(
            cycle_options,
            targets_per_attack=4,
            model_maneuverability=False,
            mana_cost=60.0,
            attack_delay=1.0,
            mana_regen=2.0,
            max_mana=70.0,
            mana_crystal=250.0,
        )
        mana = self.analyzer.analyze_map(path, mana_options)
        self.assertIsNotNone(baseline)
        self.assertIsNotNone(aoe)
        self.assertIsNotNone(mana)
        assert baseline is not None and aoe is not None and mana is not None

        single_target_combat = baseline.avg_kill_seconds * baseline.spawns
        expected_active = (
            single_target_combat / aoe.effective_targets_per_attack +
            math.ceil(baseline.spawns / aoe.effective_targets_per_attack) * 30.0 +
            10.0)
        self.assertAlmostEqual(expected_active, aoe.active_clear_seconds)
        self.assertAlmostEqual(expected_active, aoe.clear_seconds)
        self.assertGreater(aoe.xp_hour, baseline.xp_hour)
        self.assertEqual(baseline.xp_clear, aoe.xp_clear)

        expected_mana = mana.attacks_clear * 60.0
        self.assertAlmostEqual(expected_mana, mana.mana_spent_clear)
        self.assertGreater(mana.mana_rest_seconds, 0.0)
        self.assertAlmostEqual(
            mana.active_clear_seconds + mana.mana_rest_seconds,
            mana.clear_seconds)
        self.assertGreater(mana.burst_kills, 0.0)
        self.assertLess(mana.xp_hour, aoe.xp_hour)

        larger_crystal = self.analyzer.analyze_map(
            path, replace(mana_options, mana_crystal=1000.0))
        self.assertIsNotNone(larger_crystal)
        assert larger_crystal is not None
        self.assertGreater(larger_crystal.burst_kills, mana.burst_kills)
        self.assertAlmostEqual(larger_crystal.xp_hour, mana.xp_hour)

        derived_aoe = self.analyzer.analyze_map(
            path, replace(cycle_options, aoe_radius=8))
        multi_enemy = self.analyzer.analyze_map(
            path, replace(cycle_options, simulate_multiple_enemies=True))
        multi_enemy_aoe = self.analyzer.analyze_map(
            path, replace(cycle_options, targets_per_attack=4,
                          simulate_multiple_enemies=True))
        self.assertIsNotNone(derived_aoe)
        self.assertIsNotNone(multi_enemy)
        self.assertIsNotNone(multi_enemy_aoe)
        assert (derived_aoe is not None and multi_enemy is not None and
                multi_enemy_aoe is not None)
        self.assertGreater(derived_aoe.effective_targets_per_attack, 1.0)
        self.assertGreater(multi_enemy.damage_clear, baseline.damage_clear)
        self.assertLess(multi_enemy_aoe.damage_clear, multi_enemy.damage_clear)

    def test_discrete_crystal_cycle_and_combat_delay_match_server_behavior(self):
        options = replace(
            self.options(), damage_per_attack=26.0, attack_delay=1.2,
            mana_cost=9.0, mana_regen=1.7, max_mana=70.0,
            mana_crystal=100.0, meditation=True)
        active, rest, burst = self.analyzer._mana_cycle_timing(24.0, 0.0, options)
        delayed = self.analyzer._mana_cycle_timing(
            24.0, 0.0, replace(options, meditation_delay=30.0))
        self.assertAlmostEqual(28.8, active)
        self.assertEqual(36.25, rest)
        self.assertEqual(24.0, burst)
        self.assertGreater(delayed[1], 55.0)
        self.assertLessEqual(delayed[2], burst)

    def test_patrol_revisits_do_not_assume_every_spawn_is_ready(self):
        path = ROOT / "maps" / "shattered_islands" / "world_1_71_-2"
        options = replace(self.options(), player_level=9, character_level=25)
        result = self.analyzer.analyze_map(path, options)
        slower = self.analyzer.analyze_map(
            path, replace(options, seconds_per_map=120.0))
        self.assertIsNotNone(result)
        self.assertIsNotNone(slower)
        assert result is not None and slower is not None

        renewal_ceiling = result.spawns * 3600.0 / result.respawn_seconds
        self.assertLess(result.expected_kills_lap, result.spawns)
        self.assertLessEqual(result.kills_hour, renewal_ceiling + 0.001)
        self.assertGreater(slower.expected_kills_lap, result.expected_kills_lap)
        self.assertLess(slower.kills_hour, result.kills_hour)

    def test_damage_per_attack_derives_dps_from_attack_delay(self):
        output = io.StringIO()
        with patch("sys.stdout", output):
            self.assertEqual(0, main([
                "9", "--damage-per-attack", "21", "--attack-delay", "1.2",
                "--path", r"world_1_70_-2$", "--top", "1", "--json",
            ]))
        assumptions = json.loads(output.getvalue())["assumptions"]
        self.assertEqual(21.0, assumptions["damage_per_attack"])
        self.assertEqual(1.2, assumptions["attack_delay"])
        self.assertAlmostEqual(17.5, assumptions["dps"])

        with patch("sys.stderr", io.StringIO()):
            with self.assertRaises(SystemExit):
                main(["9", "--damage-per-attack", "21", "--attack-rate", "1.2"])

    def test_all_rankings_are_machine_readable(self):
        output = io.StringIO()
        with patch("sys.stdout", output):
            self.assertEqual(0, main([
                "9", "--damage-per-attack", "21", "--attack-delay", "1.2",
                "--path", r"world_1_70_-2$", "--ranking", "all", "--json",
            ]))
        payload = json.loads(output.getvalue())
        self.assertEqual(
            {"balanced", "xp", "money", "loot", "safety", "maneuverability"},
            set(payload["rankings"]),
        )

    def test_fort_ghzal_npcs_reduce_player_reward_share(self):
        path = ROOT / "maps" / "shattered_islands" / "world_5_66"
        options = replace(
            self.options(), player_level=23, character_level=30,
            damage_per_attack=54.0, attack_delay=3.0,
            targets_per_attack=7, attack_type="fire")
        contested = self.analyzer.analyze_map(path, options)
        ignored = self.analyzer.analyze_map(
            path, replace(options, model_npc_contention=False))
        self.assertIsNotNone(contested)
        self.assertIsNotNone(ignored)
        assert contested is not None and ignored is not None
        self.assertEqual(10.0, contested.competitor_count)
        self.assertEqual(contested.spawns, contested.contested_spawns)
        self.assertLess(contested.reward_fraction, 0.20)
        self.assertAlmostEqual(1.0, ignored.reward_fraction)
        self.assertLess(contested.xp_hour, ignored.xp_hour)

    def test_authored_obstacles_reduce_achievable_aoe_targets(self):
        cluttered_path = ROOT / "maps" / "shattered_islands" / "world_15_75"
        open_path = ROOT / "maps" / "shattered_islands" / "world_17_74"
        options = replace(self.options(), targets_per_attack=7)
        cluttered = self.analyzer.analyze_map(cluttered_path, options)
        open_area = self.analyzer.analyze_map(open_path, options)
        unadjusted = self.analyzer.analyze_map(
            cluttered_path, replace(options, model_maneuverability=False))
        self.assertIsNotNone(cluttered)
        self.assertIsNotNone(open_area)
        self.assertIsNotNone(unadjusted)
        assert cluttered is not None and open_area is not None and unadjusted is not None
        self.assertLess(cluttered.maneuverability, open_area.maneuverability)
        self.assertLess(cluttered.effective_targets_per_attack,
                        open_area.effective_targets_per_attack)
        self.assertAlmostEqual(unadjusted.pack_target_capacity,
                               unadjusted.effective_targets_per_attack)

    def test_character_profile_round_trip_and_cli_override(self):
        with tempfile.TemporaryDirectory() as directory:
            profile = Path(directory) / "wizard.json"
            with patch("sys.stdout", io.StringIO()):
                self.assertEqual(0, main([
                    "9", "--damage-per-attack", "21", "--attack-delay", "1.2",
                    "--mana-cost", "6", "--mana-regen", "1.2", "--max-mana", "58",
                    "--path", r"world_1_70_-2$", "--save-profile", str(profile),
                    "--json",
                ]))
            output = io.StringIO()
            with patch("sys.stdout", output):
                self.assertEqual(0, main([
                    "9", "--profile", str(profile), "--damage-per-attack", "22",
                    "--path", r"world_1_70_-2$", "--json",
                ]))
            assumptions = json.loads(output.getvalue())["assumptions"]
            self.assertEqual(22.0, assumptions["damage_per_attack"])
            self.assertEqual(6.0, assumptions["mana_cost"])

    def test_character_level_and_health_drive_survivability(self):
        path = (ROOT / "maps" / "shattered_islands" / "strakewood_island" /
                "old_outpost" / "old_outpost_0202")
        low_character = replace(
            self.options(), player_level=9, character_level=9, max_level_gap=5)
        self.assertIsNone(self.analyzer.analyze_map(path, low_character))

        veteran = replace(low_character, character_level=50, max_health=1000.0)
        result = self.analyzer.analyze_map(path, veteran)
        self.assertIsNotNone(result)
        assert result is not None
        self.analyzer._score([result], veteran)
        self.assertAlmostEqual(
            result.damage_clear / veteran.max_health,
            result.health_clear_fraction,
        )
        self.assertAlmostEqual(
            veteran.max_health / result.avg_damage_taken,
            result.survivable_kills,
        )

    def test_training_simulation_reranks_from_source_xp_table(self):
        options = replace(
            self.options(path_pattern=r"world_2_71_-2$"),
            player_level=9,
        )
        stages = simulate_training(self.analyzer, options, 0.01, None)
        self.assertTrue(stages)
        self.assertEqual(9, stages[0]["level"])
        self.assertGreater(stages[0]["xp_hour"], 0.0)

    def test_scheduled_swamp_ghouls_are_time_sensitive(self):
        path = ROOT / "maps" / "shattered_islands" / "world_1_50"
        daytime = self.analyzer.analyze_map(path, self.options(minute=12 * 60))
        nighttime = self.analyzer.analyze_map(path, self.options(minute=0))
        self.assertIsNotNone(daytime)
        self.assertIsNotNone(nighttime)
        assert daytime is not None and nighttime is not None
        self.assertEqual(7, daytime.spawns)
        self.assertEqual(10, nighttime.spawns)
        self.assertEqual(157_500, daytime.xp_clear)
        self.assertEqual(225_000, nighttime.xp_clear)

    def test_strakewood_density_is_distinct_from_direct_aggro(self):
        path = ROOT / "maps" / "shattered_islands" / "world_4_51"
        result = self.analyzer.analyze_map(path, self.options())
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(4, result.aggressive_spawns)
        self.assertEqual(0, result.passive_spawns)
        self.assertEqual(1, result.max_aggro_pack)
        self.assertEqual(3, result.max_proximity_pack)

        filtered = self.analyzer.analyze_map(
            path, replace(self.options(), max_aggro_pack=1))
        self.assertIsNotNone(filtered)

        # Neutral-aligned mud hands are still aggressive, but their spawn
        # points are not automatically one encounter merely because an
        # eight-tile proximity chain connects them.
        mud_hands = self.analyzer.analyze_map(
            ROOT / "maps" / "shattered_islands" / "world_12_79",
            replace(self.options(), max_aggro_pack=1))
        self.assertIsNotNone(mud_hands)
        assert mud_hands is not None
        self.assertGreater(mud_hands.max_proximity_pack,
                           mud_hands.max_aggro_pack)
        passive = self.analyzer.analyze_map(
            ROOT / "maps" / "shattered_islands" / "world_14_78",
            replace(self.options(), max_aggro_pack=1))
        self.assertIsNotNone(passive)
        assert passive is not None
        self.assertEqual(0, passive.aggressive_spawns)
        self.assertEqual(8, passive.passive_spawns)
        self.assertEqual(1, passive.max_aggro_pack)
        self.assertGreater(passive.max_proximity_pack, 1)

    def test_unaggressive_snowmen_reduce_achievable_aoe_pull(self):
        snowmen_path = ROOT / "maps" / "shattered_islands" / "world_12_7"
        aggressive_path = ROOT / "maps" / "shattered_islands" / "world_4_51"
        options = replace(
            self.options(), targets_per_attack=7,
            model_maneuverability=False)
        snowmen = self.analyzer.analyze_map(snowmen_path, options)
        aggressive = self.analyzer.analyze_map(aggressive_path, options)
        manually_pulled = self.analyzer.analyze_map(
            snowmen_path, replace(options, passive_pull_efficiency=1.0))
        self.assertIsNotNone(snowmen)
        self.assertIsNotNone(aggressive)
        self.assertIsNotNone(manually_pulled)
        assert snowmen is not None and aggressive is not None and manually_pulled is not None
        self.assertEqual(0.0, snowmen.aggressive_spawns)
        self.assertEqual(snowmen.spawns, snowmen.passive_spawns)
        self.assertAlmostEqual(0.20, snowmen.aoe_pullability)
        self.assertAlmostEqual(1.0, aggressive.aoe_pullability)
        self.assertLess(snowmen.effective_targets_per_attack,
                        aggressive.effective_targets_per_attack)
        self.assertAlmostEqual(manually_pulled.pack_target_capacity,
                               manually_pulled.effective_targets_per_attack)

    def test_underground_city_rooms_form_dense_controlled_packs(self):
        base = (ROOT / "maps" / "shattered_islands" / "strakewood_island" /
                "underground_city")
        options = replace(self.options(), targets_per_attack=7)
        city = self.analyzer.analyze_map(
            base / "underground_city_0_0", options)
        eld = self.analyzer.analyze_map(
            ROOT / "maps" / "shattered_islands" / "world_15_75", options)
        self.assertIsNotNone(city)
        self.assertIsNotNone(eld)
        assert city is not None and eld is not None
        self.assertEqual(4.0, city.encounter_packs)
        self.assertAlmostEqual(3.75, city.average_pack_size)
        self.assertEqual(5.0, city.largest_pack_size)
        self.assertGreater(city.arena_quality, 0.90)
        self.assertGreater(city.maneuverability, eld.maneuverability)
        self.assertGreater(city.pack_target_capacity, eld.pack_target_capacity)

        members = [
            self.analyzer.analyze_map(
                base / f"underground_city_{x}_{y}", options)
            for x in range(2) for y in range(2)
        ]
        self.assertTrue(all(member is not None for member in members))
        circuits = self.analyzer._circuits(
            [member for member in members if member is not None],
            replace(options, circuit_size=4))
        self.assertEqual(1, len(circuits))
        self.assertEqual(4, len(circuits[0].map_paths))

        candidates = [member for member in members if member is not None] + circuits
        for index, candidate in enumerate(candidates):
            candidate.score = float(index)
        groups = group_farming_results(candidates, 10)
        self.assertEqual(2, len(groups))
        self.assertEqual(4, len(groups[0].candidates))
        self.assertIs(circuits[0], groups[0].representative)

        deeper = replace(
            circuits[0], avg_monster_level=55.0,
            min_monster_level=52, max_monster_level=58)
        self.assertEqual(3, len(group_farming_results(candidates + [deeper], 10)))

    def test_adjacent_circuits_reproduce_swamp_and_graveyard_routes(self):
        swamp_options = self.options(
            circuit_size=4,
            path_pattern=r"world_[01]_5[01]$",
        )
        swamp = self.analyzer.scan(swamp_options)
        swamp_circuit = next(result for result in swamp if result.path.startswith("circuit["))
        self.assertEqual(24, swamp_circuit.spawns)
        self.assertEqual(540_000, swamp_circuit.xp_clear)
        self.assertAlmostEqual(31.8, swamp_circuit.loot_clear, places=1)
        self.assertEqual("The Strakewood Island", swamp_circuit.location.split(";", 1)[0])
        self.assertEqual(
            (
                "1 tile south of Asteria",
                "1 tile north of Centennial",
                "3 tiles northwest of Fort Sether",
            ),
            swamp_circuit.nearby_landmarks,
        )

        grave_options = self.options(
            minute=0,
            circuit_size=4,
            path_pattern=r"world_14_7[45]$",
        )
        graveyard = self.analyzer.scan(grave_options)
        grave_circuit = next(result for result in graveyard if result.path.startswith("circuit["))
        self.assertEqual(21, grave_circuit.spawns)
        self.assertEqual(456_372, grave_circuit.xp_clear)

    def test_world_map_depth_is_not_mistaken_for_a_horizontal_coordinate(self):
        self.assertEqual(
            ("world", 1, 70, -3),
            LocationIndex.world_coordinates("world_1_70_-3"),
        )
        results = self.analyzer.scan(self.options(
            circuit_size=4,
            path_pattern=r"world_1_7[01]_-[23]$",
        ))
        circuits = [result for result in results if result.path.startswith("circuit[")]
        self.assertTrue(any(
            "world_1_70_-2" in result.path and "world_1_71_-2" in result.path
            for result in circuits
        ))
        self.assertFalse(any("world_1_70_-3" in result.path for result in circuits))

    def test_region_exclusion_accepts_island_name_and_includes_children(self):
        options = replace(
            self.options(path_pattern=r"eld_woods_island"),
            excluded_regions=("Eld Woods",),
        )
        self.assertTrue(self.analyzer.locations.region_is_excluded(
            "eld_woods_island", options.excluded_regions))
        self.assertTrue(self.analyzer.locations.region_is_excluded(
            "clearhaven", options.excluded_regions))
        self.assertFalse(self.analyzer.locations.region_is_excluded(
            "brynknot", options.excluded_regions))
        self.assertEqual([], self.analyzer.scan(options))


if __name__ == "__main__":
    unittest.main()
