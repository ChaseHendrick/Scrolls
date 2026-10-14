# VC3D without a display

Checked 7 October 2026; the release AppImage route checked 12 October 2026. Short answer: yes. VC3D's command line tools need no display at all, and the VC3D app itself runs with no display under Qt's offscreen platform and can be driven over its agent bridge. The [tutorial](https://scrollprize.org/tutorial_VC3D) covers only the GUI; nothing below needs one. To let an AI agent drive all of it (tracing, rendering, checks, ink models, the app), see [vc3d-agents.md](vc3d-agents.md).

## What was run

Cloud sandbox, Ubuntu 24.04, 4 CPUs, no X server, `DISPLAY` unset. villa [`e0bbb8b`](https://github.com/ScrollPrize/villa/commit/e0bbb8b40a2db58b1d71864f286eb85717e59e64) (main on 2026-10-06) built from source with the packages and CMake flags of villa's `volume-cartographer/build_from_src_debian.sh`, except `-DVC_BUILD_FLATBOI=OFF` (see pitfall 3). All 47 `vc_*` tools and `VC3D` built.

| Check | Result |
| --- | --- |
| `vc_grow_seg_from_seed` with synthetic normal grids for one sheet tilted out of the seed quad's plane, and as the control the same grow with grids for the mirror sheet (9 October). This checks the tracer's normal-grid reader only: with its default loss weights the tracer reads nothing from the volume | With the sheet's grids, 16 of 16 vertices within 2 voxels of it (median 0.12 to 0.17, under 0.2 in every run; multithreaded runs vary by a few hundredths); with the mirror sheet's grids, 4 of 16 (median 13.2 to 13.7) and 16 of 16 on the mirror sheet, in nine runs at 1, 2, 4 and 8 threads, so the check can fail. An all-zero volume gave the same PASS (16 of 16, median 0.14), so the volume plays no part. The 7 October version of this check (a sheet in the seed quad's plane, no grids) could not fail; see below |
| `vc_render_tifxyz` on a synthetic ramp volume and a flat surface | Every layer holds exactly the expected value, with and without `--flip-normals` |
| VC3D app with `QT_QPA_PLATFORM=offscreen` | Starts; villa's own `apps/VC3D/agent_bridge/test/smoke_offscreen.py` passed 61 of 61 checks (120 JSON-RPC methods described) |
| Agent bridge `screenshot.capture` with no display | Returned a 796 x 796 PNG of the main window |
| `python -m kit vc3d selftest` | PASS in about two seconds (9 October, with the convention checks below and the tracer check against its mirror-grid control) |
| villa's `tools/vc3d-mcp`, started by `python -m kit vc3d app-mcp` (8 October) | Launched the app offscreen with its bridge; 120 methods |

On 12 October 2026, the same kind of sandbox (Ubuntu 24.04, x86_64, no display, no FUSE) ran villa's release AppImage instead of a build. The `latest` release, `VC3D-4eecd08-2026-10-12-linux-x86_64.AppImage` (120 MB, sha256 `59af3ea88cd2bb16610efb087dc45cf12c07668269951932f38ef8cc32b08ce4`), unpacks with its own `--appimage-extract` and holds 48 tools. With `VC_APPIMAGE` pointing at it, `python -m kit vc3d which` found all five tools the pipeline runs, and `python -m kit vc3d selftest` passed every check, `--flip-normals` included, in about two seconds.

## How to use it

```bash
export VC_APPIMAGE=$PWD/VC3D-4eecd08-2026-10-12-linux-x86_64.AppImage   # or VC_BIN=<villa build>/build/bin
python -m kit vc3d which                  # where the tools are, how they start, and the five the pipeline runs
python -m kit vc3d selftest               # synthetic render and trace with no display; exit 1 on FAIL
eval "$(python -m kit vc3d env)"          # headless exports for a shell
python -m kit vc3d mcp                    # the agent tools as an MCP server (stdio); see vc3d-agents.md
python -m kit vc3d call render '{"surface": "s.tifxyz", "volume": "v.zarr"}'   # one agent tool from a shell
python -m kit vc3d run vc_render_tifxyz -- --volume v.zarr --segmentation s.tifxyz --scale 1 --group-idx 0 \
    --num-slices 28 --zarr-output out.zarr --flip-normals
```

Tools are looked up in this order: `VC_ROOTFS` (a container root filesystem unpacked without docker, started through its own loader), `VC_BIN`, `VC_APPIMAGE`, `PATH`, then `/Applications/VC3D.app/Contents/MacOS`.

`VC_APPIMAGE` is villa's release AppImage, or the `squashfs-root` folder its `--appimage-extract` writes. The tools in an AppImage need its own loader and libraries, which its `AppRun` sets up; `AppRun` picks the tool by the name it was started as. So kit unpacks the file once (no FUSE needed) and makes a link to `AppRun` named after each tool, under `work/vc3d/appimage/` in the kit home (`KIT_HOME`; by default the repository). A `VC_BIN` or `PATH` entry that points at an unpacked AppImage's `squashfs-root/usr/bin` gets the same links, and `which` says so: started directly, those binaries crash (exit 139).

`which` lists the five tools the pipeline runs: `vc_gen_umbilicus` (umbilicus stage, when the catalog has no axis for the scan), `vc_grow_seg_from_seed` (trace), `vc_tifxyz_selfcross` (qa), `vc_flatten` (flatten) and `vc_render_tifxyz` (render). For a missing one it names the stage that needs it, and it exits 1. `selftest` reports the same list beside its verdict; its verdict covers its own checks, not the missing tools.

The headless environment sets `QT_QPA_PLATFORM=offscreen`, `OMP_NUM_THREADS` to the CPU quota (cgroup quota or affinity, whichever is smaller; a container usually sees every host core), `OPENBLAS_NUM_THREADS=1` and `OMP_WAIT_POLICY=PASSIVE`, as villa's container wrapper does. Community report ([Bullo27](https://github.com/Bullo27/first-letters-survey)): an uncapped OpenBLAS pool pinned every core, and capping it cut a 40-generation grow from 1,705 to 226 CPU seconds. Not measured here; the synthetic grows were too small to time.

The self-test can fail: a sampler that returns the wrong values, a tool that cannot start (missing library, no display support), a `--flip-normals` that does not reverse the layers, nearest-voxel instead of trilinear sampling, output pixels that do not map linearly onto the surface, or a tracer that does not follow its normal grids each fail it. It also reports whether the binary knows `--flip-normals` at all, and records the conventions below.

The tracer check (`trace_follows_grids`) covers the tracer's normal-grid reader, not its use of a surface prediction. It grows from the seed (64, 64, 64) three times. The first grow gets normal grids written for a sheet tilted out of the seed quad's plane, z = 64 + 0.6 (x - 64) + 0.3 (y - 64) in a 128-voxel cube, in villa's NormalGridVolume layout (`metadata.json` with `spiral-step` 20, one GridStore v3 file per xy, xz and yz slice, holding the sheet's line on that slice). The control gets grids written the same way for the mirror sheet, through the same seed with the tilt negated (-0.6, -0.3). The third grow gets no grids; it is reported and not scored. The check passes when the first grow has at least 9 vertices, one at least 25 voxels from the seed, and 90 percent of them within 2 voxels of the sheet, and the control also grows (at least 9 vertices, one at least 25 voxels out) but has fewer than 90 percent of them within 2 voxels of the sheet. If the control does not miss the sheet (or grows nothing), the check reports VOID: it cannot show that the grids put the grow on the sheet, so the self-test does not pass.

On 9 October on `e0bbb8b` (nine runs, see the table above), the control's vertices lay on the mirror sheet (16 of 16 within 2 voxels of it), so the tracer follows the grids it is given. Giving the first grow the mirror sheet's grids failed the check (4 of 16 on the sheet). Giving the control the sheet's own grids made it VOID, and so did an untilted sheet, which is its own mirror.

The volume plays no part in this check. The cube holds the sheet (the voxels within 2 of it are 255), but with its default loss weights no loss of the tracer reads the volume, with grids or without: the self-test gives it no direction field, and the volume losses have a default weight of 0 (`core/src/GrowPatch.cpp` at `e0bbb8b`, default weights at lines 1290 to 1302; Sourced fact). On 9 October an all-zero cube gave the same PASS (16 of 16 vertices on the sheet, median 0.14; the control 4 of 16). So the cube only gives the tracer a volume of the right shape, and a tracer that misreads a surface prediction would still pass.

Why the control is a mirror sheet: villa seeds every patch as a quad along x and y in the plane z = seed z (the seed quad at lines 3996 to 3997 and 4440 to 4443; Sourced fact). Until 9 October the check grew without grids on a sheet in that same plane, so it passed whether or not the tracer read anything (found by the 9 October review of skuzbucket1's site, confirmed in villa's source here). Without grids this build does not even keep the seed plane: rerun on 9 October, the old check grew vertices between z = 56 and 72 around its sheet at z = 64, and still passed with 947 of 1,273 rendered pixels on the sheet. The first fix (also 9 October) used the grow without grids as the control. That control misses a tilted sheet on this build (0 to 4 of 16 in the nine runs). But it would land on the sheet with a tracer that follows the prediction when it has no grids, and the check would then call a tracer that does follow its grids VOID. The mirror grids test the grids directly and do not depend on what the tracer does without them. The published image's older tracer has not been run on this check.

To drive the app itself, start it with `--agent-bridge-name NAME` under the headless environment (`python -m kit vc3d run VC3D -- --agent-bridge-name NAME`) and talk JSON-RPC to the socket it prints, or use the agent tools `app_start` and `app_call`. villa's [`tools/vc3d-mcp`](https://github.com/ScrollPrize/villa/tree/main/volume-cartographer/tools/vc3d-mcp) wraps the same bridge as an MCP server; `python -m kit vc3d app-mcp` starts it with the app offscreen. The pipeline itself does not need the app: tracing, rendering and flattening each have a command line tool, and `python -m kit vc3d mcp` serves them to agents ([vc3d-agents.md](vc3d-agents.md)).

## Rendering conventions, measured

The self-test measures these on synthetic volumes with known values, so a build that differs fails or reports it (villa `e0bbb8b`, 8 October 2026):

| Convention | Measured |
| --- | --- |
| Layer order without `--flip-normals` | Layer index grows along the normal N = dP/dcol x dP/drow (`+N`) |
| `--flip-normals` | The default render with its layers reversed, byte for byte |
| Sampling between voxels | Trilinear: layers 0.5 voxel apart through a ramp of 8 per voxel give 122, 126, 130, 134, not the nearest voxel's 120, 128, 128, 136 |
| Pixel registration | Output pixel p samples the surface (p + 0.5) / scale voxels from its first grid point (pixel centres), at scales 1 and 2, along both axes |
| Surface edges | The outer half grid cell of every edge renders empty (measured between 0.4375 and 0.5625 cells) |
| Output size | Grid columns / meta scale x `--scale` pixels wide, rows likewise (measured at scales 1 and 2). villa also multiplies by `--scale-segmentation`, by the cube root of an affine's determinant and by 2^-level, then rounds ([source](https://github.com/ScrollPrize/villa/blob/e0bbb8b40a2db58b1d71864f286eb85717e59e64/volume-cartographer/apps/src/vc_render_tifxyz.cpp), lines 1839 to 1844; Sourced fact) |

Which order the published renders use is a sourced fact, not a measurement: `--flip-normals`, per tutorial 5 and the comment in `vc_render_tifxyz.cpp` ([details](vc3d-agents.md#rendering-conventions)). `kit vc3d` renders in that order by default and reverses the layers itself on a binary without the flag.

## Where to get the tools

| Source | `--flip-normals` | Status |
| --- | --- | --- |
| villa's [`latest` release](https://github.com/ScrollPrize/villa/releases/tag/latest), Linux x86_64 AppImage (`VC_APPIMAGE`) | Yes | 4eecd08 of 2026-10-12: all five pipeline tools, self-test PASS here on 12 October. The `latest` release is replaced on each villa build, so its file name and sha256 change |
| villa's `stable` release AppImage (fc25b4d, July 2026) | Not recorded | Passed the self-test here on 12 October, but lacks `vc_tifxyz_selfcross` and `vc_gen_umbilicus`, which the pipeline's qa and umbilicus stages run |
| villa main built from source (`build_from_src_debian.sh`) | Yes | Built and self-tested here at `e0bbb8b` |
| Published image `ghcr.io/scrollprize/villa/volume-cartographer`, tags `main` and `edge` | No | Not run here. Read from the registry on 12 October: built 2026-05-13 from villa `1e3f4c0`, amd64 and arm64; it also lacks `vc_tifxyz_selfcross` and `vc_gen_umbilicus` |
| That image unpacked without docker (`VC_ROOTFS`) | No | Lookup covered by unit tests only |
| macOS (arm64) dmg and zip in the same `latest` release | Not run | The zip's listing holds all five pipeline tools in `VC3D.app/Contents/MacOS`, where kit looks. Not run here. villa's README says the app is not notarized, so macOS blocks it until the quarantine attribute is removed (`xattr -dr com.apple.quarantine /Applications/VC3D.app`) |

## Pitfalls found

1. **The published image is five months old.** Sourced fact (registry read 2026-10-07): tags `main` and `edge` resolve to the same index, `sha256:bad516f6...`, whose amd64 image is `sha256:b2509de2...`, built from villa `1e3f4c0` of 2026-05-13. That revision's `vc_render_tifxyz.cpp` has no `--flip-normals`. Its renders should come out in the order a current binary gives without the flag: both revisions build the normal and the layer offsets the same way (read from the source, not run). That order swaps forward and reverse maps (pscamillo's eligible-mesh maps, corrected 2026-09-15). The self-test found the `--flip-normals` render equal, byte for byte, to the default render with its layers reversed; that was a flat synthetic surface, and since the flag only negates the normal it should hold on any surface (interpretation). With the old image, reverse the layer order before inference.
2. **villa `e0bbb8b`'s install step drops a library.** `cmake --install BUILD --component vc_runtime` leaves out `libvolcomp.so` (`libs/volcomp`, added by [#1704](https://github.com/ScrollPrize/villa/pull/1704) on 2026-10-06, is not in the install list in `volume-cartographer/CMakeLists.txt`). Every installed tool then fails with `libvolcomp.so: cannot open shared object file`. `build_from_src_debian.sh` only checks that the executables exist, so it still reports success. Run from the build tree (`build/bin`), or copy `build/libs/volcomp/libvolcomp.so` into the install's `lib/`; both pass the self-test. Reported upstream by someone else (Community report): skuzbucket1 opened [villa PR #2008](https://github.com/ScrollPrize/villa/pull/2008) on 2026-10-08 with a one-line fix (adding `libs/volcomp` to the install list), and it was open on 2026-10-09, when pmh47 commented there that the bug breaks their CI builds too. That state was read from the PR page by the 9 October review of skuzbucket1's site and not checked again here. Keep the build-tree route until villa's pinned revision includes a merged fix.
3. **flatboi needs gitlab.inria.fr at configure time.** It fetches PaStiX from there, which this sandbox's proxy denied on 7 October, so the build here skipped flatboi (SLIM flattening). ABF++ flattening (`vc_flatten`, `vc_render_tifxyz --flatten`) is unaffected.
4. **Network drops.** `vc_render_tifxyz` dumped core when a chunk fetch failed until [#1817](https://github.com/ScrollPrize/villa/pull/1817) (2026-09-24, in `e0bbb8b`'s history); the published image predates it, so retry its remote renders.
5. **AppImage tools crash when started directly.** Measured 12 October: with `VC_BIN` set to an unpacked AppImage's `squashfs-root/usr/bin`, the tools exited 139, because they need the loader and libraries the AppImage bundles. Started through `AppRun`, by links named after each tool, they passed the self-test. kit makes those links itself for `VC_APPIMAGE`, and for a `VC_BIN` or `PATH` entry inside `squashfs-root/usr/bin`.

## Modal

The Modal runner that ran these tools in the cloud during development, `scripts/vc3d/modal_vc3d.py`, is not part of this release. Run the tools on your own machine as above.
