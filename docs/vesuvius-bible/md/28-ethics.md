# Data, Licences and Responsible Practice {#ch-ethics}

> **Chapter summary.** Challenge data is released under CC BY-NC 4.0 unless noted, and the legacy EduceLab-Scrolls scans are copyrighted by EduceLab and the University of Kentucky. Users agree to cite the dataset and not to publish "any revelation of hidden text" without written approval. Prize rules add open-source, open-data and reproducibility requirements and an embargo on discoveries. This chapter sets out those terms, the safeguards against machine "hallucination" of letters, and how this book handles images and data.

## Licences of the data

From the data page [VC-Data]:

- "CC-BY-NC 4.0 (unless otherwise noted for specific assets)".
- "Scrolls 1-4 and Fragments 1-6 scanned at DLS before 2025 are from the EduceLab-Scrolls Dataset, copyrighted by EduceLab/The University of Kentucky. Permission to use the data linked herein according to the terms outlined above is granted to Vesuvius Challenge, with additional citation requirements listed in How to Cite."

Two citations exist: "Vesuvius Challenge - CT Scans of Herculaneum Papyri" for newer scans released by the challenge, and "EduceLab-Scrolls" for the legacy dataset. "If you are publishing or presenting results, make sure you cite the dataset that corresponds to the scans you used" [VC-Data].

CC BY-NC 4.0 allows sharing and adaptation with attribution, for non-commercial purposes [CC-BYNC4].

## The data agreement

The FAQ summarizes the publication conditions "specified in the Data Agreement" [VC-FAQ]:

- "Any publications and presentations must cite the dataset(s) used."
- "You won't publish any revelation of hidden text (or associated code) without the written approval of Vesuvius Challenge."

The FAQ adds that researchers and students are "very much" encouraged to publish within those conditions [VC-FAQ]. Access to some data has required registration since 2023 ([Chapter 9](#ch-founding)).

## Prize rules that shape practice

From the 2027 prize rules [VC-Prizes]:

| Rule | Text |
|---|---|
| Open source | "you have to make it open source under a permissive license, publicly on GitHub, to accept the prize" |
| Open training data | "Any dataset created or used to train ML models must be published publicly, under a CC-BY-NC 4.0 license" |
| Pseudo-label stages | "the datasets and checkpoints at every stage must be released under a CC-BY-NC 4.0 license" |
| Seeds | "random seeds must be fixed and reported, for both training and inference" |
| Allowed inputs | any public resource "provided that use is permitted by that resource's own license or terms"; "Data derived from higher resolution scans of the submitted scroll volume cannot be used" |
| Embargo | "Do not make your discovery public until winning the prize is officially announced" |
| Discretion | prizes for near misses are "entirely at our discretion" |
| Co-publication | winners' results are verified, put "in a historical context", and co-published "in academic venues where applicable" |

## Guarding against invented letters

A model with a large field of view can learn what letters look like and draw them where there is no ink. The rules say: "The larger your model's window size, the easier it is for it to invent plausible letterforms instead of recovering real ink. Large windows are fine, but you must demonstrate that the text is" supported by the data, and submissions must explain "False-positive mitigation" [VC-Prizes]. In 2024 the challenge discouraged windows larger than 0.5 x 0.5 mm ([Chapter 21](#ch-ink)) [VC-Prizes2024].

The ink tutorial's safeguards for pseudo-labelling [VC-InkTutorial]:

- "The model only sees small local patches, smaller than a full letter, so it cannot learn to 'draw' plausible letterforms."
- "Labeling is conservative: only regions where strokes are clearly and repeatably visible get labeled."
- "Validation regions are held out."
- "Final readings are always reviewed by papyrologists. Machine output is never treated as a substitute for reading."

The judges "may also run your method, following your instructions, on held-out data with known ground truth" [VC-Prizes]. Readings are scored by papyrologists "who independently attribute a legibility score" [VC-Prizes].

## Cultural heritage

The scrolls are held by the Biblioteca Nazionale di Napoli and, for the Paris rolls, the Institut de France; Oxford's Bodleian Libraries hold rolls given in the nineteenth century ([Chapter 15](#ch-inventory)). The challenge's methods are non-invasive: the scrolls are imaged by X-ray CT and are not opened ([Chapter 7](#ch-xray)). The physical history in [Chapter 3](#ch-unrolling) shows what earlier opening methods destroyed, which is the main argument for virtual unwrapping.

## How this book handles images and data

- **No scan renders.** The book reproduces no CT slices, surface renders or ink predictions from challenge data. Scrolls are described with numbers and with charts the editors drew from those numbers.
- **Photographs** are from Wikimedia Commons or other sources with a reuse licence, each captioned with source and licence (Appendix F).
- **Charts and diagrams** are the editors' own, drawn from the CSV files in `data/`, and licensed CC BY 4.0 as part of this book.
- **Quotations** from scrollprize.org and the Substack are short and attributed. *The book's own licence for text is the editors' choice and should be confirmed before redistribution.*
- **Unverified statements** are written in italics and labelled.
