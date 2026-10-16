# Frequently Asked Questions {#ch-faq}

> **Chapter summary.** Short answers to common questions, each pointing to the chapter that gives the evidence. Answers repeat facts sourced elsewhere in the book; follow the chapter link for citations.

## About the scrolls

**What are the Herculaneum scrolls?**
Carbonized papyrus rolls buried by the eruption of Vesuvius in 79 CE and found in the Villa of the Papyri at Herculaneum between 1752 and 1754. More than 1,800 papyri and fragments are usually counted; more than 800 inventoried items are still rolled ([Chapter 2](#ch-villa)).

**What is in them?**
Mostly Greek philosophy of the Epicurean school, much of it by Philodemus of Gadara, with some Latin texts ([Chapter 2](#ch-villa), [Chapter 6](#ch-greek)).

**Why can't they simply be opened?**
They are fragile carbonized lumps. Mechanical unrolling from the 1750s onward (Piaggio's machine, Hayter, chemical attempts) destroyed or damaged many rolls ([Chapter 3](#ch-unrolling)).

**Why is the ink hard to see in X-rays?**
Herculaneum ink is mainly carbon on a carbonized papyrus, so the two have similar density. Some inks contain lead. Ink is detected by its subtle texture and morphology, "crackle", with machine learning ([Chapter 5](#ch-inks), [Chapter 21](#ch-ink)).

## About the challenge

**What is the Vesuvius Challenge?**
An open competition launched on 15 March 2023 by Nat Friedman, Daniel Gross and Brent Seales to read the scrolls, run by Scroll Prize, Inc. ([Chapter 9](#ch-founding)).

**How much prize money has been awarded?**
This book's ledger counts 233 awards totalling $1,958,500 to 15 October 2026 ([Chapter 14](#ch-ledger)).

**Who won the 2023 Grand Prize?**
Youssef Nader, Luke Farritor and Julian Schilliger shared $700,000 for more than 15 columns of Scroll 1 (PHerc. Paris 4) ([Chapter 10](#ch-2023)).

**Has a whole scroll been read?**
Yes. On 25 June 2026 the challenge announced the complete virtual unwrapping and reading of PHerc. 1667 ([Chapter 13](#ch-2026)).

**What prizes are open now?**
A pool of $2,140,000 including the $1 million 2027 Grand Prize, First Letters prizes and monthly progress prizes; milestone deadlines are 25 June 2027 ([Chapter 13](#ch-2026)).

**Can I take part without a background in papyrology?**
Yes. Most contributions are software: segmentation, tracing, spiral fitting, ink detection, tooling and infrastructure. Papyrologists review readings ([Chapter 24](#ch-community), [Chapter 26](#ch-open-problems)).

**Do I have to open-source my work?**
To accept a prize, yes, under a permissive licence; training datasets must be public under CC BY-NC 4.0 ([Chapter 28](#ch-ethics)).

## About the data

**Where is the data?**
In the public S3 bucket `s3://vesuvius-challenge-open-data/`, readable anonymously; curated datasets and models are on Hugging Face ([Chapter 23](#ch-formats)).

**How big is it?**
The catalogue volumes total about 811 TB uncompressed; one 2.4 µm volume of a large scroll is about 40 to 125 TB uncompressed ([Chapter 25](#ch-compute), [Chapter 8](#ch-scans)).

**What format is it in?**
Volumes are OME-Zarr; traced surfaces are tifxyz (three float32 TIFFs plus metadata) or meshes ([Chapter 23](#ch-formats)).

**Can I publish what I find?**
You must cite the dataset, and you may not publish "any revelation of hidden text" without the challenge's written approval ([Chapter 28](#ch-ethics)).

**Why are there no CT images of the scrolls in this book?**
The editors chose not to reproduce scan renders under the data terms. Scans are described with numbers and charts ([Chapter 28](#ch-ethics)).

## About the methods

**What does "segmentation" mean here?**
Finding and tracing the papyrus surface in the CT volume, then flattening it so ink can be detected on it ([Chapter 16](#ch-pipeline), [Chapter 18](#ch-tracing)).

**What is VC3D?**
Volume Cartographer 3D, the main tool for viewing scrolls and growing, editing and rendering surfaces ([Chapter 18](#ch-tracing), [Chapter 22](#ch-tools)).

**What is spiral fitting?**
A global method that fits one deformed spiral to a whole scroll from many local annotations, then renders the windings ([Chapter 19](#ch-spiral)).

**What GPU do I need?**
The tutorials assume an NVIDIA GPU with CUDA. The tutorial ink model trains in about an hour and a half on one H100; smaller GPUs work with smaller patches and batches ([Chapter 25](#ch-compute), [Chapter 27](#ch-howto)).

**How do you know the letters are real and not invented by the model?**
Small receptive windows, conservative labels, held-out validation regions, tests on data with known ground truth, and independent review by papyrologists ([Chapter 28](#ch-ethics), [Chapter 21](#ch-ink)).

**Why does a higher-resolution scan help?**
Smaller voxels separate tightly packed layers better, suffer less haze and preserve more ink morphology, at the cost of eight times more data for each halving of voxel size ([Chapter 7](#ch-xray), [Chapter 26](#ch-open-problems)).

**What is still unsolved?**
Automatic, reliable tracing through compressed regions; label quality; generalizing ink models across scrolls; telling "no ink" from "no ink recovered yet"; and handling data at scale ([Chapter 26](#ch-open-problems)).

## About this book

**How was this book made?**
From public sources: scrollprize.org pages, the challenge's Substack, peer-reviewed papers and preprints, Wikipedia and Wikimedia Commons. Every fact carries a citation key resolved in the bibliography; unverified points are in italics.

**Is it official?**
No. It is an independent compilation and is not endorsed by the Vesuvius Challenge, EduceLab or any institution named.

**How should an AI agent use it?**
Read `llms.txt` for the map, `bible.md` for the full text, and `data/` for machine-readable tables. Citation keys in square brackets resolve in Appendix G.
