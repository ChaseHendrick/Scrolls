"""Where kit writes, and where it reads the files that come with its source.

Everything kit writes goes into one folder, the kit home: runs and caches under work/ (the agent tools under
work/vc3d, unless KIT_VC3D_HOME moves them), the experiment ledger under experiments/, downloaded ink models under
checkpoints/. The kit home is

  * KIT_HOME, when it is set;
  * otherwise the source folder, when kit runs from one (scripts/ beside kit/: a clone, or an editable install
    of one), which is how kit has always worked;
  * otherwise the current working directory (a plain `pip install .` puts kit in site-packages, which is no
    place for runs).

Relative paths given to the agent tools and to `kit autopipeline` are read from the kit home too.

Some commands read files that ship with the source, not with the package: scripts/vc3d/ (the ink runner and
the Modal apps) and docs/ (the guides the agent tools serve). source_file() finds them beside kit/ and says
how to get them when they are missing. Standard library only.
"""

import os
from pathlib import Path

ENV = "KIT_HOME"
SOURCE = Path(__file__).resolve().parents[1]   # the folder that holds kit/


class MissingSource(FileNotFoundError):
    """A file kit reads from its source folder is not there: kit was installed without its source."""


def source_checkout(source=None):
    """True when kit runs from a source folder: scripts/ sits beside kit/."""
    return (Path(source or SOURCE) / "scripts").is_dir()


def home(env=None, source=None):
    """The kit home: KIT_HOME, else the source folder when kit runs from one, else the working directory."""
    env = os.environ if env is None else env
    given = (env.get(ENV) or "").strip()
    if given:
        return Path(os.path.abspath(os.path.expanduser(given)))
    src = Path(source or SOURCE)
    return src if source_checkout(src) else Path.cwd()


def path(*parts, env=None):
    """A path under the kit home."""
    return home(env).joinpath(*parts)


def source_file(rel, need=None, source=None):
    """A file or folder that ships with kit's source (scripts/vc3d/ink.py, docs/vc3d-agents.md), or MissingSource
    saying what needs it and how to get it."""
    src = Path(source or SOURCE)
    p = src / rel
    if p.exists():
        return p
    raise MissingSource(f"{rel} is not beside the kit package in {src}" + (f"; {need} needs it" if need else "")
                        + ". It ships with the source folder, not with the package: install from a copy of the "
                        "source with `pip install -e .` and keep that folder.")


def python_env(env=None):
    """A copy of env in which `python -m kit` imports this kit (its folder first on PYTHONPATH), so a child started
    in the kit home, away from the source folder, still finds it."""
    env = dict(os.environ if env is None else env)
    rest = [p for p in (env.get("PYTHONPATH") or "").split(os.pathsep) if p and p != str(SOURCE)]
    env["PYTHONPATH"] = os.pathsep.join([str(SOURCE), *rest])
    return env
