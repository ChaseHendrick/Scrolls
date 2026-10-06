# Error log

Append-only. One entry per real failure. Fields are **date**, **command**, **failure**, and **retried**.

Times are UTC unless stated.

## Entries

### 2026-10-06, scrollprize.org blocked from the setup session

- **date:** 2026-10-06
- **command:** web fetch of `https://scrollprize.org/prizes` from the cloud session that built this repository.
- **failure:** The session's network egress policy blocked scrollprize.org and scrollprize.substack.com. The GitHub API org listing for ScrollPrize was also refused (session scoped to its own repositories).
- **retried:** No. The same content was read from the website's source in [ScrollPrize/villa](https://github.com/ScrollPrize/villa/tree/main/scrollprize.org/docs) at commit `e0bbb8b40a2d` (committed 2026-10-06), the org page through github.com, and the S3 bucket listing directly. Substack posts are cited by URL but were not read in full here.

### 2026-10-06, no GPU in the setup session

- **date:** 2026-10-06
- **command:** `python -m kit doctor`
- **failure:** `[fail] gpu No NVIDIA GPU found`. The cloud container has no GPU, so no pipeline step (render, inference) was run while building this repository.
- **retried:** No. Expected; the plan commands are copied from the tutorial, not executed here.
