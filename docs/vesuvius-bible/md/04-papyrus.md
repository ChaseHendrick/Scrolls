<a id="ch-papyrus"></a>

# Papyrus: from Plant to Roll {#ch-papyrus}

> **Chapter summary.** Papyrus is made from the pith of the sedge *Cyperus papyrus*, cut into strips, laid in two layers at right angles, pressed and dried. Sheets were glued edge to edge into rolls. Carbonization at Herculaneum shrank each sheet to about 0.15 mm, and the fiber structure that survives is the main thing that CT sees. This chapter collects the measured facts about the plant, its manufacture and the physical structure of a carbonized roll, with the voxel arithmetic that links them to scanning.

Throughout this chapter, numbers are labeled with their condition: **fresh** (living plant), **replica** (modern experimental papyrus), **ancient** (surviving ancient papyri) or **carbonized** (Herculaneum material). They should not be mixed without care.

## The plant

*Cyperus papyrus* L. is a sedge (family Cyperaceae), native to central and tropical Africa including Madagascar. It was cultivated in Egypt from ancient times and is sometimes naturalized around the Mediterranean; it has almost disappeared from the lower Nile [Vaughan2011]. It grows from sea level to about 2,500 m and uses C4 photosynthesis [Vaughan2011]. Pliny the Elder places it in the marshes of Egypt or in still Nile water no deeper than two cubits [Pliny-NH13, 13.71]. The best-known European stands are in Sicily, where modern papyrus making at Siracusa underlies a widely used replica method; whether the Sicilian plants are native or introduced is **unverified** in the sources consulted [Waly2001].

> **Photograph (not stored in git; see the caption for source and license):** Cyperus papyrus plants with tall green stems and umbrella-like flower heads.
*Figure 4.1. Cyperus papyrus. Photo: Krzysztof Ziarnek (Kenraiz), via Wikimedia Commons. License: CC BY-SA 4.0. <https://commons.wikimedia.org/wiki/File:Cyperus_papyrus_kz07.jpg>*

| Quantity | Value | Condition | Source |
|---|---|---|---|
| Culm (stem) height | up to 5 m, exceptionally 9 m | fresh | [Vaughan2011] |
| Culm cross-section | three-sided (trigonous) | fresh | [Vaughan2011] [Pliny-NH13] |
| Stem length according to Pliny | at most 10 cubits | ancient text | [Pliny-NH13] |
| Rhizome thickness | 2 to 6 cm | fresh | [Vaughan2011] |
| Fiber cell length | 1.8 mm (range 1 to 4) | fresh | [Vaughan2011] |
| Fiber cell width | 12 µm (range 8 to 25) | fresh | [Vaughan2011] |
| Vascular bundle spacing | 1.2 mm mean (0.6 to 2.0) | fresh | [Scora1991] |

### The pith

The writing material is made from the pith: a soft tissue of parenchyma surrounding air channels (aerenchyma), crossed lengthwise by stiff fibrovascular bundles. Held up to the light, a finished sheet shows these bundles as dark lines [Vaughan2011]. Lignin sits mainly in the sclerenchyma of the bundles, which are the densest parts of the pith [Bausch2022].

| Component | Value | Source | Note |
|---|---|---|---|
| Lignin in pith | about 16 percent | [Bausch2022] | older values of 47 percent called incorrect |
| Lignin in pith | 15.7 percent of dry mass | [Rosado2021] | |
| Lignin in rind | 27.0 percent of dry mass | [Rosado2021] | |
| Lignin in pith (older handbook) | 24 to 32 percent | [Vaughan2011] | conflicts with the two values above |
| Cellulose in pith | 54 to 68 percent | [Vaughan2011] | |
| Lignin in modern commercial sheets | under 5 percent | [Bausch2022] | removed by alkali and bleach |
| pH of Pliny-type replica sheets | 5.5 to 6.0 | [Bausch2022] | |
| pH of commercial sheets | 7.9 to 9.8 | [Bausch2022] | |

Bausch and colleagues found that ancient papyri dated from 200 BCE to 800 CE contain two to three times more lignin than commercial sheets, some close to fresh pith [Bausch2022]. This matters for scanning: lignified bundles are the stiffest part of the pith, and they are the likeliest to survive carbonization as the long oriented features that CT shows as the papyrus "grid".

## Making a sheet: Pliny's account

Pliny's *Natural History* 13.68 to 89 is the only detailed ancient description of papyrus manufacture [Pliny-NH13]. The key steps, paraphrased from the Latin:

