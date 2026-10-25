# AGENTS.md

Rules for AI agents (and people) running AutoPipeline and the VC3D agent tools in this folder. The tools enforce rules 2, 3, 4, 6 and 8 themselves; the others are on you. The [README](README.md) says what the pipeline does; [docs/vc3d-agents.md](docs/vc3d-agents.md) is the guide to the tools, which the `guide` tool serves one section at a time.

1. **Do not publish a possible finding.** The Vesuvius Challenge prize terms forbid disclosing a discovery before the official announcement. Maps, triage lists and verdicts on scrolls whose ink is not published stay on your machine.
2. **An ink map is model output, not a reading.** Never write that letters were found or read.
3. **Preregister before looking.** On a target scroll, fix the readout rule with `python -m kit run init` before any map exists. `ink`, `detectability` and AutoPipeline's `target` purpose refuse to run without a ledger experiment that is planned or running.
4. **Every check must be able to fail.** Ink runs make a reverse-depth map beside the forward one; benchmark scores use it as the control. Device or render agreement needs a control too.
5. **Cite real URLs and dates** for facts about prizes, people and published results, and say whether a claim is a sourced fact, a community report, model output, an interpretation or an untested idea.
6. **No scroll data, maps or weights in git.** Tools write under `work/`, `experiments/` and `checkpoints/` of the kit home (this folder, or `KIT_HOME`; `KIT_VC3D_HOME` moves `work/vc3d`), which this folder's `.gitignore` keeps out of git. They refuse any other output path git would track, and any path when git cannot say.
7. **Changes to `kit/` come with tests** in `tests/`; run `python3 -m unittest discover -s tests`.
8. **Nothing outward without the user.** The network tools only download, anonymously. The `modal` tool refuses unless the user started the server with `KIT_ALLOW_MODAL=1`, because it rents compute.
9. **Plain sentences** in records and documentation.
10. **GPU work is launched by a person or an agent that can reach the GPU host.** On a machine with no model or GPU, AutoPipeline's ink stage writes a job file and stops. Run the same folder again where `KIT_INK_PYTHON` names a Python with torch and the planned models are registered, and it finishes ink. The Modal runner that read that job file during development (`a script of the source repository`) is not part of this release.
