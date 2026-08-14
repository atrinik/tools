"""Parse and evaluate source-authored treasure lists."""

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from .config import CONSUMABLE_TYPES, GEAR_TYPES, MONEY_TYPE, ROOT, WEALTH_TYPE
from .sources import _integer, _number


@dataclass
class Loot:
    packages: float = 0.0
    gear: float = 0.0
    consumables: float = 0.0
    direct_money: float = 0.0
    base_item_value: float = 0.0

    def __add__(self, other: "Loot") -> "Loot":
        return Loot(*(a + b for a, b in zip(self.values(), other.values())))

    def __mul__(self, multiplier: float) -> "Loot":
        return Loot(*(value * multiplier for value in self.values()))

    __rmul__ = __mul__

    def values(self) -> tuple[float, ...]:
        return (self.packages, self.gear, self.consumables,
                self.direct_money, self.base_item_value)


@dataclass
class TreasureEntry:
    kind: str | None = None
    target: str | None = None
    chance: int = 100
    chance_fix: int | None = None
    difficulty: int = 0
    nrof: int = 0
    attrs: dict[str, str] = field(default_factory=dict)
    yes: "TreasureEntry | None" = None
    no: "TreasureEntry | None" = None
    next: "TreasureEntry | None" = None


@dataclass(frozen=True)
class TreasureList:
    name: str
    one: bool
    first: TreasureEntry


