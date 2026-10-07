# 2026-10-07: M1 Pro path, and what transfers from Chase's other repositories

Research notes, not claims. Labels per [`../NOVELTY.md`](../NOVELTY.md).

## Machine

The user's machine is an Apple M1 Pro. No CUDA. (Stated by the user.)

## villa on Apple Silicon (Sourced fact, villa `e0bbb8b` and GitHub, checked 2026-10-07)

- `inference_runtime.prepare_model_for_inference` picks `cuda` if available, else `cpu`. No MPS branch in stock ink inference.
- VC3D ships a native macos-arm64 `.dmg` with `vc_*` CLI tools in `VC3D.app/Contents/MacOS/`.
- Lasagna runs on MPS since [#1639](https://github.com/ScrollPrize/villa/pull/1639).
- MPS ink inference is open in [#1865](https://github.com/ScrollPrize/villa/pull/1865) and [#1812](https://github.com/ScrollPrize/villa/pull/1812), with benchmarks from M1 Max, M4 and M5 Pro already posted. A third, [#1770](https://github.com/ScrollPrize/villa/pull/1770), closed for inactivity. Writing a fourth patch would duplicate them.

## Chase's repositories, assessed for transfer

Read from README files on 2026-10-07; private repositories were not read.

| Repository | Transfers? | How |
| --- | --- | --- |
| [GENChase](https://github.com/ChaseHendrick/GENChase) | Yes, the method | Its Apple GPU backend is accepted only after GPU vs CPU agreement under a tolerance, a deliberately wrong method that must be caught, and exact checkpoint-resume equality, recorded on an M1 Pro. The same three checks are the evidence the open MPS PRs lack from an M1 Pro. Used in [`../mac.md`](../mac.md). |
| [Research-Integrity](https://github.com/ChaseHendrick/Research-Integrity) | Yes, as discipline | "A check that cannot fail is reported as passed" is the main way First Letters reports go wrong. Recommended in [`../AI-AGENTS.md`](../AI-AGENTS.md). |
| [ThermalPilot](https://github.com/ChaseHendrick/ThermalPilot) | Yes, small | Read-only temperature monitoring on an M1 Pro during long CPU inference. Not its unverified power tuning. |
| [Undeciphered-Texts](https://github.com/ChaseHendrick/Undeciphered-Texts) | Already used | Repository structure, claim labels, case workflow, preregistration. |
| GENChase validator (volunteer compute, duty cycling, result bundles) | Not now | A volunteer-compute harness for scroll inference is not something the organizers have asked for. (Untested idea) |
| minimal-winding and the point-vortex papers | No | Logarithmic spirals appear in both, but self-similar vortex collapse says nothing about where a crushed papyrus sheet lies. Spiral fitting is an optimization over CT evidence, not a dynamics problem. |
| FibersOfEarth | No | Textile fibers, not papyrus fibers. |
| cross-section | No | WebGL cutaways; VC3D already covers viewing. |
| hh-dynamics, hh-pulse, nf-pulse, cardiac-rings, double-pendulum, rank-window, stable-expansion, collapse-without-rotation | No direct transfer | Computer-assisted proof methods. The habit of interval-checked claims fits; the code does not. |
| Games, studio and browser tools (Oro, Fins, Siegeworks, TinyLaps, Haywire, After-the-Sirens, PageArm, SaveDesk, YT-Insights, music-field-manual, hendrickresearch.com) | No | Unrelated domains. |

## Next

1. On the M1 Pro: `python -m kit doctor`, install VC3D, run the w035 control on CPU.
2. Check out #1865, run the control on MPS, apply the three GENChase-style checks, and post the numbers on the PR after asking its author. That is a concrete, reviewable contribution only a Mac owner can make.
