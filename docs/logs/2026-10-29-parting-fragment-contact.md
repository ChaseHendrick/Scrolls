# Parting: telling touching layers apart on fragments it never saw (29 October 2026)

**Result (Model output).** Where two papyrus layers lie 3 to 8 voxels apart, Parting told a point on the same layer from a point on the next layer better than the dinovol features it starts from, in a test fixed before any CT of the object was read: touching AUC **0.895** against **0.839** for base dinovol's token cosine, a gain of **+0.056** (2.5 % bootstrap bound **+0.037**), on 150 touching sites over 5 layer pairs of PHercParis1Fr34. The preregistered bar was a gain of at least +0.05 with its 2.5 % bound above 0, so the test passed. It is one pass in three fragments tried: the first, on a fragment of PHerc1667, missed the bar (+0.045), and the third, on a fragment of PHerc. Paris 2, missed it too (+0.010), where base dinovol alone already scored 0.965. Where the layers are fused, under 3 voxels apart, it adds little.

Parting reads model features of the scan; it does not read ink or text, and nothing here is a reading of a scroll.

## What Parting is

Parting is a contact classifier. Where two layers of papyrus touch, a tracer can hop from one layer to the next (a sheet switch). Parting takes a point `a` on one layer, with its sheet normal, and a candidate point, and scores how likely the candidate is to lie on `a`'s layer. It votes gradient boosting and a one-layer MLP over features of the two points: the tokens of the Vesuvius Challenge's base dinovol encoder ([`scrollprize/dinovol_ps8_9.6um_101626`](https://huggingface.co/scrollprize/dinovol_ps8_9.6um_101626), `teacher_305k.pt`) at both points and their similarity along the line between them, CT profiles along each point's normal and along that line, and base dinovol's own token cosine. It was trained on contact sites built from the published hand-traced windings of PHerc0139 and PHerc0172.

Code status (updated 30 October 2026): Parting's code is released under Apache-2.0, with its own [tool page](../tools/parting.md), and the trained model file used in every test here is on Hugging Face as [`SharpMeow/parting-v1`](https://huggingface.co/SharpMeow/parting-v1) (CC BY-NC 4.0). This page is the public record of the test.

## The test

- **Object.** PHercParis1Fr34 (Frag3 in the open data), fragment 34 of PHerc. Paris 1, a flat stack of layers ([open data](https://dl.ash2txt.org/fragments/Frag3/PHercParis1Fr34.volpkg/)). Parting never trained on PHerc. Paris 1 or on any fragment (checked in its training record, which is in our private repository). Base dinovol's checkpoint config lists 39 pretraining volumes, all scroll scans, none of them PHerc. Paris 1 or a fragment (Sourced fact, the checkpoint's embedded config; that the weights trained on exactly that list is an Interpretation).
- **Truth.** The six layer segments traced by the Vesuvius Challenge team in October 2024 (`paths/` in the volpkg), read as ordered pointsets, ordered by geometry into five consecutive layer pairs. Points where two traces cross were found from the geometry and every site was kept at least 16 voxels away from them, because a crossing trace may have jumped layers.
- **Sites.** A site is a point `a` on one layer, a second point on the same layer and a point on the next layer, both at the same distance from `a`. Touching sites have both gaps 3 to 8 voxels; 30 per pair, 150 in all, drawn once with a fixed seed from the geometry only.
- **Scan.** The organizers' standardized 54 keV, 3.24 um volume, box-averaged to 7.91 um so the windows match the voxel size the model was built for.
- **Comparison.** Base dinovol's raw token cosine between the two points, on the same sites. The claim is the gain over it, not the absolute AUC.
- **Rule, fixed before any CT value was read** (frozen 29 October 2026 about 20:50 UTC, read once about 21:10 UTC). PASS needs a touching AUC of at least 0.75, a gain over base dinovol of at least +0.05, and the 2.5 % bound of the gain above 0, from 20,000 resamples of layer pairs. VOID if fewer than 100 touching sites or 5 pairs, if base dinovol scores under 0.85 on apart sites (8 to 16 voxels, the pipeline check), or if the mean AUC of 1,000 shuffled-label permutations falls outside 0.5 plus or minus 3 standard errors.

## Numbers (Model output)

| | Value |
| --- | --- |
| Parting, touching AUC (2.5 % bound) | 0.8952 (0.8452) |
| Base dinovol token cosine, touching AUC | 0.8392 |
| Gain (2.5 % bound) | +0.0560 (+0.0368) |
| Touching sites, layer pairs | 150, 5 |
| Shuffled-label control, mean of 1,000 | 0.500 (band 0.497 to 0.503) |
| Pipeline check, base dinovol on 75 apart sites | 0.944 |
| Verdict | PASS |

Reported, not judged: the gain was positive on all five pairs (+0.026, +0.071, +0.026, +0.053, +0.023), but three of the five gained less than +0.05 alone; the pooled gain and its bound carry the result. Without the pair that held most crossings the gain was +0.057. One feature Job on Hugging Face (rtx-pro-6000, 425 s, 0.37 USD) made the features for all sites.

## The earlier miss, disclosed

The same model, rule and bar were first tried on PHerc1667Cr1Fr3 (Frag5 in the open data), a crust fragment of PHerc1667, on 29 October 2026: 0.960 against base dinovol's 0.915 on 203 touching sites over 7 pairs, a gain of +0.045 (bound +0.020), **FAIL** by the margin. That result stands and was not rerun. Frag3 was then tested once as the second object tried, with nothing in the method changed. One control-validity gate changed before the freeze: the single shuffled-label check became the mean of 1,000 permutations, because one permutation voids a sound run of this size by chance about 15 % of the time. Under the old single check Parting's run also passes (0.541, inside 0.45 to 0.55).

## The later miss, disclosed

After the Frag3 pass, the same frozen model, comparator, rule and bar were tested once on a third fragment, PHercParis2Fr143 (Frag2 in the open data, fragment 143 of PHerc. Paris 2), frozen on 29 October 2026 before any CT value was read and read once about 23:20 UTC: **FAIL**. Parting scored a touching AUC of 0.9754 (2.5 % bound 0.9615) against 0.9651 for base dinovol's token cosine, a gain of +0.0103 (2.5 % bound -0.0005), on 270 touching sites over 9 layer pairs. The controls held: the shuffled-label mean was 0.50057 and the pipeline check, base dinovol on 135 apart sites, 0.9988. Per pair the gain ran from -0.029 to +0.030. The Job cost 0.64 USD. Interpretation: base dinovol was already close to a perfect score there, so even a perfect Parting score could have gained only +0.035, under the +0.05 bar. That result stands and is not rerun.

## Limits

- **Fused layers are not solved.** On 38 fused sites (gaps under 3 voxels) Parting scored 0.633 against 0.611 for base dinovol, a gain of +0.022, not judged. Only 3 touching sites had both gaps at 4 voxels or less, too few to read.
- **One pass in three fragments.** One PASS (Frag3) and two misses (Frag5 by the margin, Frag2 with base dinovol near its ceiling). On Frag3, five layer pairs is the floor the rule allows, so the bound is coarse. Before the read we put the chance of a PASS at about 0.3 to 0.4 (Interpretation).
- **Room for a gain.** Base dinovol was weaker on Frag3 than on Frag5 and Frag2 (0.839 against 0.915 and 0.965), which left more room for a gain; the bar of +0.05 can only be met where dinovol leaves that much room (Interpretation).
- **A resampled scan is not a native 7.91 um scan.** Both arms saw the same windows, so the comparison is fair, but the absolute AUCs may differ on a native scan.
- **Team traces.** Layer segments can hold local jumps that geometry cannot find; the crossing rule removes only places where two traces actually cross.

## Data and credits

Scan and layer segments: Vesuvius Challenge open data, CC BY-NC 4.0. Base dinovol: the Vesuvius Challenge (`scrollprize/dinovol_ps8_9.6um_101626`). Training windings: the published hand-traced windings of PHerc0139 and PHerc0172.