class TreasureModel:
    """Analytic expectation evaluator for authored treasure-list branches."""

    def __init__(self, archetypes: dict[str, dict], treasure_paths: Iterable[Path]):
        self.archetypes = archetypes
        self.lists: dict[str, TreasureList] = {}
        self.warnings: set[str] = set()
        self._cache: dict[tuple[str, int, str], Loot] = {}
        for path in treasure_paths:
            self._parse_file(path)

    @classmethod
    def load(cls, archetypes: dict[str, dict], root: Path = ROOT) -> "TreasureModel":
        paths = sorted((root / "arch").rglob("*.trs")) + sorted((root / "maps").rglob("*.trs"))
        return cls(archetypes, paths)

    def _parse_file(self, path: Path) -> None:
        lines = path.read_text(errors="replace").splitlines()
        index = 0
        while index < len(lines):
            stripped = lines[index].strip()
            match = re.fullmatch(r"(treasure|treasureone)\s+(\S+)", stripped)
            if match is None:
                index += 1
                continue
            first, index = self._parse_entry(lines, index + 1)
            self.lists[match.group(2)] = TreasureList(
                match.group(2), match.group(1) == "treasureone", first)

    def _parse_entry(self, lines: list[str], index: int) -> tuple[TreasureEntry, int]:
        entry = TreasureEntry()
        while index < len(lines):
            stripped = lines[index].strip()
            index += 1
            if not stripped or stripped.startswith("#"):
                continue
            key, separator, value = stripped.partition(" ")
            value = value.strip() if separator else ""
            if not separator:
                if key == "yes":
                    entry.yes, index = self._parse_entry(lines, index)
                elif key == "no":
                    entry.no, index = self._parse_entry(lines, index)
                elif key == "more":
                    entry.next, index = self._parse_entry(lines, index)
                    return entry, index
                elif key == "end":
                    return entry, index
                continue
            if key in {"arch", "list"}:
                entry.kind, entry.target = key, value
            elif key == "chance":
                entry.chance = _integer(value, 100)
            elif key == "chance_fix":
                entry.chance_fix = _integer(value)
                entry.chance = 0
            elif key == "difficulty":
                entry.difficulty = _integer(value)
            elif key == "nrof":
                entry.nrof = _integer(value)
            else:
                entry.attrs[key] = value
        raise ValueError("unterminated treasure entry")

    @staticmethod
    def _probability(entry: TreasureEntry) -> float:
        if entry.chance_fix is not None:
            return 1.0 / max(1, entry.chance_fix)
        if entry.chance >= 100:
            return 1.0
        return max(0.0, (entry.chance - 1) / 100.0)

    @staticmethod
    def _list_category(name: str, inherited: str) -> str:
        lowered = name.casefold()
        if any(token in lowered for token in (
                "armour", "weapon", "mtools", "talisman", "ring", "amulet")):
            return "gear"
        if any(token in lowered for token in (
                "potion", "scroll", "balm", "dust", "food", "read")):
            return "consumable"
        return inherited

    def evaluate(self, name: str | None, difficulty: int, category: str = "") -> Loot:
        if not name or name == "NONE" or name.startswith("traps"):
            return Loot()
        key = (name, difficulty, category)
        if key in self._cache:
            return self._cache[key]
        treasure = self.lists.get(name)
        if treasure is None:
            self.warnings.add(f"missing treasure list: {name}")
            return Loot()
        # Break malformed recursion conservatively.
        self._cache[key] = Loot()
        if treasure.one:
            result = self._evaluate_one(treasure.first, difficulty, category)
        else:
            result = self._evaluate_all(treasure.first, difficulty, category)
        self._cache[key] = result
        return result

    def _target(self, entry: TreasureEntry, difficulty: int, category: str,
                *, one_list: bool) -> Loot:
        if difficulty < entry.difficulty or not entry.kind or not entry.target:
            return Loot()
        if entry.kind == "list":
            hint = self._list_category(entry.target, category)
            return self.evaluate(entry.target, difficulty, hint)
        record = self.archetypes.get(entry.target)
        if record is None:
            self.warnings.add(f"missing treasure archetype: {entry.target}")
            return Loot()
        attrs = record.get("attrs", {})
        item_type = _integer(attrs.get("type"))
        base_nrof = max(1, _integer(attrs.get("nrof"), 1))
        if entry.nrof and base_nrof <= 1:
            nrof = (1 + entry.nrof) / 2.0
        else:
            nrof = base_nrof
        value = _number(attrs.get("value")) * nrof
        loot = Loot(packages=1.0)
        if item_type == WEALTH_TYPE or entry.target == "wealth":
            multiplier = difficulty if one_list else (difficulty // 2) + 1
            # rndm(1, 40) gives an exact mean multiplier of 1.005 before
            # integer denomination expansion; truncation changes this by <1c.
            loot.direct_money = _number(attrs.get("value")) * multiplier * 1.005
            return loot
        if item_type == MONEY_TYPE:
            loot.direct_money = value
            return loot
        loot.base_item_value = value
        if category == "gear" or item_type in GEAR_TYPES:
            loot.gear = 1.0
        if category == "consumable" or item_type in CONSUMABLE_TYPES:
            loot.consumables = 1.0
        return loot

    def _evaluate_all(self, entry: TreasureEntry | None, difficulty: int,
                      category: str) -> Loot:
        if entry is None:
            return Loot()
        probability = self._probability(entry)
        result = probability * self._target(entry, difficulty, category, one_list=False)
        if entry.yes is not None:
            result += probability * self._evaluate_all(entry.yes, difficulty, category)
        if entry.no is not None:
            result += (1.0 - probability) * self._evaluate_all(entry.no, difficulty, category)
        result += self._evaluate_all(entry.next, difficulty, category)
        return result

    def _evaluate_one(self, first: TreasureEntry, difficulty: int, category: str) -> Loot:
        entries = []
        current: TreasureEntry | None = first
        while current is not None:
            entries.append(current)
            current = current.next
        if any(entry.chance_fix is not None for entry in entries):
            self.warnings.add("treasureone chance_fix approximated as an independent weight")
            eligible = [entry for entry in entries if difficulty >= entry.difficulty]
            weights = [
                (1.0 / max(1, entry.chance_fix)) if entry.chance_fix is not None
                else max(0, entry.chance)
                for entry in eligible
            ]
        else:
            # Mirror treasure_create_one(): its initial roll is 0..total-1,
            # then each chance is subtracted and <= 0 selects the entry.  This
            # intentionally gives the first entry one boundary value more than
            # a conventional weighted choice. Ineligible selections are
            # retried, so normalize the eligible outcomes.
            total_chance = sum(max(0, entry.chance) for entry in entries)
            selected = [0] * len(entries)
            for initial in range(total_chance):
                value = initial
                for index, entry in enumerate(entries):
                    value -= entry.chance
                    if value <= 0:
                        selected[index] += 1
                        break
            eligible = []
            weights = []
            for entry, weight in zip(entries, selected):
                if difficulty >= entry.difficulty and weight:
                    eligible.append(entry)
                    weights.append(weight)
        total = sum(weights)
        if total <= 0:
            return Loot()
        result = Loot()
        for entry, weight in zip(eligible, weights):
            result += (weight / total) * self._target(
                entry, difficulty, category, one_list=True)
        return result
