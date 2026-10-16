# Founding the Vesuvius Challenge {#ch-founding}

> **Chapter summary.** The Vesuvius Challenge was launched on 15 March 2023 by Nat Friedman, Daniel Gross and Brent Seales, with CT data from EduceLab, a Kaggle ink-detection competition and a grand prize for reading text inside a closed scroll. A week after launch the prize pool reached one million dollars. The challenge is run by Scroll Prize, Inc., a 501(c)(3) non-profit. This chapter describes its origins, organization, data agreement, prize philosophy and the teams behind it.

## Origins

The scientific groundwork was laid at the University of Kentucky. In 2019 Professor Brent Seales's EduceLab imaged Herculaneum scrolls at a particle accelerator, producing CT scans "at resolutions as high as 4 µm", and also scanned and photographed detached fragments with visible ink to provide ground truth [VC-FirstLetters]. Seales's graduate student Stephen Parsons showed that machine-learning models could detect ink in the CT of those fragments. "That success caught the eye of tech entrepreneurs Nat Friedman and Daniel Gross, who started Vesuvius Challenge to accelerate this progress" [VC-FirstLetters].

The software lineage is equally long. Seth Parker of EduceLab started the Volume Cartographer project in 2013 to work on the 2009 Herculaneum scans; its first success was the virtual unwrapping of the En-Gedi scroll, published in *Science Advances* in 2016 [VC-NewScans2023]. Volume Cartographer, EduceLab's *ink-id* code (Parsons), *Quick Segment*, and Parsons's dissertation *Hard-Hearted Scrolls* are acknowledged by the challenge as the foundation the community built on; EduceLab members are not eligible for prizes [VC-Winners].

## Launch, 15 March 2023

The challenge launched on 15 March 2023 [VC-GrandPrize]. Its first public assets were [VC-Launch] [VC-PrizesOverview2023]:

- CT scans of two complete scrolls from the Institut de France, PHerc. Paris 3 (Scroll 2) and PHerc. Paris 4 (Scroll 1), made at the Diamond Light Source at 7.91 µm, and of detached fragments with infrared photographs and ink labels;
- a **Kaggle competition** for ink detection on fragments;
- **open-source prizes** for tools;
- a **Grand Prize** for reading text inside a closed scroll by 31 December 2023.

Within a week, more than 400 people had joined the Discord server and more than 300 had registered for the data. Two donors offered $50,000 each; when this was announced, more than a dozen others followed, and "by the time the dust had settled, the grand prize had grown from $150,000 to $700,000, and the overall prize pool stood at ONE MILLION DOLLARS" [VC-Launch]. The sponsors named in that announcement were Joseph Jacks, John Collison, Patrick Collison, Tobi Lütke, Guillermo Rauch, Arthur Breitman, Matt Huang, Julia DeWahl, Dan Romero, an anonymous donor, Bastian Lehmann, Aaron Levie, Ivan Zhao, Stephanie Sher, Amjad Masad and Conor White-Sullivan [VC-Launch]. Almost 100 contestants had submitted on Kaggle by then, and François Chollet published a Keras starter notebook [VC-Launch].

The Kaggle ink-detection prizes were raised to $100,000 the next day: $25,000, $20,000, $15,000 and $10,000 for the top four places and $5,000 each for fifth to tenth [VC-KaggleIncrease]. By 30 March the plan was: open-source prizes due 11 April 2023; the Kaggle Ink Detection Progress Prize due 14 June 2023; the $700,000 Grand Prize due 31 December 2023 [VC-PrizesOverview2023].

## Organization

