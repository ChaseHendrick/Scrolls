# Community and People {#ch-community}

> **Chapter summary.** The Vesuvius Challenge is a hybrid of open competition and in-house work: a Discord community, open-source progress prizes, a paid segmentation (annotation) team from 2023, an in-house research team from 2025, a papyrology team, and partners at libraries and synchrotrons. The organizers credit five things for the 2023 success: an inspiring goal, a solid starting point, blending competition with cooperation, hiring segmenters, and many small breakthroughs. This chapter describes the structure, the people named in public sources, and the community's working norms.

## How the community is organized

| Group | Role | Source |
|---|---|---|
| Organizers | Scroll Prize, Inc.; founders Nat Friedman, Daniel Gross, Brent Seales | [VC-GrandPrize] [VC-FAQ] |
| EduceLab (University of Kentucky) | scanning, Volume Cartographer, ink-id, EduceLab-Scrolls dataset | [VC-GrandPrize] [VC-Data] |
| Segmentation (annotation) team | hired in early summer 2023 to trace papyrus and open-source segments; in early 2024 Ben Kyles, David Josey and Konrad Rosenberg | [VC-GrandPrize] |
| Technical review team | reproduces submissions | [VC-GrandPrize] |
| Research and platform teams | hired from 2025; members forfeit prize eligibility | [VC-Hiring2025] |
| Papyrology team | reviews readings independently and blind; led by Federica Nicolardi in 2025 to 2026 | [VC-FirstTitle] [VC-HardParts] |
| Contestants and contributors | Kaggle teams, progress-prize winners, tool builders | [VC-Winners] |
| Partners | Institut de France, Biblioteca Nazionale di Napoli, Bodleian Libraries, Diamond Light Source, ESRF, the Getty, Kaggle, AWS Open Data | [VC-GrandPrize] [VC-Scroll5] [VC-FirstScroll] [VC-WeAreCooking] |

## What the organizers say worked

After the 2023 Grand Prize, the organizers listed what they believed was important [VC-GrandPrize]:

1. **"An inspiring goal and a clear target."** The unusual goal "drew more press and donations early on" and "attracted an intrinsically motivated community".
2. **"A solid starting point."** Brent Seales's team "spent two decades making the first scroll scans, building Volume Cartographer, demonstrating the first success in virtual unwrapping, and proving that Herculaneum ink can be detected in CT".
3. **"Blending competition and cooperation."** A grand prize alone "would suffer from information 'hoarding'". Progress prizes "often in the $1,000-10,000 range" every two months, conditional on open-sourcing, "leveled up" the community, let winners reinvest in equipment or time, and helped people form teams.
4. **"Hiring an in-house segmentation team."** The "(then somewhat controversial)" decision to pay labellers, because segment quality was hard to judge before ink detection worked, labelling is tedious with "a long learning curve", and prize feedback loops are slow. "We were not dogmatically attached to just being referees; we were willing to run out onto the field and kick the ball a little."
5. **"Maximizing surface area for breakthroughs."** "Even ideas and discoveries landing outside the critical path were still important, because a massive search space had to be exhausted."

At the start, "most of us estimated that we had a less than 30% probability of success within the year" [VC-GrandPrize].

## Size and activity

Systematic membership counts are not published in the sources consulted. Indicators:

| Indicator | Value | Date | Source |
|---|---|---|---|
| Discord members | more than 400 | first week, March 2023 | [VC-Launch] |
| Data registrations | more than 300 | first week, March 2023 | [VC-Launch] |
| Kaggle contestants with submissions | almost 100 | first week, March 2023 | [VC-Launch] |
| Kaggle ink competition | "hundreds of teams" | 2023 | [VC-GrandPrize] |
| Segmented area | almost 200 cm2; more than 600 cm2; more than 1,000 cm2 | May, August, October 2023 | [VC-SignsOfProgress] [VC-4thFragment] [VC-SegTooling2Winners] |
| Progress-prize submissions | 11 | March 2026 | [VC-WeAreCooking] |
| Progress-prize submissions | 58, of which 13 awarded | July 2026 | [VC-July2026] |
| Award entries in the winners list | 54, 92, 16, 71 | 2023, 2024, 2025, 2026 | [VC-Winners] |

![Two-panel chart: left, segmented area of Scroll 1 data in 2023 rising from about 200 to over 1,000 square centimetres; right, number of prize awards per year 2023 to 2026.](../figures/charts/community_growth.svg)
*Figure 24.1. Two public indicators of community activity: segmented area reported during 2023 (left) and number of awards per year in the winners list (right). Chart by the editors. Data: data/community_indicators.csv from [VC-SignsOfProgress], [VC-4thFragment], [VC-SegTooling2Winners] and [VC-Winners]. License: CC BY 4.0 (this book).*

