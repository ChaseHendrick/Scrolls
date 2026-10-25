# AutoPipeline 0.1.8: Reader V3 as the default reader

This package follows AutoPipeline 0.1.7 at public commit `24572e6203bafa67de1611bcd31b9edebe2c078e`. Earlier released branches and tags stay unchanged. This is a change of default model and the code around it. It is not a new ink-accuracy result or a reading, and every map the pipeline makes is model output.

## Reader V3 is the default reader

`ink.models` now defaults to `["reader-v3"]`: Domenico Russo's [Reader V3](https://huggingface.co/domenicor046/reader-v3) (MIT, file `reader-v3.pth`, sha256 `ea405417450abd8ace1b8ff79ebce3adb646c5e48ab95da46844d77efe984d8a`), in place of his Reader v2, the default since 0.1.3. Reader V3 is Reader v2 continued on 256 px and then 384 px tiles, on the same data, and it keeps the `ink_9um` checkpoint format. `reader-v3` joins the models kit can fetch: `fetch_model` downloads it and checks its sha256, and villa's flat ink inference runs it tile by tile as it runs Reader v2, at the patch size its config names (17 x 384 x 384, stride 192 at villa's overlap 0.5; Reader v2 and `ink_9um` use 128 px).

Why the change: Reader V3 is the newest release of the reader family AutoPipeline already used. No rule fixed in advance chose it, and this release makes no claim that it reads ink better than Reader v2. Its author reports fewer false ink marks on blank papyrus (Community report, the model's README). Its author also benchmarked PHerc0841 while choosing its recipe, so PHerc0841 scores may favor it. A plan that names `"models": ["reader-v2"]` keeps the earlier default.

## The built-in koine route is now `reader-v3-koine`

0.1.6 added Reader V3 as a built-in model named `reader-v3`, run through villa's koine inference in the ink Python (the engine of the Crackle Check Space). It is now `reader-v3-koine`, with the same behavior: it needs torch, torchvision, monai, timm and einops in `KIT_INK_PYTHON`, and it reads the whole render into memory. The name `reader-v3` now means the fetchable model above.

## The ink Space

The ink Space source in `space/` runs Reader V3 in place of `ink_9um` seed 42. It sizes its crops for 384 px patches: uploads are 384 to 768 px a side (128 to 768 before), and each run asks for 28 GPU seconds. Its sample notes say what each segment is to Reader V3: Reader V3, Reader v2 and `ink_9um` were not trained on PHerc0841, but Reader V3's author benchmarked PHerc0841; PHerc0139 w035 and w045 are training data. The page shows a Connect your tool panel when `connect.html` is uploaded beside it.

A check that could fail: on a 4-core CPU, the Space's own code at villa `e0bbb8b` made Reader V3's maps of the PHerc0841 w00 and auto-grown 896 sample crops, and their AUCs (0.9414 forward and 0.6621 reversed; 0.8390 and 0.5447) equal to four decimals those of an earlier run of the same checkpoint through villa's flat inference on the same crops. These crops were chosen with the labels and scored before, so they are development numbers, not a test.

## Changed behavior

- A plan made by 0.1.7 or earlier without `ink.models` used Reader v2; a new plan uses Reader V3, so its digest differs.
- A plan that names `reader-v3` now runs villa's flat inference of the checkpoint; name `reader-v3-koine` for the koine route.

## Package

`kit/overlap.py` gains `union_area`, which counts each piece of papyrus once across several traces (points within 30 um of an earlier trace count once, well under a sheet pitch), for reporting beside the plain sum of trace areas. Nothing in this package calls it yet. Version metadata changes from 0.1.7 to 0.1.8. The Docker image was not rebuilt for this version. This package does not assert a Progress Prize form submission or award.
