"""The stage registry's defectbench source (kit/stagereg.py loads every kit/stagereg_ext_*.py): kit defectbench as the
option of a new `devbench` stage, the synthetic benches a mesh-fix recipe or a switch alarm is developed on before
any frozen test.

kit/defectbench.py and docs/tools/defectbench.md: planted sheet-switch bands, rough tracing, folds, bridges and gap
strips on synthetic spirals with per-vertex truth, sized like spiral-fit columns of public PHerc0343. Development
only: a bench score is never a result on a scroll. Standard library only here."""

WORKFLOWS = ("cli",)
STAGE_LINE = ("a synthetic development bench with known answers that a mesh fix or an alarm is scored on before any "
              "frozen test (never a result on a scroll)")


def _register():
    from . import stagereg
    stagereg.STAGES.setdefault("devbench", STAGE_LINE)


_register()


def rows():
    return [{"stage": "devbench", "name": "defectbench", "origin": "ours",
             "by": "kit defectbench: planted sheet-switch bands, rough tracing, folds, bridges and gap strips on "
                   "kit planted's spiral sheets at a 91 x 405 column grid, per-vertex truth, a mini track with a "
                   "sheet prediction; scores alarms and repairs against none, all, identity and oracle controls",
             "licence": "Apache-2.0", "compute": "cpu", "maturity": "experimental",
             "why": "check recomputes every label from the coordinates and fails on a moved vertex; every control "
                    "fails as it must and the oracles pass; roughness matched to two PHerc0343 spiral-fit columns' "
                    "crease and spike shares (one variant) and Taubin moves (the other)",
             "reach": "docs/tools/defectbench.md",
             "use": {"cli": {"command": ["python3", "-m", "kit.defectbench", "score"]}},
             "source": "kit/stagereg_ext_defectbench.py"}], {}
