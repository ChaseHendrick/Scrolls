# AutoPipeline 0.1.7: ink maps in color, a demo with planted strokes

This package follows AutoPipeline 0.1.6 at public commit `8096b464007af732d9835ac9fae4be49ce2354d0`. Earlier released branches and tags stay unchanged. These are software and display changes. None of them is a new ink-accuracy result or a reading, and every map the pipeline makes is model output.

## Ink maps in color

The monitor drew ink map thumbnails as gray squares, with off-surface pixels black and small maps blown up into blocks. It now draws them in one color ramp, from dark umber (low model score) through copper to pale papyrus (high score). Each color stop sits at its own CIE L* lightness, so lightness rises evenly with the score and a brighter pixel means a higher score in the light and the dark theme. Each thumbnail is cropped to the map's on-surface pixels, off-surface pixels are transparent, and a map smaller than the thumbnail is enlarged bilinearly among on-surface pixels, so it reads as a smooth picture. The reversed control is still drawn on its forward map's scale, so a control is never stretched to look like ink. The page shows a Low to high key beside the thumbnails.

The ink Space source in `space/` draws its two ink maps with the same colors (`INK_STOPS`, checked equal to the monitor's by a test), the reversed control on the forward map's scale, and the CT surface in gray as before.

## A demo with something to look at

`scripts/demo_synthetic.py` now draws its own CT: the sheet with horizontal fibers and, on its outer face, a thin denser layer in the shape of planted pen strokes, rows of capital-like shapes. Its stand-in ink model scores that layer in the front half of each rendered column, so the forward map shows the planted strokes and the reversed control does not. A new test checks both. The strokes are planted in a synthetic CT; the demo reads nothing.

## Center lines

The pinned snapshot of [SharpMeow/vesuvius-center-lines](https://huggingface.co/datasets/SharpMeow/vesuvius-center-lines) moves to revision `c67d4743638faf6794f7dc023910934d89a96f0e` (v2.4, 24 October 2026). It adds public scans off the prize page and, for each of the Center Finder's 12 lines on 1.2 m scans, a coverage-polished copy beside the original (source `finder-polished`, made by `kit axispolish` rule 1; jumpier than the original, ends not re-checked, `usable_ends` null). The default order now takes the polished copy before the original; `prefer` with `finder` before `finder-polished` takes the original.

## Changed behavior

- A plan made by 0.1.6 that names `umbilicus.centerlines` holds revision `4ce97ee58c22b88e5d5205101d73966a330f827c`, and this kit refuses it, since it holds the dataset at the new revision only. Make the plan again (`umbilicus.centerlines` `true` takes the new defaults).

## Package

`kit run all`, `watch` and `catalog` now say so and exit 2 when AutoPipeline is missing from the folder, and `kit/vc3d_agent.py` registers AutoPipeline's four tools only when `kit/autopipe.py` is present, so the same files serve the standalone VC3D agent package; with AutoPipeline present nothing changes. A few VC3D tests skip in that package for the same reason. The agent guides use US spelling, and a fault in the script that makes their public copies, which dropped a bracket and left half a link in two places, is fixed. Version metadata changes from 0.1.6 to 0.1.7. The Docker image was not rebuilt for this version. The live ink Space also runs Reader v2 and has a Connect your tool panel, which this package's `space/` copy does not include. This package does not assert a Progress Prize form submission or award.
