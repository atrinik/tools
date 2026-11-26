from pathlib import Path
import sys
import unittest


APP_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_ROOT))

from system.checker import CheckerObject  # noqa: E402
from system.constants import Game  # noqa: E402
from system.game_object import ArchObject, GameObject, MapObject  # noqa: E402


class LootCheckerTests(unittest.TestCase):
    def setUp(self):
        self.map = MapObject("test map")
        self.map.setAttribute("difficulty", "5", modified=False)
        self.map.setAttribute("region", "test", modified=False)

        self.spawn = GameObject("spawn_point")
        self.spawn.setAttribute("type", str(Game.Types.spawn_point),
                                modified=False)
        self.spawn.map = self.map

        self.arch = ArchObject("kobold")
        for attr, value in (("type", Game.Types.monster), ("race", "kobold"),
                            ("level", 3)):
            self.arch.setAttribute(attr, str(value), modified=False)

        self.checker = CheckerObject(None)
        self.checker.setPath("/test")
        self.checker.setName("test")

    def _monster(self, **attrs):
        monster = GameObject("kobold")
        monster.setArch(self.arch)
        monster.map = self.map
        for attr, value in attrs.items():
            monster.setAttribute(attr, str(value), modified=False)
        self.spawn.inventoryAdd(monster, modified=False)
        return monster

    def _item(self, parent, **attrs):
        item = GameObject("sword")
        for attr, value in attrs.items():
            item.setAttribute(attr, str(value), modified=False)
        parent.inventoryAdd(item, modified=False)
        return item

    def _loot_errors(self, monster):
        self.checker.errors = []
        self.checker.checker_monster(monster)
        return [error for error in self.checker.errors
                if error["description"].startswith("Monster has no loot.")]

    def test_monster_without_loot_is_flagged(self):
        errors = self._loot_errors(self._monster())
        self.assertEqual(1, len(errors))
        self.assertEqual("warning", errors[0]["severity"])

    def test_explicit_empty_treasure_is_flagged(self):
        for value in ("none", "empty"):
            with self.subTest(value=value):
                monster = self._monster(randomitems=value)
                self.assertEqual(1, len(self._loot_errors(monster)))

    def test_treasure_list_counts_as_loot(self):
        self.assertEqual([], self._loot_errors(self._monster(
            randomitems="default_loot")))

    def test_arch_treasure_list_counts_as_loot(self):
        self.arch.setAttribute("randomitems", "default_loot", modified=False)
        self.assertEqual([], self._loot_errors(self._monster()))

    def test_droppable_inventory_counts_as_loot(self):
        monster = self._monster()
        self._item(monster)
        self.assertEqual([], self._loot_errors(monster))

    def test_arch_inventory_counts_as_loot(self):
        self._item(self.arch)
        self.assertEqual([], self._loot_errors(self._monster()))

    def test_non_droppable_inventory_is_not_loot(self):
        for attrs in ({"sys_object": 1}, {"startequip": 1}, {"no_drop": 1},
                      {"type": Game.Types.event_object},
                      {"type": Game.Types.quest_container}):
            with self.subTest(attrs=attrs):
                monster = self._monster()
                self._item(monster, **attrs)
                self.assertEqual(1, len(self._loot_errors(monster)))

    def test_monster_outside_map_is_not_checked(self):
        monster = self._monster()
        monster.map = None
        self.assertEqual([], self._loot_errors(monster))


if __name__ == "__main__":
    unittest.main()
