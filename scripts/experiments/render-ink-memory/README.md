# render_ink.py memory, 24 October 2026

Peak memory of villa `spiral-fitting/render_ink.py`'s compositing and 8-bit scaling step, current code (`old2.py`, the lines at villa `322cb08` unchanged) against the patch (`new2.py`, which loads `max_composite` and `scale_to_uint8` from a patched `render_ink.py`). Made for a villa issue about render_ink.py's memory use.

- `make.py 2000 60000`: five synthetic uint8 slice TIFFs, 120 Mpx each, no scan data.
- `sample.py PYTHON PATCHED_RENDER_INK`: runs each side three times, samples RSS from `/proc` every 10 ms, keeps the fastest run in `trace.json`.
- `chart.py OUTDIR`: the still and GIF in `docs/assets/villa-issues/`.

Result on Linux (4 CPUs, numpy 2.5.4): current 1.49 GB peak, patched 0.59 GB, identical output pixels.
