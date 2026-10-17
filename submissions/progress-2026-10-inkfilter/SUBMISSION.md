# Fixed image filters for surface volumes

This package adds a small, inspectable filter that converts a rendered surface-volume window into a two-dimensional map without trained weights. It also produces the same calculation with reversed depth as a control. The implementation needs NumPy, runs locally on CPU, and has optional local TIFF and Zarr support.

On 56 confirmation windows from 28 publicly labelled segments across seven scrolls, the fixed recipe scored mean AUC 0.7357, compared with 0.7042 for the selected alpha-compositing baseline and 0.7077 for alpha plus high-pass. These were different nonoverlapping windows from the same development segments and scrolls. The paired difference from alpha was +0.0315, with a segment-bootstrap 95% interval [0.0221,0.0404]. Alpha scored higher on three scrolls, and the reversed filter scored higher on one. These are model outputs, not readings.

The contribution is a fixed-filter baseline with a reverse-depth control and a simple local interface. It has not been compared with trained ink models on these windows, has no measured accuracy on wholly unseen scrolls, and has not demonstrated community adoption. The included evidence supports the narrow fixed-filter comparison; it does not establish that this is the best available tool.

The [README](README.md) gives installation, commands, input conventions, algorithm and failure modes. [Evidence](evidence/README.md) records the protocol, controls, per-window scalar scores, aggregates and limitations. `python evidence/summarize.py` checks the saved aggregate arithmetic; a complete raw-data replication of the baseline bank is not bundled. The synthetic tests check the numerical components and local interface independently of any scan data. Code is Apache-2.0; referenced data and upstream methods keep the licenses stated in the README.

This text describes the contribution. It is not a prize submission receipt, acceptance of terms or announcement of an award.