1. **Splitting (13.74).** The stem is split with a point into very thin but as wide as possible strips (*philyrae*); the best come from the center.
2. **Weaving (13.77).** All papyrus is "woven" on a board wetted with Nile water. A lengthwise layer is laid first and trimmed, then a cross layer on top.
3. **Pressing and drying (13.77).** The sheets are pressed and dried in the sun, then joined into a roll, in descending order of quality, never more than twenty to a *scapus*.
4. **Grading (13.78).** Quality is judged by thinness, density, whiteness and smoothness.
5. **Finishing (13.81 to 82).** Roughness is smoothed with ivory or a shell, though then the letters may flake; a polished sheet absorbs less. Common paste is made from fine flour, boiling water and a little vinegar, or from leavened bread; the sheet is beaten thin with a mallet, coated with paste and beaten again.

### Pliny's grades

| Grade | Width in Pliny | Converted (18.5 mm per digit) |
|---|---|---|
| Augusta (best) | 13 digits | about 24.1 cm |
| hieratica | 11 digits | about 20.4 cm |
| Fanniana | 10 digits | about 18.5 cm |
| amphitheatrica | 9 digits | about 16.7 cm |
| Saitica | fewer | not given |
| emporitica | at most 6 digits | at most about 11.1 cm |
| Claudia (after reform) | 1 foot | about 29.6 cm |
| macrocollum | 1 cubit | not converted |

Source: [Pliny-NH13], conversion using the standard Roman digit [WP-RomanUnits]. **Caution:** whether these widths refer to the strip, the finished sheet or the roll height, and what exactly a *scapus* is, are long-standing debates in the specialist literature (Lewis 1974; Hendriks 1980), which were not consulted directly for this book. The converted centimeters are arithmetic, not measurements.

> **Photograph (not stored in git; see the caption for source and license):** A modern demonstration of papyrus making: strips laid in two layers on a board.
*Figure 4.2. Making papyrus: strips laid in crossed layers before pressing (modern demonstration). Photo: FrogUnderALilyPad, via Wikimedia Commons. License: CC BY-SA 4.0. <https://commons.wikimedia.org/wiki/File:Making_papyrus.jpg>*

## Modern reconstructions

Experimental papyrus making has tested Pliny's account:

- **Scora and Scora (1991)** cut slices about 2 mm thick from the lowest 30 cm of the stem, overlapped adjacent strips by 1 to 2 mm, and found that pressing raised the density of fibrovascular bundles more than sixfold. The plant's own juices bonded the two layers; paste was needed only to join sheets, with about 1 cm of overlap [Scora1991].
- **Ragab (1980)** argued that strips bond by physical interlocking of cells under pressure; Scora and Scora saw no such interlocking [Scora1991].
- **Wallert (1989)** compared strips cut across the stem with a continuous peeling method and showed the two leave different surface textures [Wallert1989].
- **Basile and Di Natale** (Siracusa) developed a replica method; sheets made by it reached 0.50 mm thick [Waly2001].
- **Bausch and colleagues (2022)** made "Pliny-type" sheets from stalks 2 to 3 cm thick, cut into slices 2 to 4 mm thick, soaked for 10 minutes and pressed for two days, and compared them with alkali-cooked commercial sheets [Bausch2022].

### What holds the layers together?

| Position | Source |
|---|---|
| Muddy Nile water acts as glue; flour or bread paste for joining | [Pliny-NH13] 13.77, 13.82 |
| The plant's natural starch acts as paste | [Mocella2015] |
| No starch detected; natural mucilage bonds the layers; paste only at sheet joins | [Scora1991] |
| Physical interlocking of cells | Ragab 1980, via [Scora1991] |

This disagreement is unresolved. For CT the question matters because a paste layer at a sheet join could add a thin interface of different density.

## Recto, verso and the roll

A sheet consists of two layers of strips at right angles [Bonnerot-CSMC] [Scora1991] [Parsons2023]. The side with fibers running horizontally (parallel to the length of the roll) is the **recto**. It was written first and rolled inward; the **verso** shows vertical fibers [VC-OpenProblems2026] [Bonnerot-CSMC]. Text runs in columns along the horizontal fibers [Bukreeva2016].

Sheets were joined into a roll by overlapping and gluing their edges:

- a **kollema** (plural kollemata) is one sheet within a roll; the **kollesis** is the glued join;
- the **protokollon** is the first sheet, often turned so its fibers run vertically on the inside, protecting the start of the roll;
- the **eschatokollion** is the last sheet;
- an **agraphon** is an unwritten stretch, used for the blank spaces at the start and end of a roll [Romano2023].

Overlaps at a kollesis are 1 to 2 cm. Joins run in the same direction through a roll, and a standard commercial roll had 20 sheets [UCL-Rolls] [Pliny-NH13]. Fibers are often disturbed at a join, and a vertical crack 1 to 1.5 cm before it is often mistaken for the join itself [Janko-HowTo].

