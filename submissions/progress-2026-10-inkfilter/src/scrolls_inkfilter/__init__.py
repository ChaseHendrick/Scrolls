"""Fixed surface-volume filters. An ink map is filter output, not a reading."""

from .core import DEFAULT_RECIPE, RECIPES, InkFilterError, ink_map

__version__ = "0.1.0"
__all__ = ["DEFAULT_RECIPE", "RECIPES", "InkFilterError", "ink_map"]
