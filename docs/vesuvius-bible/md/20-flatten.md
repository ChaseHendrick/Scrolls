<a id="ch-flatten"></a>

# Flattening and Rendering {#ch-flatten}

> **Chapter summary.** Flattening assigns each mesh point a 2D coordinate with as little distortion as possible; VC3D's production tool, flatboi, uses SLIM to minimize the symmetric Dirichlet energy. Rendering then samples the CT volume along the mesh and its normals to produce a **surface volume**, a stack of flat images centered on the papyrus surface, which is what most ink models read.

## Flattening

"Flattening takes each point on the 3D mesh and assigns it a 2D coordinate. The same trick as making a flat map from a curved globe, but in our case we are aiming to preserve local distances as much as possible: we are looking for a transformation from 3D -> 2D which is isometric" [VC-OpenProblems2026].

- **flatboi** is "VC3D's current production flattening tool"; it "uses SLIM (Scalable Locally Injective Mappings), minimizing the Symmetric Dirichlet Energy (which is small the lower the isometric distortion induced by the map)" [VC-OpenProblems2026] [Rabinovich2017].
- An earlier community variant, *slim-flatboi*, by Giorgio Angelotti, was reported to improve L2 and L-infinity stretch metrics and won part of a $20,000 prize in March 2024 [VC-MarchProgress2024].
- Particle-based flattening (William Stevens) received a progress prize in February 2025 [VC-Winners].
- For spiral fits, flattening is largely implicit: the inverse deformation maps scan points to the ideal sheet, and *render_ink.py* SLIM-flattens concatenated windings before rendering [VC-SpiralTutorial].
- The 2027 Grand Prize requires each tifxyz mesh to "already include a low-distortion isometric 2D parametrization (flattening)" [VC-Prizes].

Fibers provide a physical check: in a good flattening the horizontal and vertical fibers appear straight in the flat view, and the VC3D tutorial uses visible fibers as the sign of an accurate segment [VC-VC3DTutorial] [VC-OpenProblems2026].

## Rendering surface volumes

"A surface-conditioned render, or a surface volume, is a flattened 3D subvolume centered on a segmented sheet surface. Using the mesh's 2D flattened coordinates, each point on the sheet is mapped back into the original CT volume. The center layer corresponds to the sheet surface, while additional layers are sampled at positive and negative voxel offsets along the local surface normal" [VC-OpenProblems2026].

The tool is **vc_render_tifxyz**. The ink tutorial's example renders a PHerc. 139 segment (w035) against the native 9.362 µm volume, streamed from S3, into a Zarr with 28 slices, which "takes about five minutes and writes a ~900 MB Zarr" of 5820 x 5240 pixels per slice [VC-InkTutorial]. Key options [VC-InkTutorial]:

| Option | Purpose |
|---|---|
| `--volume s3://...` | stream the scroll volume; chunks persist in VC3D's remote cache (default `~/.VC3D/remote_cache`) |
| `--segmentation ...tifxyz` | the surface mesh |
| `--zarr-output` | output surface volume |
| `--num-slices 28` | depth of the stack, matching released renders |
| `--voxel-size 9.362 --voxel-unit micrometer` | physical metadata |
| `--flip-normals` | reproduce the depth orientation of published renders and labels |
| `--cache-gb 16` | cache size |

In VC3D, right-clicking a segment and choosing **Render** runs the same tool with a dialog [VC-InkTutorial]. A September 2026 progress prize made the renderer "load only the chunks actually needed along the surface, greatly reducing memory use" [VC-Winners], and an October 2026 change allowed remote OME-Zarr input [Recent-2026-10-15].

## Depth and orientation

Surface volumes are sensitive to where the surface sits in depth. The ink tutorial warns that 9 µm models "are sensitive to depth offsets" and suggests shifting the window with `--layer-start` and `--layer-end` or averaging nearby windows; when the facing direction is unknown, `--direction both` writes both orientations [VC-InkTutorial]. An August 2026 progress prize studied "how many depth slices the 9 µm ink model actually needs" (Paulo Sergio Camillo) [VC-Winners].

## Beyond surface volumes

Native 3D ink models skip rendering: "for every training patch it uses the .tifxyz coordinates to find where the segment passes through the original scroll volume, samples a 3D crop there on the fly, and projects the 2D labels into the crop around the surface" [VC-InkTutorial]. [Chapter 21](21-ink.md#ch-ink) describes them.
