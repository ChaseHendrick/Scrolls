## Change and reason

Explain the concrete problem and resulting behavior. Link a public issue if one exists.

## Validation

List the exact checks run and their outcomes, including skips or limitations.
For code changes, describe a regression that fails before the fix when practical.
For a documentation-only change, say which links and facts were checked.

## Contribution checklist

- [ ] I read CONTRIBUTING.md and CODE_OF_CONDUCT.md.
- [ ] This PR contains no credentials, private research, candidate images or descriptions, maps, renders, meshes, masks, labels, datasets, or weights.
- [ ] Research claims have dated public sources and clearly stated controls and limitations; no reading or novelty claim is implied by model output alone.
- [ ] Third-party notices are preserved, and I have the right to contribute these changes under Apache-2.0 (with any separately licensed material identified).
- [ ] Relevant tests and documentation are updated, or I explained why they do not apply.
- [ ] Every new or changed tool has its page in `docs/tools/` updated, and `python -m kit.tooldocs check` passes.
- [ ] If this releases work from the private repository, its entry is in `docs/releases.json`, added with `python -m kit releases add` (the README section is generated from it).
