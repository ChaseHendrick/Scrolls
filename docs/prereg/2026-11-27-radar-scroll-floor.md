# Preregistration: Vesuvius Radar scroll floor (27 Nov 2026)

Frozen before any rating is read. Tool: [vesuvius-radar](../tools/vesuvius-radar.md). Public data only (item titles and abstracts the Space already shows).

## Change under test

`scroll_floor` in `spaces/vesuvius-radar/radar.json` and `scanner.apply_scroll_floor`: an item from arXiv, journals, Zenodo or the blog and news feeds whose matched terms include a specific scroll term (herculaneum, pherc, virtual unwrapping, vc3d and the rest of the list) and whose meaning score is at least 50 gets final = max(learned, round((learned + rule) / 2)). It never lowers a score.

Why: on the live store of 27 Nov 17:37 UTC (888 items, 30 days), the learned head fitted on 29 Oct gave the arXiv paper "Complete virtual unwrapping and reading of a rolled Herculaneum papyrus" 47 and a Zenodo paper on training-free ink detection in Herculaneum papyri 35, while minor villa pull requests scored 90. No arXiv item in 30 days reached the high band (0 of 298).

## Test

- Items: the 10 items the change moves (affected) plus 150 drawn at random (Python `random.Random(1127).sample`, ids sorted first) from the other 878 items of the same store snapshot.
- Rater: one Sonnet subagent, blind to every score, band and source score; it sees title, source, kind and the first 300 characters of the summary, in a shuffled order, and rates each item's value to the work of reading the Herculaneum scrolls from CT, 0 to 100 (the learned head's own target). Label: Model output.
- Metrics on the 160 items: Spearman of old and new score with the rating; high band (60 and up) precision and recall against rating 60 and up; on the affected items, mean absolute error of old and new score to the rating.
- Control: the same rule with the generic terms (papyrus, papyri, papyrolog, vesuvius) instead of the specific list, applied to the same items; it must not do better than the specific rule, or the specific list is not what helps.
- PASS: new Spearman at least old Spearman, and mean absolute error on the affected items lower with the floor than without. Else FAIL, and the change is not merged as is.

Limits: development check on a store we looked at while designing the rule; one rater from the model family; the affected set is small (10), so it shows direction, not size.

## Result (27 Nov 2026, added after the frozen rule above)

PASS. 160 items rated (46 rated 60 or more). Spearman with the ratings: old 0.874, new 0.883. Mean absolute distance to the rating on the 10 moved items: old 35.9, new 21.0. High band: old 23 items at precision 0.91 and recall 0.46, new 28 at 0.89 and 0.54. Control (generic terms): 13 items moved, Spearman 0.875, 29 high at precision 0.86, distance on the 10 items 19.7. The control does not beat the specific rule on rank agreement or precision; it comes 1.3 points closer on the 10 items because it also lifts them, and it lifts three more papyrology items. Moved items, old to new score (rating): virtual unwrapping paper 47 to 74 (99); training-free ink detection paper 35 to 68 (97) and its code 45 to 70 (92); WindingGuard 36 to 54 (85); vesuvius-inkcheck 35 to 50 (80); two news stories 42 to 63 (80) and 36 to 50 (80); XRF ink analysis 34 to 50 (45); a Herculaneum inscription 27 to 46 (30); a news digest page 47 to 60 (55).
