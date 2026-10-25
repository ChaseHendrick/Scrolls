# Public label pull, before and after (25 October 2026)

Times one ink label store from the organizers' public Hugging Face bucket `scrollprize/datasets` two ways, one after the other: a plain download of every file in one `download_bucket_files` call, and `kit.hfpull`, which downloads each distinct file once and copies the rest. It then compares the two folders file by file. Public data, no token, no cost.

```bash
python3 -m venv .hub && .hub/bin/pip install "huggingface_hub>=1.33"
.hub/bin/python scripts/experiments/2026-10-25-label-pull/labelpull.py \
    ink_9um/labels/aligned-scrollprizeorg-21slices/pherc0139-w035 /tmp/labelpull
```

Result on 25 Oct 2026, 4-core Claude cloud container behind an HTTPS proxy, `huggingface_hub` 2.3.0, anonymous (Measurement, one run):

```
{"store": "ink_9um/labels/aligned-scrollprizeorg-21slices/pherc0139-w035", "files": 3606, "before_s": 61.7, "after_s": 5.0, "downloaded": 175, "identical": true}
```

Why it helps: the Hub serves bucket files at a roughly fixed rate per request whatever their size, and these zarr v2 label stores are mostly copies of one empty chunk (175 distinct contents among 3,606 files here), so the request count is the cost. Anonymous requests share a lower rate limit than requests with a token; a listing that hits it waits and retries (`HTTP Error 429`).

Tool page: [`docs/tools/hfpull.md`](../../../docs/tools/hfpull.md).
