# Roadmap (set 2026-10-07)

Plain list of what comes next, in order. Each step says what decides it. The handoff ([`../HANDOFF.md`](../HANDOFF.md)) holds the detail of the current session; this file is the longer view. No Hugging Face or forum posting (user decision, 2026-10-07).

## Now: is v8in the better reader on an unseen scroll?

1. **PHerc0841 w00**, v8in fp16 quick run on the user's Mac. Bars on the same crop, 64 px edge left out: d9v2 0.8994, `ink_9um` seed 42 0.8061 (the summary's `ink_9um` line must read 0.8061 too, or the runs are not comparable).
2. **PHerc0841 ag896 and ag405**, one at a time. Bars: d9v2 0.8230 and 0.8319, `ink_9um` 0.6594 and 0.7838.
3. **Youssef's PHerc1447 fine-tune** (`MODEL=v8in-1447`) on the same three crops. Training idea 1 with no training: does learning from the scroll whose text was just found help on another one?
4. **Pick the reader for the targets.** The preregistered v8in atlas run ([`../prereg/2026-10-07-v8in-atlas.md`](../prereg/2026-10-07-v8in-atlas.md)) runs regardless. If d9v2 stays clearly ahead on PHerc0841, write a second preregistration: d9v2 on the PHerc0813 and 0358 atlas meshes (TAUIL ran d9v2 on PHerc0826 only).
5. **Training prep** ([`2026-10-07-training.md`](2026-10-07-training.md)): stage PHerc1447 surfaces and labels, inventory the 1 µm teacher maps, smoke-test v8in's fine-tune loop here on CPU, then ask the user about a GPU budget.

## Next: the target runs

6. **v8in atlas run** (`scripts/mac-atlas-v8in.sh`), 81 meshes, overnight on the Mac. Results stay private; the user looks, then records `null` or `candidate`.
7. **Second reader on the targets** if step 4 calls for it, under its own preregistration.
8. **Hand-fix the surfaces the runs point to.** Every published read of these scrolls used automatic surfaces; fixing sheet jumps by hand in VC3D on the most promising meshes is the step nobody has published. Read the fixed surface with the best reader from steps 1 to 3.
9. **PHerc1545** has no public meshes in the atlas: tracing a first surface there would be new ground.

## Then: our own reader

10. **Idea 1, trained:** fine-tune on all three PHerc1447 windings; score on PHerc0841.
11. **Idea 2:** a 9 µm student from the team's 1.1 µm teacher maps; score on PHerc0841.
12. **Idea 3:** self-supervised pre-training on the eligible scans (nestorvfx sheets), only if 10 and 11 show the scan protocol matters.
13. **Ensemble:** average the best readers (Russo found Hecate plus Reader v2 better than either); free once the maps exist.

Every trained model is scored the same way before it touches a target: PHerc0841 labels, reverse control, 64 px edge, provenance record.

## Deadlines and records

- **October Progress Prize: 31 Oct 2026**, 11:59pm Pacific. Submit near the deadline (user decision), from [`../contrib/progress-prize-2026-10-draft.md`](../contrib/progress-prize-2026-10-draft.md), updated as results arrive.
- **First Letters and the 2027 Grand Prize: 25 Jun 2027.** A candidate is never described publicly before the announcement ([`../WORKFLOW.md`](../WORKFLOW.md) 3b).
- Every Mac run writes a provenance record and digest (operator, times, code, model, input and output hashes). Keep them; they are the attribution.
