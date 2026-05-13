from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BrandColor:
    name: str
    hex: str
    rgb: tuple[int, int, int]


BRAND_COLORS: dict[str, BrandColor] = {
    "dark_blue": BrandColor("Dark Blue / Logo Blue", "#0F5FDC", (15, 95, 220)),
    "tech_purple": BrandColor("Tech Purple", "#5F1EBE", (95, 30, 190)),
    "dark_purple": BrandColor("Dark Purple", "#411482", (65, 20, 130)),
    "mid_purple": BrandColor("Mid Purple", "#8C69F0", (140, 105, 240)),
    "light_purple": BrandColor("Light Purple", "#B9C8FF", (185, 200, 255)),
    "tech_blue": BrandColor("Tech Blue", "#3C91FF", (60, 145, 255)),
    "mid_blue": BrandColor("Mid Blue", "#8CC8FA", (140, 200, 250)),
    "light_blue": BrandColor("Light Blue", "#C9E5FF", (201, 229, 255)),
    "tech_gray": BrandColor("Tech Gray", "#DCE6F0", (220, 230, 240)),
}

SINGLE_COLOR_HEX = BRAND_COLORS["dark_blue"].hex


def css_tokens() -> dict[str, str]:
    return {f"--color-{key.replace('_', '-')}": value.hex for key, value in BRAND_COLORS.items()}

