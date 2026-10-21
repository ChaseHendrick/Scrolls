"""Hard mesh checks for a parameter-domain sheet. Standard library only. Not a reading."""

from __future__ import annotations


class MeshGateError(ValueError):
    pass


def mesh_verdict(triangles):
    """Fail unless the sheet is one counterclockwise piece with no bad edges.

    A shared edge used in opposite directions passes. An edge used by three
    triangles fails. A repeated directed edge fails. An empty sheet, a
    zero-area triangle, a clockwise triangle, or two separate pieces fail.
    Points compare equal only when both coordinates are exactly equal.
    """
    n = len(triangles)
    blank = {
        "pass": False,
        "components": 0,
        "nonmanifold": 0,
        "same_dir": 0,
        "cw": 0,
        "ccw": 0,
        "degenerate": 0,
        "rule": _RULE,
    }
    if n == 0:
        return blank
    cw = ccw = deg = 0
    faces = []
    for tri in triangles:
        if len(tri) != 3:
            raise MeshGateError("triangle must have 3 points")
        pts = []
        for p in tri:
            if len(p) != 2:
                raise MeshGateError("point must be (x, y)")
            pts.append((float(p[0]), float(p[1])))
        a, b, c = pts
        area2 = (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
        if area2 == 0:
            deg += 1
        elif area2 > 0:
            ccw += 1
        else:
            cw += 1
        faces.append(tuple(pts))
    undirected = {}
    directed = {}
    tri_edges = []
    for pts in faces:
        edges = []
        for i, j in ((0, 1), (1, 2), (2, 0)):
            p, q = pts[i], pts[j]
            directed[(p, q)] = directed.get((p, q), 0) + 1
            key = (p, q) if p <= q else (q, p)
            undirected[key] = undirected.get(key, 0) + 1
            edges.append(key)
        tri_edges.append(edges)
    nonmanifold = sum(1 for count in undirected.values() if count >= 3)
    same_dir = sum(1 for count in directed.values() if count >= 2)
    parent = list(range(n))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i, j):
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[rj] = ri

    owner = {}
    for i, edges in enumerate(tri_edges):
        for edge in edges:
            if edge in owner:
                union(i, owner[edge])
            else:
                owner[edge] = i
    components = len({find(i) for i in range(n)})
    ok = (
        deg == 0
        and cw == 0
        and ccw == n
        and nonmanifold == 0
        and same_dir == 0
        and components == 1
    )
    return {
        "pass": ok,
        "components": components,
        "nonmanifold": nonmanifold,
        "same_dir": same_dir,
        "cw": cw,
        "ccw": ccw,
        "degenerate": deg,
        "rule": _RULE,
    }


_RULE = (
    "fail unless every triangle is counterclockwise and has area, "
    "the sheet is one piece, no edge is used 3 times, "
    "and no directed edge is repeated"
)