| Roll (Egypt) | Kollema widths | Roll height | Source |
|---|---|---|---|
| P.Lit.Lond. 132 (Hyperides) | 21.1 to 27.5 cm (13 sheets) | 30.5 to 31.0 cm | [Johnson-Bookrolls] |
| P.Berol. 16985 (Iliad 21 to 22) | 20.4 to 21.8 cm | 23.6 cm | [Johnson-Bookrolls] |
| P.Berol. 9875 (Timotheus) | 21.2 to 21.9 cm | | [Johnson-Bookrolls] |
| P.Oxy. 223 (Iliad 5) | 21.2 to 24.1 cm | 25.6 cm | [Johnson-Bookrolls] |
| P.Vindob. G 257 (Xenophon) | 22.9 to 25.0 cm | | [Johnson-Bookrolls] |
| P.Lit.Lond. 27 (Iliad 23 to 24) | 11.7 to 25.0 cm | | [Johnson-Bookrolls] |

Johnson's dataset of Greek literary rolls from Egypt gives heights of about 20 to 33 cm and estimated lengths of about 1.2 to 33 m [Johnson-Bookrolls].

## Herculaneum roll formats

| Quantity | Typical value | Source |
|---|---|---|
| Roll height | 19 to 24 cm, mostly 21 to 22 cm | [Papyrology-Compiled] |
| Roll length | about 8 to 16 m; "15 m or more" | [Papyrology-Compiled] [Mocella2015] |
| Lines per column | 20 to 45 | [Papyrology-Compiled] |
| Letters per line | 16 to 40 | [Papyrology-Compiled] |
| Common column width | 5 to 6 cm | Cavallo, via [Capasso-Titoli] |
| Letter height | about 3 mm; 3 to 4 mm | [Mocella2015] [Ceccarelli2025] |
| Heights of unrolled fragments studied by thermography | 14.6 to 20.6 cm | [Ceccarelli2025] |
| Column slant (Maas's law) | up to about 5 degrees, leaning left | [Romano2023] [Ceccarelli2025] |
| PHerc. 1667 (read in 2026) | preserved height about 8 cm; 31 wraps; 22 columns | [Angelotti2026a] |

Here [Papyrology-Compiled] marks values compiled from the published papyrological literature (Cavallo 1983; Capasso; Del Mastro 2014; Janko) that were not re-verified against each primary text for this book. Rows sourced only to it should be checked against those primaries before reuse.

Romano and colleagues found lead-drawn ruling lines by macro X-ray fluorescence in six rolls, in three systems of increasing elaboration: frame lines and a left column edge; lines on both sides of each column and intercolumn; and that system plus a baseline for every line of text [Romano2023]. Guide dots appear in some rolls. Lead along the ruling lines is at most about 8 ng per 250 µm pixel against about 1 ng background [Romano2023].

## Thickness, density and the carbonized sheet

| Quantity | Value | Condition | Source |
|---|---|---|---|
| Single unrolled sheet, PHerc. 164 | about 0.15 mm | carbonized | [Romano2023] |
| Fragments studied by thermography | about 0.15 mm | carbonized | [Ceccarelli2025] |
| Paris fragments "made of different sheets" | about 0.3 mm average | carbonized | [Tack2016] |
| Thickness assumed for ink-detection neighborhoods | 150 µm ("varies considerably") | carbonized | [Parsons2023] |
| Replica sheets (Siracusa method) | up to 0.50 mm | replica | [Waly2001] |
| Pith slices before pressing | 2 to 4 mm; about 2 mm | replica | [Bausch2022] [Scora1991] |
| Bulk density of a whole carbonized roll (5 cm diameter, 20 cm, 141 g) | 0.36 g/cm3 | carbonized | [Tack2016] |
| Fiber ridge width on sheet surface (SEM) | 50 to 200 µm | replica | [Parker2019] |
| Rounded cells between ridges | about 50 to 100 µm | replica | [Parker2019] |

Two to four millimeters of wet pith become a sheet a few tenths of a millimeter thick, consistent with the more than sixfold increase in bundle density on pressing [Scora1991]. A carbonized sheet of about 0.15 mm is thinner than replica sheets of up to 0.5 mm; no source consulted separates shrinkage due to carbonization from original thinness. Carbonization also makes sheets bubble and delaminate, so they can appear to have more layers than they do [Parsons2023], and rolls are crushed, with layers hardest to separate in the innermost windings [Mocella2015].

The 0.36 g/cm3 figure is a whole-roll bulk density that includes the gaps between wraps [Tack2016]. Ink and carbonized papyrus have "almost the same density" [VC-Tutorial5], so absorption contrast between them is very low and phase effects dominate [Angelotti2026a].

> **Photograph (not stored in git; see the caption for source and license):** Scanning electron micrograph of the surface of a papyrus sheet at 100 times magnification, showing crossing fiber bundles.
*Figure 4.3. Scanning electron image of the surface of a (modern) papyrus sheet, 100x. The ridged fiber structure is what CT resolves as the papyrus grid in carbonized rolls. Image: Ckazilek, via Wikimedia Commons. License: CC BY-SA 4.0. <https://commons.wikimedia.org/wiki/File:Scanning_electron_image_of_surface_of_a_papyrus_sheet_-_100x.jpg>*

> **Photograph (not stored in git; see the caption for source and license):** Scanning electron micrograph of a papyrus sheet surface at 1,000 times magnification, showing individual fiber cells.
*Figure 4.4. The same kind of surface at 1,000x, showing individual fiber cells. Image: Ckazilek, via Wikimedia Commons. License: CC BY-SA 4.0. <https://commons.wikimedia.org/wiki/File:Scanning_electron_image_of_surface_of_a_papyrus_sheet_-_1,000x.jpg>*

## Carbonization

Estimates of the thermal history of the papyri differ by method:

| Estimate | Value | Method | Source |
|---|---|---|---|
| Pyroclastic flow at the papyri | about 320 C, "for a few seconds" | cited from earlier work | [Mocella2015] [Ceccarelli2025] |
| Wood charred in place at the villa | 240 to 370 C | charcoal reflectance | [Caricchi2014] |
| Mixed deposits | average about 270 C (190 to 300) | thermal remanent magnetization | [Giordano2018] |
| Unmixed deposits | average 350 C (300 to 440) | same | [Giordano2018] |

Giordano and colleagues also report that the deposits stayed out of thermal equilibrium for more than 24 hours [Giordano2018]. The "few seconds" figure and a deposit that stayed hot for a day do not fit easily together; one reading is that rolls inside rooms or cases saw less heat than open deposits, so local histories varied. No source measures the temperature history of any particular roll.

Bukreeva and colleagues distinguish the amorphous carbon of ink from the ordered carbon fibers of the substrate [Bukreeva2016]. That structural difference, rather than density, is a plausible physical basis for texture contrast between ink and papyrus. Very high resolution scans (0.55 µm) of carbonized fragments show fibers as cell walls around hollow lumens; these graphite-like structures act as tiny refractive lenses and degrade phase contrast, a phenomenon the Vesuvius Challenge calls "compressed-region haze" [VC-OpenProblems2026] [Angelotti2026a] (see [Chapter 7](07-xray.md#ch-xray)).

## Voxel arithmetic

The table below converts physical sizes into voxels for the two voxel sizes most used in the challenge (2.4 µm, ESRF BM18; 7.91 µm, Diamond 2019 scans of Scroll 1). It is arithmetic on the sourced sizes.

| Feature | Physical size | At 2.4 µm | At 7.91 µm | Source of size |
|---|---|---|---|---|
| Ink layer on a phantom | 3 to 5 µm | 1.25 to 2.1 voxels | 0.38 to 0.63 voxels | [Parker2019] |
| Apparent ink deposits (Scroll 1 at 2.4 µm) | 10 to 20 µm | 4.2 to 8.3 voxels | 1.3 to 2.5 voxels | [Angelotti2026a] |
| Fiber cell width | 8 to 25 µm | 3.3 to 10.4 voxels | 1.0 to 3.2 voxels | [Vaughan2011] |
| Fiber ridge | 50 to 200 µm | 21 to 83 voxels | 6.3 to 25 voxels | [Parker2019] |
| Carbonized sheet | 150 µm | 62.5 voxels | 19 voxels | [Romano2023] |
| Letter height | 3 to 4 mm | 1,250 to 1,667 voxels | 379 to 506 voxels | [Ceccarelli2025] |

![Bar chart on a logarithmic scale comparing feature sizes from ink layers to letters with the 2.4 and 7.91 micrometer voxel sizes.](../figures/charts/feature_scales.svg)
*Figure 4.5. Physical feature sizes of papyrus and ink compared with common voxel sizes (log scale). Chart by the editors from the sources in the table above. Data: data/feature_scales.csv. License: CC BY 4.0 (this book).*

The practical lesson: at 7.91 µm a single fiber cell is one to three voxels and the thinnest ink layers are below one voxel, so ink detection at that resolution relies on texture and context rather than resolving the ink itself. At 2.4 µm fibers and apparent ink deposits span several voxels. Chapter 7 returns to the trade-off between resolution, field of view and data volume.
