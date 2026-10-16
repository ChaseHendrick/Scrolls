# About This Book {#ch-preface}

*The Vesuvius Challenge Bible* is a reference for anyone working on reading the Herculaneum scrolls: the history of the rolls, the physics of imaging them, the record of the Vesuvius Challenge from 2023 to October 2026, every scroll and fragment in the public catalogue, the full virtual unwrapping pipeline, the tools and formats, and the open problems. It is written for two kinds of reader: people, who will mostly read it as a PDF, and AI agents, which can read the same text as Markdown with machine-readable data alongside.

Edition date: 15 October 2026.

## How the book is sourced

- **Every fact carries a citation key** in square brackets, such as [VC-OpenProblems2026] or [Tack2016]. Keys resolve in Appendix G, which gives the title and URL. Pages on scrollprize.org and the challenge newsletter were read on 15 October 2026.
- **Quotations are exact** and in quotation marks. Where the source used a dash, the quotation may replace it with a comma or colon; no words are changed.
- **Unverified statements are in italics** and marked as unverified. They include numbers known only from a summary or abstract, and the editors' own arithmetic.
- **No readings are claimed.** Greek text quoted from the scrolls is quoted as published by the challenge and its papyrologists.
- **Numbers in charts** come from the CSV and JSON files in `data/`, each with its source.

## Images

Photographs come from Wikimedia Commons and other sources whose licences allow reuse; each caption gives the source and licence, and Appendix F lists them all. **The book reproduces no CT scan data, renders or ink predictions** from the Vesuvius Challenge or EduceLab datasets, out of respect for the data terms ([Chapter 28](#ch-ethics)). Scans are described with numbers and with charts and diagrams drawn by the editors.

## How to read it

| If you want to | Start with |
|---|---|
| understand why the scrolls matter | Chapters 1 to 3 |
| learn the material and the physics | Chapters 4 to 8 |
| know the history of the challenge and its prizes | Chapters 9 to 14 |
| find data about a particular scroll | Chapter 15 and Appendix C |
| understand or improve the pipeline | Chapters 16 to 23 |
| start contributing | Chapters 26 and 27 |
| look something up | Appendix A (glossary), the index, and Chapter 30 (FAQ) |

## For AI agents

The Markdown edition has one file per chapter in `md/`, the whole book in one file as `bible.md`, a map in `llms.txt`, and every chart's data in `data/`. Chapter anchors have the form `#ch-name`; citation keys are stable across editions. The bibliography is also available as `data/bibliography.json`.

## Status

This is an independent compilation. It is not published or endorsed by the Vesuvius Challenge, Scroll Prize, Inc., EduceLab, or any library or facility named in it. Corrections are welcome; the sources cited are authoritative where they differ from this book.
