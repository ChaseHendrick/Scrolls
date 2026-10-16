# Appendix D. Models in the Catalogue {#app-models}

The 13 models listed in the open data catalogue [VC-Catalog] on 15 October 2026. Models published only on Hugging Face (for example ink_9um and ink_canonical_2um) are described in [Chapter 21](#ch-ink). Data: data/catalog_models.csv.

| ID | Name | Date | Architecture | Task | Resolution (µm) | Training dataset | Compatible |
|---|---|---|---|---|---|---|---|
| 20230702185753 | 20230702185753 | 2023-07-02 | timesformer | ink-detection | 7.0 to 10.0 | timesformer_GP_scroll1 | PHercParis4 |
| 20250701154204 | 20250701154204-surface-recto-090 | 2025-07-01 | nnunet | surface-prediction |  | Dataset090_CEDCrops |  |
| 20250713185324 | 20250713185324-timesformer_scroll5_july_retreat | 2025-07-13 | timesformer | ink-detection | 7.0 to 10.0 | timesformer_scroll5_july_retreat | PHerc0172 |
| 20250807020208 | 20250807020208-canonical-2um | 2025-08-07 | resnet50 | ink-detection | 2.0 to 3.0 | canonical_2um_20250807020208 | none |
| 20251222202946 | 20251222202946-timesformer_scroll5_november19 | 2025-12-22 | timesformer | ink-detection | 7.0 to 10.0 | timesformer_scroll5_november19 | PHerc0172 |
| 20260413222639 | 20260413222639-surface-m7 | 2026-04-13 | nnunet | surface-prediction |  | Dataset100_VesuviusSurface |  |
| 20260413141734 | 20260413141734-surface-recto-2um-ps256 | 2026-04-13 | vesuvius-unet | surface-prediction |  |  |  |
| 20260417190342 | 20260417190342-new_canon_autoresearch_recipe | 2026-04-17 | resnet3d-152-3d-decoder | ink-detection | 2.0 to 3.0 | new_canon_autoresearch_recipe | PHerc0009B;PHerc0139;PHerc0343P;PHerc0500P2;PHerc0814;PHerc0841;PHerc1667;PHercParis4 |
| 20260419180421 | 20260419180421-lasagna | 2026-04-19 | unet | lasagna |  | scrollprize/lasagna |  |
| 20260428123845 | 20260428123845-v3-78k-fullsup | 2026-04-28 | dino3d | ink-detection-3d | 2.0 to 3.0 | dino_guided_v3_78k_fullsup |  |
| 20260709123958 | 20260709123958-mrg20736-1um-s1z2 | 2026-07-09 | resnet3d-152 | ink-detection | 1.0 to 1.5 | mrg20736_1um_s1z2 | PHerc0139;PHerc0814;PHerc1667;PHercMANBp;PHercParis4 |
| 20260801084232 | 20260801084232-lasagna | 2026-08-01 | fiber3d/unet | lasagna |  |  |  |
| 20260915212757 | 20260915212757-lasagna | 2026-09-15 | fiber3d/unet | lasagna |  | scrollprize/lasagna-fiber |  |
