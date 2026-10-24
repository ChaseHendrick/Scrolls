"""Choose released Greek reader weights by task, without loading images or models.

The ink-lines profile uses the checkpoint with lower error in the published
given-line ink-map comparison. Automatic page reads keep the permissive profile;
the released benchmarks do not establish one checkpoint as best for every task.
This module uses only the standard library. Downloads and hash verification stay
in kit.letterread.resolve_weights.
"""

import json
from pathlib import Path


REGISTRY = Path(__file__).parent / "data" / "letter-weights.json"
DEFAULT_PROFILE = "permissive"
PROFILE_NAMES = ("ink-lines", "permissive")


def profile_info(profile=None, *, lines_given=False, registry=None):
    """Describe a weight profile, its checkpoint, license and public evidence.

    With no explicit profile, supplied line positions select ink-lines; automatic
    line finding selects permissive. Selection reads no image or readout score.
    An unknown profile or a profile naming unregistered weights raises ValueError.
    """
    name = profile if profile is not None else ("ink-lines" if lines_given else DEFAULT_PROFILE)
    data = json.loads(Path(registry or REGISTRY).read_text(encoding="utf-8"))
    profiles = data.get("profiles", {})
    if name not in profiles:
        raise ValueError(f"unknown weight profile {name!r}; choose {', '.join(PROFILE_NAMES)}")
    entry = profiles[name]
    weights = entry.get("weights")
    model = data.get("models", {}).get(weights)
    if not model:
        raise ValueError(f"weight profile {name!r} names unregistered weights {weights!r}")
    return {"name": name, "weights": weights, "license": model["license_id"],
            "scope": entry["scope"], "evidence": entry["evidence"]}


def select_weights(weights=None, profile=None, *, lines_given=False, registry=None):
    """A released name or caller's unchanged file path for letterread.load_weights.

    Explicit weights bypass profile selection; providing both is an error. With
    neither, choose ink-lines for supplied lines and permissive otherwise. The
    returned name still goes through the reader's existing pinned-hash loader.
    """
    if weights is not None:
        if profile is not None:
            raise ValueError("choose --weights or --weight-profile, not both")
        return weights
    return profile_info(profile, lines_given=lines_given, registry=registry)["weights"]
