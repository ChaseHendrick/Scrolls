# Modal run specs

One file per job that should run on Modal rather than for hours on CPU (AGENTS.md hard rule 11). Claude's cloud sessions cannot reach Modal (their proxy does not carry Modal's gRPC traffic), so they write the spec here and give the user a short prompt to paste into Codex, or commands to run on their own computer. The agent that runs it records the outcome in the spec and the time in the compute ledger ([`../../compute.md`](../../compute.md)).

This folder is public. Only generic jobs on public data belong here; a job about a target scroll, or one whose outputs could show a possible finding, gets its spec in Scrolls-private instead (rule 1).

Name: `YYYY-MM-DD-<slug>.md`. Each spec says:

1. **Goal**, and the preregistration if the job produces a map that needs one (rule 3).
2. **Inputs**: public URLs, with checksums where known.
3. **Code**: repository, branch and commit, plus the exact commands.
4. **Machine**: GPU type and count, expected wall time and cost ([pricing](../modal-pricing.md)), and the cap past which to stop and ask.
5. **Outputs**: where they go (never git) and what to copy back.
6. **Checks**: how to tell the run worked, including its control (rule 4).
7. **Prompt for the runner**: a few lines the user can paste as is.
