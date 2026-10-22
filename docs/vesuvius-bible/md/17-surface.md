<a id="ch-surface"></a>

# Surface Prediction {#ch-surface}

> **Chapter summary.** Surface prediction labels each voxel as papyrus recto surface or background, producing the cue that meshing follows. The standard architecture is a 3D U-Net, and since the 2025 to 2026 Kaggle competition, nnU-Net ensembles trained for very long schedules. Predictions are not final geometry: holes, mergers and sheet switches remain, and approximate training labels are now a main bottleneck.

## The task

"A common starting point for surface localization is semantic segmentation: assigning a class label to every voxel: either it's the recto surface of the papyrus, or the 'background'" [VC-OpenProblems2026]. The **recto** is the written surface with horizontal fibers, "always rolled facing inward, toward the center of the scroll"; the **verso** is the back, where fibers run vertically [VC-OpenProblems2026].

The output is "a dense 3D prediction that later steps can use as geometric cues", not "a finished scroll surface" [VC-OpenProblems2026].

## Architectures

- **U-Net and 3D U-Net.** Encoder-decoder convolutional networks for dense segmentation [Ronneberger2015] [Cicek2016]. The 3D U-Net "learns local and contextual patterns in the CT data and produces a voxelwise surface probability" [VC-OpenProblems2026].
- **nnU-Net.** "A self-configuring 3D U-Net framework that automatically adapts its own architecture and training pipeline to a given dataset's geometry and voxel spacing" [VC-OpenProblems2026] [Isensee2021].

Two released checkpoints "anchor the current pipeline": *surface_recto_3dunet*, used in the pipeline of the PHerc. 1667 paper, and *surface_m7_nnunet*, a component of the first-place Kaggle solution [VC-OpenProblems2026].

## The Kaggle surface-detection competition

- **Task:** "Detect the papyrus surface inside 3D CT scans" from CT chunks and binary masks of smoothed sheet positions [VC-KaggleSurface].
- **Metric:** "a topology-aware linear blend rewarding both voxel accuracy and surface connectivity (no gaps, holes, sheet-switches or mergers)" [VC-KaggleSurface].
- **Prizes:** $100,000, doubled to $200,000 [VC-Scroll4Letters]; awarded March 2026 ([Chapter 13](13-2026.md#ch-2026)).
- **What won:** "take an off-the-shelf nnU-Net model configured for a couple of patch sizes, train it for a very long time (well over the default 1,000 epochs), and average their predictions together" [VC-OpenProblems2026]. "Almost all of the top 10 submissions used large ensembles of our baseline, a ResEncUNet trained with the nn-UNet framework", some training "for more than 4,000 epochs", with post-processing against holes [VC-WeAreCooking]. The fifth-place write-up used a distance transform rather than binary segmentation, which the challenge highlights as worth investigating [VC-OpenProblems2026].

The challenge then planned to retrain "using a combination of the best shared techniques, but this time on our 2.4 um high resolution dataset" [VC-WeAreCooking].

## Other predicted fields

The Lasagna optimizer ([Chapter 18](18-tracing.md#ch-tracing)) needs richer fields [VC-OpenProblems2026]:

- **Normals.** "A normal is simply a vector perpendicular to a surface"; a coarse 3D field of them is a **normal grid**, built by *vc_gen_normalgrids*. A U-Net also predicts a dense normal volume.
- **Fractional winding position** and **gradient magnitude.** A second U-Net predicts, for each voxel, "how much further out in the scroll do we get, moving from one side of this voxel to the other point, expressed as a fraction of one full winding". The field is built from distance transforms to sheet skeletons and normalized into a monotone field; its gradient magnitude measures local winding density: "High gradient magnitude means sheets are packed tightly together locally; low means they're far apart."
- **Fibers.** A checkpoint *fiber_hz_vt* is "an nnUNet model trained on 'horizontal/vertical' fibers manually traced by annotators on the older 7.91 µm scans" in WebKnossos [VC-OpenProblems2026] [Boergens2017].

## Why predictions are not geometry

"Dense predictions often contain holes, local deviations, false positives, or accidental mergers between nearby layers. In a normal image/volume segmentation task, a small local error may be tolerable. Here, a small local error can send a traced mesh onto the wrong wrap entirely, with no easy way to recover" [VC-OpenProblems2026]. In June 2026 the team reported that surface predictions "disappear and barely make sense" in the hardest spots, and that the team was "close to saturating the performance of models trained on the approximate surface labels our annotators can produce" [VC-HardParts].

## Label quality

"Machine learning needs labels. For surface models, those labels often come from human-generated meshes or annotations: enormously valuable, but approximate. They may wiggle. They may drift slightly off the true surface. They may avoid the most ambiguous regions" [VC-OpenProblems2026]. The document calls label quality "one of the main unwrapping bottlenecks" and suggests two directions:

- **Label snapping:** "using the raw CT signal and local geometry to move approximate labels back onto the most plausible papyrus surface / fiber".
- **Active learning:** the model identifies the most uncertain or valuable regions "and asks humans to correct only those".

Its conclusion: "a smaller set of precise labels in hard regions may be more useful than a larger set of approximate labels in easy regions" [VC-OpenProblems2026]. A 2026 progress prize rewarded label refinement with nnInteractive (Benjamin Hamm), and another a trained model that grows a single sheet from a seed together with harder training data (Mihajlo Nestorović) [VC-Winners].

## Self-supervised features

Sean Johnson adapted Meta's DINO [Caron2021] to full volumes ("DINO 3D") [VC-WeAreCooking]. The implementation, *dinovol*, has released checkpoints, and a version fine-tuned with supervised contrastive learning on three classes (air, fiber, ignore) on the PHerc. Paris 4 2.4 µm scan guides a background and fiber segmentation model, *fiber_dinoguided_2class* [VC-OpenProblems2026]. "The future likely lies in training self-supervised methods to extract relevant features without (or with minimal) annotation" [VC-HardParts].
