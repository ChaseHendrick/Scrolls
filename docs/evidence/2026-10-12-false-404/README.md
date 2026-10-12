# False-404 fix: test and render receipts

Receipts behind [villa #2058](https://github.com/ScrollPrize/villa/issues/2058) and its draft fix [villa #2060](https://github.com/ScrollPrize/villa/pull/2060), both opened by ChaseHendrick on 12 October 2026. Context and limits: [the log](../../logs/2026-10-12-upstream-reports.md).

**What was built.** villa `main` at `25f3c93c65b492be3b90e402213a1ba6b5fd624c`, twice: with the fix (one commit, tree `3f7b6741275aebb5d958c3ffcb6e61ce9f874fb4`, the commit on #2060's branch `ChaseHendrick:fix-unconfirmed-s3-404`), and unchanged with only the fix's new test files added. `linux/` is a Linux x86_64 cloud container (g++ 13.3, Qt 6.4.2, villa's Debian packages, Release, `VC_TESTING=ON`); `macos/` is an Apple Silicon Mac (macOS 27.0, Apple clang 21, villa's `scripts/build_macos.sh` with `VC_TESTING=ON`; `machine.txt`).

**Tests** (`fix-*.log` with the fix, `main-*.log` without):

| Test | With the fix | `main` |
| --- | --- | --- |
| `test_http_s3_missing` | 15 test cases pass (both machines) | 65 checks fail (both) |
| `test_s3_chunk_cache` | 3 test cases pass (both) | 5 checks fail (both) |
| `test_http_fetch_errors` | 16 test cases pass (both) | 16 test cases pass (both) |
| `test_sftp_fetch` | passes on Linux; on macOS fails the same 4 checks as `main` | passes on Linux; fails 4 checks on macOS |

The macOS `test_sftp_fetch` failures (a cancelled transfer and two gets that should fail, lines 322 to 330) occur with and without the fix, which does not touch SFTP code. `linux/v1-test_sftp_fetch.log` is an earlier, unpublished version of the fix that broke SFTP misses (3 checks); the published version keeps SFTP's 404 behaviour, and `verification.json` records the change.

**Renders** (`render-before/` is `main`, `render-after/` the fix). PHerc0139 w035, a training segment of the released ink models, in the frame of scan `20260102150214` (2.399 um), a 256 x 256 crop at x 9000, y 11000, 109 layers, streamed from the open-data bucket through [`scripts/false404/fault_relay.py`](../../../scripts/false404/fault_relay.py) with `--rate 0.3 --seed 1 --bad 1`. That relay answered the first GET of 6 chosen chunk keys with the 404 `NoSuchBucket` S3 sent in #2058, and passed everything else through. Each `summary.json` has three runs: `reference` (no false 404s, empty cache), `faulty` (the 6 false 404s, a second empty cache) and `rerun` (no false 404s, on the faulty run's cache). `relay.jsonl` logs every request the relay answered.

| Build | Run | False 404s sent | Empty markers | Zero samples | Same as `reference` |
| --- | --- | ---: | ---: | ---: | --- |
| `main` | faulty | 6 | 12 | 19.18 % | no |
| `main` | rerun | 0 | 12 | 19.18 % | no |
| fix | faulty | 6 | 0 | 0.03 % | yes |
| fix | rerun | 0 | 0 | 0.03 % | yes |

Both machines give these numbers. Whether a run is "the same as reference" compares a digest of its layers with the reference render on the same machine; Linux and macOS renders differ from each other byte for byte (different compilers), so their digests are not compared across machines.

**Not included.** The rendered layers and the before/after images are scroll renders and stay out of Git; the images are public in #2060. The patch is public as the commit on #2060's branch. Paths to local builds and data are written `SCRATCH/`; the Mac files had their home folder replaced by `SCRATCH/` when copied here, and nothing else in them was changed. `verification.json` names files in the private workbench where the runs were prepared (`docs/contrib/false-404/...`, `scripts/false404/render_demo.py`); the render driver is not published because it reads layers through a private helper module. No ink model ran, and nothing here is about a target scroll.

`SHA256SUMS` covers every file here other than itself.
