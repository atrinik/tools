"""Default source paths and shared Atrinik constants."""

from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parent
TOOLS_ROOT = PACKAGE_ROOT.parent


def _find_workspace_root() -> Path:
    """Find the wrapper workspace while retaining standalone-checkout behavior."""
    for candidate in TOOLS_ROOT.parents:
        if ((candidate / "atrinik").is_file() and
                (candidate / "components.json").is_file()):
            return candidate
    return TOOLS_ROOT.parent


WORKSPACE_ROOT = _find_workspace_root()
ROOT = WORKSPACE_ROOT / "content-1x"
MAP_ROOT = ROOT / "maps"
ARCH_ROOT = ROOT / "arch"
SERVER_ROOT = WORKSPACE_ROOT / "classic" / "server" / "src"

MONEY_TYPE = 36
WEALTH_TYPE = 125
SPAWN_POINT_TYPE = 81
MONSTER_TYPE = 80
SPAWN_POINT_MOB_TYPE = 83
RANDOM_DROP_TYPE = 102
GEAR_TYPES = {
    3, 13, 14, 15, 16, 33, 34, 35, 39, 70, 87, 99, 100, 104, 109, 113,
}
CONSUMABLE_TYPES = {5, 6, 8, 54, 85, 111}
PHYSICAL_ATTACKS = ("impact", "cleave", "slash", "pierce")
ATTACK_TYPES = PHYSICAL_ATTACKS + (
    "fire", "cold", "electricity", "poison", "acid", "drain", "magic",
)
SERVER_ATTACK_TYPES = (
    "impact", "slash", "cleave", "pierce", "weaponmagic", "fire", "cold",
    "electricity", "poison", "acid", "magic", "lifesteal", "blind",
    "paralyze", "force", "godpower", "chaos", "drain", "slow", "confusion",
    "internal",
)
STATUS_ATTACK_TYPES = {"blind", "paralyze", "slow", "confusion"}
