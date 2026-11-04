# Draft: comment on villa issue 2346 offering to work together on the geometry overlap check

Status: draft by an agent, 4 Nov 2026. Not posted. Chase reads it, edits it and posts it himself if he wants to
(AGENTS.md rule 12). When posting, mention dlescanogithub with an @ in front; it is left bare here so nobody is
notified from this file. Issue: https://github.com/ScrollPrize/villa/issues/2346

---

dlescanogithub, checking leakage on the meshes instead of by segment id made a lot of sense to me, so I tried a
version of it. I'd rather build it with you than end up with two tools that do the same thing.

For every segment in the open data catalog that has ink labels, it takes the training segments each released ink
model lists (ink_9um, v8in, d9v2, Reader v2 and V3, ink_canonical_2um, Hecate and a few more), puts their tifxyz
meshes in the labeled segment's own volume, and counts how many of its vertices have a training surface within
60 um along that surface's normal, only inside the training mesh's own grid. It also gives the share within 100 um
and the z range overlap, like you suggested. Meshes only, no labels or CT.

Before real pairs I planted 30 public meshes as renamed copies in another scan's frame, moved 0 to 3 voxels. It found
all 30. The control, the same copies moved 100 um further, failed at first: big auto-grown PHerc0814 meshes cover
neighboring windings themselves, so the shifted copy lands on the mesh's own next winding. I changed the control and
reran it under a new preregistration; on the third attempt (the first ran out of memory) none of the 30 was called
exposed. Both runs are written up, the failed one too.

What it shows that a name check can't: some segments a training list holds out as test segments sit partly on the
same papyrus as that model's training segments (PHerc0009B `auto_grown_20250919055754487_inp_hr`: about 43 % of its
vertices within 60 um of three PHerc0009B training traces), and several labeled segments overlap each other. These
are geometry numbers, not proof either way. In this first matrix every training mesh was traced on the labeled
segment's own scan, so no cell depends on a catalog transform yet; when one does, it carries that transform's
landmark error.

Code, the matrix and the planted checks: https://github.com/ChaseHendrick/Scrolls/pull/321 (Apache-2.0). Happy to
port the core into inkcheck, or match your NO_HELD_OUT output so the two read together. How would you set the
distance? 60 um sits under half a winding, but where windings are pressed together it may be too wide.
