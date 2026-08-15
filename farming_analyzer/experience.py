"""Mirror the classic server's source-derived experience calculations."""

import re
from dataclasses import dataclass
from pathlib import Path

from .config import SERVER_ROOT


def _extract_initializer(source: str, declaration_pattern: str) -> str:
    match = re.search(declaration_pattern, source, re.MULTILINE)
    if match is None:
        raise ValueError(f"could not find C initializer: {declaration_pattern}")
    start = source.find("{", match.end())
    if start < 0:
        raise ValueError("initializer has no opening brace")
    depth = 0
    for index in range(start, len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return source[start:index + 1]
    raise ValueError("unterminated C initializer")


def _c_numbers(initializer: str) -> list[float]:
    initializer = re.sub(r"/\*.*?\*/", "", initializer, flags=re.DOTALL)
    initializer = re.sub(r"//.*", "", initializer)
    return [
        float(token.rstrip("fFuUlL"))
        for token in re.findall(r"-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?[fFuUlL]*", initializer)
    ]


@dataclass(frozen=True)
class ExperienceModel:
    new_levels: tuple[int, ...]
    level_exp: tuple[float, ...]
    level_colors: tuple[tuple[int, int, int, int, int, int], ...]

    @classmethod
    def load(cls, server_root: Path = SERVER_ROOT) -> "ExperienceModel":
        exp_source = (server_root / "server" / "exp.c").read_text(errors="replace")
        skill_source = (server_root / "server" / "skill_util.c").read_text(errors="replace")
        levels = tuple(int(value) for value in _c_numbers(_extract_initializer(
            exp_source, r"uint64_t\s+new_levels\s*\[")))
        level_exp = tuple(_c_numbers(_extract_initializer(
            skill_source, r"static\s+float\s+lev_exp\s*\[")))
        color_init = _extract_initializer(exp_source, r"level_color_t\s+level_color\s*\[")
        rows = tuple(
            tuple(int(value) for value in _c_numbers(match.group(0)))
            for match in re.finditer(r"\{[^{}]+\}", color_init)
        )
        if not levels or not level_exp or not rows or any(len(row) != 6 for row in rows):
            raise ValueError("failed to parse server experience tables")
        return cls(levels, level_exp, rows)

    def level_difference(self, player_level: int, monster_level: int) -> float:
        if not (0 <= player_level < len(self.level_colors)):
            return 0.0
        if not (0 <= monster_level < len(self.level_colors)):
            return 0.0
        green, blue, yellow, orange, red, _purple = self.level_colors[player_level]
        if monster_level < green:
            return 0.0
        result = 1.0
        if player_level > monster_level:
            if monster_level >= yellow:
                span = max(1, player_level - yellow)
                result = 1.0 - (0.2 / span) * (player_level - monster_level)
            elif monster_level >= blue:
                span = max(1, yellow - blue)
                result = 0.4 + (0.3 / span) * (monster_level - blue + 1)
            else:
                span = max(1, blue - green)
                result = 0.25 + (0.05 / span) * (monster_level - green + 1)
        elif player_level < monster_level:
            if monster_level < orange:
                span = max(1, orange - player_level - 1)
                result = 1.0 + (0.1 / span) * (monster_level - player_level)
            elif monster_level < red:
                span = max(1, red - player_level - 1)
                result = 1.2 + (0.2 / span) * (monster_level - player_level)
            else:
                result = 1.4 + 0.1 * ((monster_level + 1) - red)
        return result

    def kill_cap(self, player_level: int) -> int:
        if player_level + 1 >= len(self.new_levels):
            return 0
        if player_level < 2:
            maximum = 0.85
        elif player_level < 3:
            maximum = 0.70
        elif player_level < 4:
            maximum = 0.60
        elif player_level < 5:
            maximum = 0.45
        elif player_level < 7:
            maximum = 0.35
        elif player_level < 8:
            maximum = 0.30
        else:
            maximum = 0.25
        level_span = self.new_levels[player_level + 1] - self.new_levels[player_level]
        return int(level_span * 0.1 * maximum)

    def kill_xp(self, player_level: int, monster_level: int, monster_exp: int) -> int:
        if monster_level < 1 or monster_exp < 1 or monster_level >= len(self.level_exp):
            return 0
        raw = int(monster_exp * self.level_exp[monster_level] *
                  self.level_difference(player_level, monster_level))
        return min(raw, self.kill_cap(player_level))
