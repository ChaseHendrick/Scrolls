Independent verification on an Apple M1 Pro (macOS 27.0, torch 2.14.1, MPS available).

Same input on both devices: the published 9.362 µm surface volume of PHerc0139 w035, `ink_9um` seed42 `step-075000.pth` (sha256 `e635558a…2a9cab`), `--overlap 0.5 --blend-mode hann --batch-size 1 --no-compile`. CPU on `main` (e0bbb8b40), MPS on this PR (6723ad158).

| Check | Result |
|---|---|
| CPU vs MPS (forward) | max abs diff 1/255, 0.000000% of pixels beyond 2 levels, Pearson 0.99999999 |
| MPS run twice | max abs diff 0 (bit-identical) |
| Control: CPU forward vs CPU reverse, same metric | 73.12% of pixels beyond 2 levels (so the comparison can tell different maps apart) |
| Time | CPU 1740 s for both directions (~870 s each); MPS 218 s and 212 s forward |

Logs confirmed `Using MPS device` on both MPS runs. With torch 2.14.1 I saw no sign of the non-blocking copy issue reported for 2.12.1: the two MPS runs are identical.

Script and comparison tool: https://github.com/ChaseHendrick/Scrolls/blob/claude/youthful-heisenberg-gdjttc/scripts/mac-verify.sh
