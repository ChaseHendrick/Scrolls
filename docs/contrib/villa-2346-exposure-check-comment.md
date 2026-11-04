# Draft: comment on villa issue 2346 offering to work together on the geometry overlap check

Status: draft by an agent, 4 Nov 2026. Not posted. Chase reads it, edits it and posts it himself if he wants to
(AGENTS.md rule 12). When posting, mention dlescanogithub with an @ in front; it is left bare here so nobody is
notified from this file. Issue: https://github.com/ScrollPrize/villa/issues/2346

---

dlescanogithub, your idea of checking leakage on the meshes instead of by segment id made a lot of sense to me, so I
tried a version of it. I'd rather build this with you than end up with two tools that do the same thing.

What it does: for every segment in the open data catalog that has ink labels, it takes the training segments each
released ink model lists (ink_9um, v8in, d9v2, Reader v2 and V3, ink_canonical_2um, Hecate, and a few more), moves
their tifxyz meshes into the labeled segment's own volume (the catalog's transformed tifxyz where there is one, else
the catalog affine), and counts how many of the labeled segment's vertices have a training surface within 60 um along
that surface's normal. It only counts spots inside the training mesh's own grid, so mesh edges and holes don't count.
It also reports the share within 100 um (about one render band) and the z range overlap, like you suggested. It
reads meshes only, no labels and no CT.

Before running it on real pairs I planted duplicates: 30 public meshes copied into another scan's frame with the
catalog transform, moved 0 to 3 voxels along the normal and renamed. It found all 30. The control was the same
copies moved 100 um further, which should come back clear. My first version of that control failed: big auto-grown
PHerc0814 meshes cover neighboring windings themselves, so the shifted copy lands on the mesh's own next winding.
Scoring the control only where a mesh has nothing else of itself within 160 um fixed it, and the second run passed.
Both runs are written up, the failed one too.

A few things it shows that a name check can't: some segments that a training list holds out as test segments sit
partly on the same papyrus as that model's training segments (for example PHerc0009B
`auto_grown_20250919055754487_inp_hr`, about 43 % of its vertices within 60 um of three PHerc0009B training
traces), and several labeled segments overlap each other, so a split between them isn't clean either. These are
geometry numbers, not proof either way, and anything that crosses scans depends on the catalog transforms, which
#1835 and #2312 question. Each cross-scan cell carries the transform's landmark error.

Code, the matrix and the planted checks: LINK (Apache-2.0). If it helps I'm happy to port the core into inkcheck, or
match whatever output format you already use for NO_HELD_OUT so the two can be read together. I'd also really like
to know how you'd set the distance. 60 um was chosen to sit under half a winding, and where windings are pressed
together that may be too wide.
