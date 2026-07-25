"""Processing operations. Importing this package registers every op."""

from . import ops_color, ops_detail, ops_geometry, ops_linear, ops_stretch  # noqa: F401
from .display import auto_stretch_display

__all__ = ["auto_stretch_display"]
