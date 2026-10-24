"""Registers the lasagna_* tools (kit/lasagna.py: headless villa lasagna fits) on kit/vc3d_agent.py, which loads
every kit/vc3d_ext_*.py at import. A kit without this file serves every other tool."""

from .lasagna import register  # noqa: F401
