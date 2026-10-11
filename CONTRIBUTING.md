# Contributing to Scrolls

Small, reproducible improvements are welcome: tested helpers, clearer docs,
public-data benchmarks, and carefully scoped bug fixes. Read the
[code of conduct](CODE_OF_CONDUCT.md), [quality guidelines](docs/QUALITY.md),
and [public workflow](docs/WORKFLOW.md) first. AI-assisted contributors should
also read [AGENTS.md](AGENTS.md) and [docs/AI-AGENTS.md](docs/AI-AGENTS.md).

## Before opening an issue or pull request

Search existing issues and pull requests for related work. Use the issue templates
for bugs, feature requests and questions. Discuss a large change before investing
in it. Report vulnerabilities through [SECURITY.md](SECURITY.md), and use
[SUPPORT.md](SUPPORT.md) when unsure where to ask.

Keep the change focused. The official [villa](https://github.com/ScrollPrize/villa)
project provides the engine; general engine fixes belong upstream, with a public
link here when available. Do not vendor villa, VC3D or model weights.

## Public research and data boundaries

- No claimed letters, candidate images, candidate descriptions or hints in public issues, PRs, logs or CI output. An ink map is model output, not a reading.
- No credentials, private research, operational account details or submission drafts.
- No scroll volumes, renders, maps, meshes, masks, labels, checkpoints or model weights in Git. Use synthetic fixtures or links to licensed public inputs.
- Cite dated public URLs for prize facts and published results. Separate measurements, reproductions, interpretations and untested ideas.
- State controls, data scope, uncertainty and negative results. Preserve historical evidence and hashes; a passing software test does not establish a scientific finding.

See [NOVELTY.md](docs/NOVELTY.md) and [WORKFLOW.md](docs/WORKFLOW.md).

## Local setup and checks

Use Python 3.10 or newer. From your fork or clone, create a branch from current
`main`, then work in a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m unittest discover -s tests -v
python -m kit prizes
```

The core tests need only the standard library. Numerical tests skip without their
optional dependencies. To include them:

```bash
python -m pip install numpy tifffile imagecodecs scipy zarr
python -m unittest discover -s tests -v
```

Follow [docs/TESTING.md](docs/TESTING.md) for additional experiment checks and the
limits of green CI. `kit/` changes need tests in `tests/`; prefer a small regression
that fails on the old behavior. Documentation-only changes need relevant source
and link checks. Do not run a paid or long experiment merely to make a PR.

## Sending a pull request

1. Make one coherent change on your branch and update the relevant docs.
2. Use plain sentences without long dash characters. Keep shell scripts compatible with the documented platforms.
3. Run the relevant checks and record exact commands, results and skips in the PR template.
4. Inspect the full diff, including fixtures and logs, for private material and oversized artifacts.
5. Open a PR against `main`. Resolve review conversations and wait for the repository's required checks before merging.

The maintainer is [Chase Hendrick](https://github.com/ChaseHendrick). Reviews and
support are best effort. A change can be declined if it is outside the workbench's
scope or lacks reproducible evidence.

## License and attribution

Original contributions are accepted under the existing
[Apache License 2.0](LICENSE). Submit only material you have the right to
contribute, retain upstream copyright and license notices, and identify any
separately licensed material. Dependencies, datasets and weights keep their own
terms. See [NOTICE](NOTICE). Contributing does not transfer copyright ownership.
