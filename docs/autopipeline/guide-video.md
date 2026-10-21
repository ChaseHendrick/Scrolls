# AutoPipeline trailer: script, storyboard and shot list

A 60 second trailer for the [AutoPipeline guide](guide.md). It is drawn from a cast file, timed to a score from Chase's Oro synthesizer, and checked against the rules below before anyone posts it. The draft render is kept outside Git: the repository's media rule caps every file under `docs/assets/` at 4 MB, and the draft still has a diagram where the VC3D shots will go.

| Piece | Where |
| --- | --- |
| Cast (every scene, caption and label) | [`scripts/media/captures/autopipeline-trailer.json`](../../scripts/media/captures/autopipeline-trailer.json) |
| Score (96 bpm, 24 bars, D major) | [`scripts/media/captures/autopipeline-trailer.oro.txt`](../../scripts/media/captures/autopipeline-trailer.oro.txt) |
| Frame renderer | [`scripts/media/termcast.py`](../../scripts/media/termcast.py) ([media page](../tools/media.md)) |
| Draft render | Not in Git. Rebuild it with the commands at the end |

## Rules it follows

Each rule carries its source and its claim label ([NOVELTY.md](../NOVELTY.md)).

| Rule | How the trailer meets it | Source |
| --- | --- | --- |
| Open on the result, no logo intro | First frame: the monitor's finished run, with the title caption | Community report: Roy Lee, X, 10 Sep 2025, https://x.com/im_roy_lee/status/1965859119728046433 |
| The first 30 s deliver what the thumbnail promises | By 30 s the viewer has seen the demo pass and a real plan | Sourced fact: YouTube's retention report and its "Intro" metric, https://support.google.com/youtube/answer/9314415 (read 21 Oct 2026) |
| Show a real demo, not a description | Terminal text is pasted from real runs of 0.1.5 on 21 Oct 2026; nothing is typed that was not run | Community report: Ashley Wright, X, 7 Jul 2026, https://x.com/ashley_wright/status/2074478544508346609 |
| Something changes every 2 to 3 s; cut on phrases | Every scene is a whole number of 2.5 s bars; the reveal lands on bar 17 | Community report: Roy Lee (above); https://filmdaft.com/how-to-edit-video-clips-to-the-beat-of-music-the-easy-way/ |
| Captions burned in and as a sidecar; at most 42 characters a line, 2 lines | `termcast.py` refuses a longer caption and writes the `.srt` | Sourced fact: Netflix English timed text guide, https://partnerhelp.netflixstudios.com/hc/en-us/articles/217350977-English-USA-Timed-Text-Style-Guide; X accepts `.srt`, https://help.x.com/en/using-x/upload-caption-srt-file |
| It makes sense with the sound off | No voice; every point is in a caption or on screen | Community report: Marketing Dive, May 2016, https://marketingdive.com/news/most-of-facebooks-8b-daily-video-views-happen-without-sound/419407 |
| Master near -14 LUFS, true peak below -1 dBTP | Two-pass `loudnorm` to -14 LUFS, -1.5 dBTP | Sourced fact (vendor documentation): https://youlean.co/?p=30813 |
| One call to action | The last card: the clone command, the demo, the guide | Interpretation |
| Inform, do not persuade; state the limits | A limits card; every clip labeled; no claim that letters were found or read | Sourced fact: Blastland et al., Nature 587, 362 to 364 (2020), doi 10.1038/d41586-020-03189-1 |

## Storyboard

Bars are 2.5 s at 96 bpm (one beat is 60 / 96 = 0.625 s). The cue names are in the score, so the render receipt gives each in seconds.

| Time | Bars | Shot | Label on screen | Caption | Music |
| --- | --- | --- | --- | --- | --- |
| 0 to 2.5 s | 1 | The monitor's finished synthetic run, slow zoom | Synthetic demo | AutoPipeline runs villa's pipeline for you | Pad and drone in |
| 2.5 to 7.5 s | 2 to 3 | Card: "Tracing, checking, rendering and scoring one scan takes many tool runs and checks by eye." | Concept illustration | Every step waits for a person | Cue `problem`; celesta on the phrase |
| 7.5 to 17.5 s | 4 to 7 | Terminal: `python scripts/demo_synthetic.py --out work/demo-run` to `DEMO PASS` | Synthetic demo | Step 1: every stage on a made-up scroll | Cue `demo`; hats enter |
| 17.5 to 22.5 s | 8 to 9 | Terminal: `monitor --text`, every stage Done or Skipped | Synthetic demo | Each stage is checked and recorded | |
| 22.5 to 27.5 s | 10 to 11 | Terminal: `plan PHerc0841` with its digest, run folder, voxel size and license | Interface (text only) | Step 2: freeze a plan for a real scan | Kick enters |
| 27.5 to 32.5 s | 12 to 13 | The monitor's surface cards, slow zoom | Synthetic demo | Watch the run live in the monitor | |
| 32.5 to 40 s | 14 to 16 | **Final cut: VC3D shots 1 to 3 (below).** Draft: the VC3D and AutoPipeline loop diagram | Interface (final), Concept illustration (draft) | Step 3: from a VC3D point and back again | Cue `vc3d`; riser into bar 17 |
| 40 to 50 s | 17 to 20 | Split: "By hand", the steps a person runs and checks; then "AutoPipeline 0.1.5", the same steps from one plan, with `DEMO PASS in 20.3 s` on the synthetic demo | Synthetic demo | Same steps, one plan, every check kept | Cue `reveal`: impact and crash on the right panel |
| 50 to 55 s | 21 to 22 | Card: limits (model output, not a reading; small patches; ink needs a GPU; Mac untested) | Concept illustration | Know the limits before a big run | Cue `limits`; thins out |
| 55 to 60 s | 23 to 24 | Card: the clone command, `python scripts/demo_synthetic.py`, the guide, credits | Concept illustration | Guide link in the post | Cue `call`; last chord, 2 s fade |

