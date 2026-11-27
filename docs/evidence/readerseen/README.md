# Pinned source copies for kit readerseen

Copies of three published files, fetched 27 Nov 2026, that `python -m kit.readerseen build` reads to make `kit/data/readerseen.json`. Metadata only; no label, CT, preview, mesh or map. Each keeps its own terms.

- `reader-v3-train_config.json`: https://raw.githubusercontent.com/DomRusso2/reader-v3/4a9f1c633d2f30d9b522922ec1cb52c082013183/train_config.json (MIT repository), sha256 `2d71d6d54cc975e4ab25c0c8a789bde5ab18879eaf9f2095e849526b29e10661`.
- `reader-v2-train_config.json`: https://huggingface.co/domenicor046/reader-v2/resolve/72633d8aa6d40e9e737ccea4c9928fbc624dab45/train_config.json, sha256 `a69e9cf23263d4b17a85f05501333408f923f67f65b6f4ebc6c4539ceb1e81ec`.
- `ink_9um-README.md`: https://huggingface.co/buckets/scrollprize/datasets/resolve/ink_9um/README.md (Vesuvius Challenge), sha256 `c9a88ff970594fcef3788eb588bb75dbbd0e6436f4812f89074e26c0d9fef7a5`.

Rebuild the registry: `python -m kit.readerseen build`; check it: `python -m kit.readerseen verify`.