- **Legal entity.** Prizes are awarded at the sole discretion of Scroll Prize, Inc., subject to review by the Technical Team, Annotation Team and Papyrological Team [VC-Prizes]. The FAQ describes Scroll Prize, Inc. as "a 501c3 non-profit organization that was formed solely to solve the puzzle of the Herculaneum Papyri" [VC-FAQ].
- **Founders.** Nat Friedman, Daniel Gross and Brent Seales [VC-GrandPrize]. Nat Friedman is described in 2026 as the "co-founder, instigator and main sponsor" [VC-GP2027].
- **Funding.** Many individual donors, and a donation of $2,084,000 from the Musk Foundation toward Stage Two [VC-MasterPlan]; the dataset is hosted for two years through the AWS Open Data Program [VC-WeAreCooking]. By October 2023 the challenge had spent "about $500,000 in prizes and operational costs" [VC-RaceIsOn].
- **Teams.** A technical team (review and, from 2025, an in-house research team that is ineligible for prizes), an annotation (segmentation) team, and a papyrology team led in recent years by Prof. Federica Nicolardi [VC-Hiring2025] [VC-FirstTitle] [VC-HardParts].
- **Partners.** EduceLab (University of Kentucky); the Biblioteca Nazionale di Napoli and its Officina dei Papiri Ercolanesi; the Institut de France; the Bodleian Libraries, Oxford; Diamond Light Source; the ESRF [VC-NewScans2023] [VC-Scroll5] [VC-FirstScroll].

## The data agreement

Access to the scan data originally required agreeing to a data licence. The FAQ summarizes its central publication rule: researchers may generally publish results, provided that "you won't publish any revelation of hidden text (or associated code) without the written approval of Vesuvius Challenge" [VC-FAQ]. Prize rules add that winners must not make a discovery public until the prize is officially announced [VC-Prizes]. Scan volumes now carry the CC BY-NC 4.0 licence or the EduceLab Data License ([Chapter 8](#ch-scans)). [Chapter 28](#ch-ethics) discusses what these terms mean for contributors and for this book.

## Prize philosophy

The organizers stated from the start that they are "big believers in open source and incremental progress" [VC-KaggleIncrease]. Three principles recur in the prize design:

1. **Open sourcing as a condition of winning.** Milestone prizes require code and results to be released under a permissive licence on acceptance [VC-Prizes].
2. **Many small prizes alongside a few large ones.** Monthly progress prizes (from $250 to $20,000) reward tools that "actually get used", early release and documentation [VC-Prizes].
3. **Independent review.** A technical team reproduces methods; an independent papyrology team judges readings, often blind and with multiple reviewers [VC-GrandPrize] [VC-Prizes].

The prizes also adapted to the state of the problem: Kaggle competitions where a well-posed benchmark existed (ink in 2023, surface detection in 2025 and 2026), milestone prizes for first letters and titles, and from 2024 monthly progress prizes [VC-NewPrizes2024].

## The stages

The master plan (as updated in July 2025) describes the work in stages [VC-MasterPlan]:

| Stage | Content as described | Cost estimate |
|---|---|---|
| Two | the 2023 breakthrough ("more than four passages of never-before-seen text"), words from a second scroll in 2024, and in 2025 optimization of scanning toward "the 300 extant scrolls"; two remaining problems, unwrapping at scale and ink identification | $5 to 6 million, "partially funded" by many individual donors and $2,084,000 from the Musk Foundation |
| Three | once unwrapping is automated and ink identification generalizes, systematize and staff scanning, segmenting and reading; "all the remaining 300 scrolls" in 2 to 3 years | $4 to 8 million with an efficient beamline protocol, otherwise $15 million or more |
| Four | inspire continued excavation of the Villa dei Papiri: "It is a near-certainty that there are more scrolls waiting for us in the dirt" | "largely a political effort" |

The plan states that "full scrolls are 10cm-20cm wide and up to 15 meters long", that "with current techniques, it could cost $1-5 million to unwrap an entire scroll", which for 300 scrolls is "clearly impractical", and that "we believe it's possible to bring the cost of unwrapping an entire scroll to $5000 or below. It might even be possible to fully automate it" [VC-MasterPlan]. [Chapter 25](#ch-compute) returns to these numbers.
