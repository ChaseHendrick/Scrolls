# AGENTS.md

Rules for AI agents (and people) running the headless VC3D tools in this folder. The tools enforce rules 2, 3, 4, 6 and 8 themselves; the others are on you. The [README](README.md) says what the package does; [docs/vc3d-agents.md](docs/vc3d-agents.md) is the guide to the tools, which the `guide` tool serves one section at a time and the MCP server offers as a resource.

1. **Do not publish a possible finding.** The Vesuvius Challenge prize terms forbid disclosing a discovery before the official announcement. Maps, triage lists and verdicts on scrolls whose ink is not published stay on your machine.
2. **An ink map is model output, not a reading.** Never write that letters were found or read.
3. **Preregister before looking.** On a target scroll, fix the readout rule with `python -m kit run init SLUG --scroll S --question Q --readout R` and set it running with `python -m kit run status SLUG running` before any map exists. `ink` and `detectability` with `"purpose": "target"` refuse to run without that ledger experiment.
4. **Every check must be able to fail.** Ink runs make a reverse-depth map beside the forward one; benchmark scores use it as the control (`python -m kit auc MAP --control REVERSED_MAP --labels L --mask M`). Device or render agreement needs a control too.
5. **Cite real URLs and dates** for facts about prizes, people and published results, and say whether a claim is a sourced fact, a community report, model output, an interpretation or an untested idea.
6. **No scroll data, maps or weights in git.** Tools write under `work/`, `experiments/` and `checkpoints/` of the kit home (this folder, or `KIT_HOME`; `KIT_VC3D_HOME` moves `work/vc3d`), which this folder's `.gitignore` keeps out of git. They refuse any other output path git would track, and any path when git cannot say.
7. **Changes to `kit/` come with tests** in `tests/`; run `python3 -m unittest discover -s tests`.
8. **Nothing outward without the user.** The network tools only download, anonymously. The `modal` tool refuses unless the user started the server with `KIT_ALLOW_MODAL=1`, because it rents compute; its runner is not part of this package.
9. **Plain sentences** in records and documentation.

## Glossary

| Term | Meaning here |
| --- | --- |
| `ink_9um` | The Vesuvius Challenge team's released 9 µm ink model (`scrollprize/ink_9um`), seeds 42 and 43 |
| w035 | A PHerc0139 segment the released 9 µm models trained on: a pipeline check only |
| w045 | A PHerc0139 segment unseen by Youssef Nader's v8in model but not held out from `ink_9um`, which trained on its 2.4 µm render |
| PHerc0841 | A scroll with labeled segments w00, ag896 and ag405 in the training data of none of `ink_9um`, v8in, v8in-1447, d9v2 and Reader v2: the fair generalization test for them |
| AUC | The probability that a labeled ink pixel scores above a labeled background pixel, inside the supervision mask |
| As stored, reversed | The depth order of a surface volume; the reversed map is the control and should sit near or below 0.5 |
| Kit home | The folder the tools write in and read relative paths from: `KIT_HOME`, else this folder |
| tifxyz | VC3D's surface format: a folder with `x.tif`, `y.tif`, `z.tif` and `meta.json` |