The split is not a race: the left side lists steps and gives no time, because none was measured. The 20.3 s is the demo's own report on a shared 4-core cloud container on 21 October 2026, and the card says so.

## VC3D shot list (to record on Chase's Mac)

VC3D cannot run in the cloud container that made the draft, so these three shots replace the diagram at 32.5 to 40 s. Record them on the synthetic demo's run or on PHerc0841 (not prize-eligible), with no ink maps on screen.

1. **2.5 s.** VC3D with PHerc0841 open; click on the papyrus; the focus point moves. Then a terminal beside it: `python3 ap_vc3d.py here --bridge` printing the plan digest.
2. **2.5 s.** `python3 ap_vc3d.py open --run last`; VC3D's segment list gains the `ap-...` surfaces and the seed points appear.
3. **2.5 s.** Zoom on one accepted surface in VC3D's viewer, its outline over the CT.

Large font (at least 18 pt in the terminal), dark theme, slow pointer, a short pause after each command. Label the shots "Interface". If a shot shows CT pixels, it is a Real data render of PHerc0841 and its credit, "Vesuvius Challenge open data, CC BY-NC 4.0", goes on screen and in the post.

## Exports

| Cut | Size | For | Status |
| --- | --- | --- | --- |
| 1920 x 1080, H.264 and AAC, 24 fps, with music | 60 s | YouTube, the guide's release notes, X | Draft rendered 21 Oct 2026: 3,640,385 bytes, -14.1 LUFS integrated, true peak -1.1 dBTP |
| The same, silent | 60 s | Muted autoplay, review | Draft rendered: 2,142,060 bytes |
| `.srt` captions | 10 cues | Every upload | Written by `termcast.py --srt` |
| Discord cut at or under 20 MB | 60 s | Discord | The master is already under 20 MB |
| 1:1 cut | | X | Not made: the terminal text is too small when cropped; post the 16:9 master |

Nothing here is posted. Each post needs Chase's yes (the go-ahead rule, hard rule 8).

## Rebuild the draft

```bash
python scripts/media/termcast.py scripts/media/captures/autopipeline-trailer.json \
  --out-dir FRAMES --fps 24 --size 1920x1080 --srt OUT/autopipeline-trailer.srt
node ORO/scripts/oro-score.mjs render scripts/media/captures/autopipeline-trailer.oro.txt --out OUT/music.wav --bits 32 --tail 0
ffmpeg -framerate 24 -i FRAMES/frame-%05d.png -i OUT/music.wav \
  -filter_complex "[1:a]atrim=0:60,afade=t=in:d=0.3,afade=t=out:st=58:d=2,loudnorm=I=-14:TP=-1.5:LRA=11[a]" \
  -map 0:v -map "[a]" -c:v libx264 -crf 20 -preset slow -pix_fmt yuv420p -movflags +faststart -c:a aac -b:a 192k \
  -shortest OUT/autopipeline-trailer-1080p.mp4
```

`FRAMES` is an empty scratch folder (about 170 MB of PNGs), `OUT` any folder outside `docs/assets/`, and `ORO` a clone of https://github.com/ChaseHendrick/Oro (Node 22 or newer, no `npm install` needed). The draft used two-pass `loudnorm`: the first pass measures and the second applies the measured values, which keeps the true peak under the ceiling.

## Not done

- **fframes.** The fframes chart recipe (not in this repository) draws bar charts of measured values, not screen recordings, and its first build needs about 2 GB of disk. The trailer uses `termcast.py` and ffmpeg instead. A comparison chart with measured numbers would use fframes.
- **Chase's X bookmarks and likes.** No X connector was available and x.com needs a login, so the rules above come from public sources only. Reading his bookmarks needs an X connector or his X data export (Settings, "Download an archive of your data").
