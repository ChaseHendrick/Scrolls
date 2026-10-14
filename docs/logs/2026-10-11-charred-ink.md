# 2026-10-11: ink from charred scrolls, what has actually been shown

Checked 11 October 2026 against the papers and official pages below. This adds the primary sources that were easy to confuse with the entries already in [`../papers.json`](../papers.json). It does not add a method, and an ink map is not a reading.

Two different jobs get called "ink derivation." One is recovering writing from images, including X-ray CT of a closed roll. The other is measuring what the ink is made of. A result on one specimen class does not establish the others.

| Class | What it is | What a result does not prove |
| --- | --- | --- |
| Sealed carbonized papyrus | A Herculaneum roll that is still closed | Nothing about an opened fragment's surface photograph, and nothing about parchment |
| Opened ancient fragments | Pieces already unrolled, often glued to a support | Nothing about a sealed roll, because the surface can be photographed or lit directly |
| Modern carbonized replicas | New scrolls, written and then burned | Nothing about an ancient recipe unless the replica matches it |
| Burned parchment | Animal skin, as at En-Gedi | Nothing about papyrus. En-Gedi's ink is metal-bearing and shows as bright voxels |

## Recovering writing

**Laboratory absorption micro-CT can carry a carbon-ink signal, on the specimens Parker tested.** Parker, Parsons, Bandy, Chapman, Coppens and Seales, PLOS ONE 14(5): e0215775 (8 May 2019), https://doi.org/10.1371/journal.pone.0215775. They argue against Gibson et al. 2018, who studied surrogate papyrus phantoms for mummy cartonnage and wrote that there could not then be confidence that deeper carbon ink is detectable by micro-CT (Heritage Science 6:7, https://doi.org/10.1186/s40494-018-0175-4). Parker's network was shown on controlled carbon-ink material and on one opened Herculaneum fragment, PHerc. Paris 2 fragment 96, including a lunate sigma. They did not read a sealed roll. They say a network trained on a reference library of authentic fragments could later be applied to unopened scans. Code is GPL-3.0 at https://github.com/viscenter/ink-id. Data: https://doi.org/10.17605/OSF.IO/ZDKN4. (Sourced fact)

**Synchrotron phase contrast showed letters inside rolled Herculaneum papyri, in short stretches, and those early readings stayed limited.** Mocella, Brun, Ferrero and Delattre, Nature Communications 6:5895 (20 Jan 2015), https://doi.org/10.1038/ncomms6895. Two Paris scrolls, one still rolled. The authors report letters, mostly found by hand on small surface pieces, and they list the limits: inner windings are hard to separate, texture hides characters, and some letters are flipped. A 2016 follow-up (Bukreeva et al., Scientific Reports 6:27227, https://doi.org/10.1038/srep27227) reports longer Greek stretches and a coronis inside unopened rolls, still from phase-contrast tomography plus virtual unrolling. Parker 2019 records that those phase-contrast letter claims had not then been extended to complete passages. This is not the same scan as a later absorption volume. (Sourced fact)

**The Vesuvius Challenge is the first public, papyrologist-reviewed reading of substantial text from sealed carbonized papyrus, from X-ray CT plus virtual unwrapping and machine learning.** Official Grand Prize page, read 11 October 2026: https://scrollprize.org/grandprize. Awarded 5 February 2024 for PHerc.Paris. 4. The page requires 4 passages of 140 characters with at least 85 percent recoverable, and it reports another 11 columns, more than 2000 characters, about 5 percent of that scroll. It calls the method machine learning on X-ray CT. Official first full scroll, https://scrollprize.org/firstscroll, read the same day: PHerc. 1667, announced 25 June 2026, about 22 columns over roughly 1.4 m, transcribed and reviewed by papyrologists, from phase-contrast X-ray microtomography, virtual unwrapping and ink detection. The page says hundreds of rolls remain sealed. The technical account of 1667 is arXiv:2606.29085, already in the registry. An ink prediction is not that transcription. (Sourced fact)

**Opened fragments can show carbon ink in infrared, without any CT.** Tournié et al., Science Advances 5: eaav8936 (4 Oct 2019), https://doi.org/10.1126/sciadv.aav8936. Shortwave infrared hyperspectral imaging (1000 to 2500 nm) on opened, board-mounted PHerc. 1691/1021 recovered Greek on the hidden reverse and improved the front relative to 950 nm imaging. This needs the fragment in front of the camera. (Sourced fact)

**Pulsed thermography also needs the fragment.** Ceccarelli et al., Scientific Reports 15:34466 (8 Oct 2025), https://doi.org/10.1038/s41598-025-19911-w. Flash lamps and a mid-wave infrared camera, in reflection, on supported opened pieces (PHerc. 1018, 1691/1021, 1780 and 1025). The abstract says the method reveals writing almost not discernible to the naked eye. It does not read a sealed roll and it is not a reprocessing of an existing CT volume. Surface shape can distort the text. (Sourced fact)

**Fine surface relief is a third route, only on opened papyrus and only at about 1 micrometre.** Angelotti, Nicolardi, Henderson and Seales, arXiv:2603.27698 (29 Mar 2026), already in the registry. Profilometry, not CT. At several micrometres the relief signal collapses.

## Measuring what the ink is

**Some opened Herculaneum fragments contain a lot of lead in the ink.** Brun et al., PNAS 113:3751 (21 Mar 2016), https://doi.org/10.1073/pnas.1519958113. Two nearly flat Paris fragments. Reported lead about 84 ± 5 and 16 µg/cm², which they argue is too high for casual contamination. A follow-up, Tack et al., Scientific Reports 6:20763 (8 Feb 2016), https://doi.org/10.1038/srep20763, maps and speciates that lead. This is chemistry on opened pieces. It does not show that any named sealed roll is leaded. (Sourced fact)

**A modern replica can make leaded carbon ink obvious in CT.** Seiler et al., PLOS ONE 21(9): e0353485 (Sep 2026), already in the registry. Lampblack spiked with lead, then carbonized. Leaded letters were much brighter than papyrus, down to about 25 µg/cm². They propose handheld XRF to choose which real scrolls to scan. The replica is not an ancient roll. (Sourced fact)

**En-Gedi is burned parchment with metal ink, not a Herculaneum papyrus.** Seales et al., Science Advances 2: e1601247 (21 Sep 2016), https://doi.org/10.1126/sciadv.1601247. Virtual unwrapping of a synagogue scroll charred about 600 CE produced a papyrologist-usable image of Leviticus. The ink shows as bright voxels, the metal-ink case. Success there does not mean carbon-only Herculaneum ink will look the same. (Sourced fact)

## What an existing absorption CT volume can and cannot do

Learned detection of a subtle carbon-ink signature, as Parker proposed and as the 2024 challenge used on X-ray CT, is the route that does not need a new visit to the object. It still needs a volume that captured that signature, a surface, and a check that can fail. It does not identify letters by itself.

These need the object, or a new scan, and cannot be run on an absorption volume we already have: XRF, shortwave infrared, pulsed thermography, surface profilometry, and phase-contrast tomography. A phase-contrast result does not transfer to a different beamline by reprocessing.

No entry above is a claim that carbon ink has been chemically separated from charred papyrus as a recovered pigment. The demonstrated recoveries are images of writing, or elemental maps of ink that is still on the fragment.

## Already in the 7 October registry

Surface topography, the 1667 unwrapping paper, EduceLab-Scrolls, the unsupervised texture ink score on PHerc. 172, and the leaded-replica paper stay in [`../papers.json`](../papers.json). This note adds the primary sources that were only mentioned or were easy to confuse with them.