## People named in public sources

The list below gives people with a documented public role, in the words of the sources. It is not complete and does not rank contributions.

### Founders and organizers

- **Nat Friedman:** co-founder, "instigator and main sponsor"; announced the 2027 Grand Prize [VC-GP2027].
- **Daniel Gross:** co-founder [VC-GrandPrize].
- **W. Brent Seales:** co-founder; professor at the University of Kentucky whose EduceLab imaged the scrolls in 2019 [VC-FirstLetters] [VC-GrandPrize].
- **Stephen Parsons:** Seales's former graduate student who showed ML ink detection on fragments; dissertation *Hard-Hearted Scrolls* [VC-FirstLetters] [VC-InkTutorial].
- **Seth Parker (C. Seth Parker):** started Volume Cartographer in 2013 [VC-NewScans2023].
- **J. P. Posma:** co-author of the PHerc. 1667 preprint [VC-OpenProblems2026]. The launch newsletter names a "JP" alongside Stephen and Seth in the first Q&A [VC-Launch]; *that this is the same person is assumed, not stated (unverified)*.

### Papyrologists quoted

- **Federica Nicolardi:** papyrology team lead; identified the Theophrastus quotation in PHerc. 172 [VC-Column172] [VC-HardParts].
- **Richard Janko:** commented on rolls without an umbilicus and on the 2023 text [VC-PapyrologyQA] [VC-GrandPrize].
- **Robert (Bob) Fowler:** quoted on the 2023 text [VC-GrandPrize].
- **Daniel Delattre**, **Maria Chiara Robustelli:** readings in PHerc. 172 [VC-Column172].

### Research team and co-authors (2026)

The PHerc. 1667 preprint lists G. Angelotti, S. Parsons, F. Nicolardi, Y. Nader, S. Johnson, D. Josey, P. Henderson, H. Schilling, J. Rudolph, F. McDonald, E. R. Dal Prá, P. Tafforeau, A. Mirone, C. S. Parker, J. P. Posma, B. Kyles, C. Vergara, A. Lavorante, R. Villa, M. C. Robustelli, M. D'Angelo, G. Del Mastro, M. McOsker, K. Fleischer, C. Chapman, N. Friedman and W. B. Seales [VC-OpenProblems2026] [Angelotti2026a]. Paul Tafforeau and Alessandro Mirone are also co-authors of the new-scan dataset citation [VC-Data].

### Prize winners

Grand Prize 2023: Youssef Nader, Luke Farritor, Julian Schilliger. First Ink: Casey Handmer. First Title: Marcel Roth and Micha Nowak. First Letters, PHerc. 343: Erwin Nieuwlaar. Every award is listed in Appendix B [VC-Winners].

## Working norms

The norms below are stated in prize rules and tutorials:

- **Open source to win.** Code must be released under a permissive licence to accept a prize [VC-Prizes].
- **Release early.** Progress prizes favour work "released or open-sourced early", that "actually get used", improves results "on real data", fixes bugs in tools people use, reveals "insightful, actionable" information, and is "well documented" [VC-Prizes].
- **Use community formats.** OME-Zarr or Zarr arrays, tifxyz quadmeshes, triangular meshes [VC-Prizes].
- **Bundle small fixes.** Several small PRs in a month go in one submission [VC-Prizes].
- **Embargo discoveries.** "Do not make your discovery public until the prize is officially announced" [VC-Prizes]; hidden text is not to be published without written approval [VC-FAQ].
- **Register on Discord** before submitting for milestone prizes [VC-Prizes].

## AI in the work

Machine learning is central to the pipeline ([Chapters 17](#ch-surface) and [21](#ch-ink)). Since 2026 the team has also used autonomous agents: "a swarm of automated agents that perform research on ink detection model architectures and training", inspired by an open-source autoresearch project, which found a cross-scroll configuration that nearly doubled validation Dice on PHerc. 1667 [VC-WeAreCooking] [VC-OpenProblems2026]. VC3D has an "agent bridge" that received fixes in a 2026 progress round [VC-Winners].

A broader comparison by the editors' research notes: undeciphered scripts such as Linear A lack a bilingual anchor, so statistical or AI methods "cannot confirm a reading"; the Herculaneum texts are in known languages, so the machine task is recovering ink and letters, not meaning. DeepMind's Ithaca (Greek inscriptions) and Aeneas (Latin inscriptions, *Nature* 2025) propose restorations and parallels that experts then judge [AIChallenges2026]. *These comparisons rest on secondary search summaries and are marked unverified.*
