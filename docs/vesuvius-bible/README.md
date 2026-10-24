# The Vesuvius Challenge Bible

An edited, fully cited reference on the Herculaneum papyri and the Vesuvius Challenge, dated 15 October 2026. Start with [index.md](index.md) (chapter list and summaries) or [llms.txt](llms.txt) (agent entry point). [bible.md](bible.md) is the whole book in one file; `md/` holds one file per chapter.

- `data/`: the CSV or JSON behind every chart, plus the prize, scan and bibliography tables.
- `figures/charts/`: charts drawn by the editors from `data/`, as SVG.
- Photographs and the PDF are not stored in git. Each photo reference keeps its caption with source page and license, so the image can be fetched from its source.
- No EduceLab or Vesuvius Challenge scan-data renders are included.
- Links inside the book work on GitHub. Each heading keeps its Pandoc id (`{#ch-ink}`) for a Pandoc or PDF build, and has an `<a id="ch-ink"></a>` line before it, since GitHub ignores Pandoc ids. A link from one chapter file in `md/` to another names that file (`05-inks.md#ch-inks`); in `bible.md` every link stays in the one file (`#ch-inks`). `tests/test_doc_anchors.py` fails on any link whose anchor GitHub cannot find.
