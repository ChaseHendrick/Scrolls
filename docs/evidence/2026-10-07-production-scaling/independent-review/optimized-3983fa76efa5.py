"""Conservative bilinear-quad correspondence, independent of reader outputs.

The radius search includes every quad that could be within the physical bound.
Triangle approximations only bound distances: accepted coordinates are evaluated
on the actual bilinear quad. Unresolved optimization and ambiguous matches abstain.
"""

import heapq

from .verify import _numpy


def quad_mask(mesh):
    """Four valid corners and consistently oriented, nondegenerate Jacobians."""
    np = _numpy()
    xyz, valid = mesh["xyz"], mesh["valid"]
    a, b, c, d = xyz[:-1, :-1], xyz[1:, :-1], xyz[:-1, 1:], xyz[1:, 1:]
    cross = np.stack([np.cross(b - a, c - a), np.cross(b - a, d - b),
                      np.cross(d - c, c - a), np.cross(d - c, d - b)], -2)
    center = cross.mean(-2)
    return (valid[:-1, :-1] & valid[1:, :-1] & valid[:-1, 1:] & valid[1:, 1:] &
            ((cross * center[..., None, :]).sum(-1) > 1e-12).all(-1))


def bilinear(corners, uv):
    np = _numpy()
    u, v = np.asarray(uv)[..., 0:1], np.asarray(uv)[..., 1:2]
    a, b, c, d = [corners[..., i, :] for i in range(4)]
    return a * (1 - u) * (1 - v) + b * u * (1 - v) + c * (1 - u) * v + d * u * v


def sample_geometry(mesh, uv):
    """Bilinear volume coordinates, plus validity without crossing holes or folds."""
    np = _numpy()
    uv = np.asarray(uv)
    shape = mesh["valid"].shape
    inside = np.isfinite(uv).all(-1) & (uv >= 0).all(-1)
    inside &= (uv[..., 0] <= shape[0] - 1) & (uv[..., 1] <= shape[1] - 1)
    safe = np.where(np.isfinite(uv), uv, 0)
    cells = np.clip(np.floor(safe).astype(int), 0, np.asarray(shape) - 2)
    r, c = cells[..., 0], cells[..., 1]
    xyz = mesh["xyz"]
    corners = np.stack([xyz[r, c], xyz[r + 1, c], xyz[r, c + 1], xyz[r + 1, c + 1]], -2)
    return bilinear(corners, safe - cells), inside & quad_mask(mesh)[r, c]


def _triangle_closest(point, triangles):
    """Exact closest points on nondegenerate triangles, including their edges."""
    np = _numpy()
    a, b, c = [triangles[:, i] for i in range(3)]
    e0, e1, v = b - a, c - a, point - a
    d00, d01, d11 = (e0 * e0).sum(-1), (e0 * e1).sum(-1), (e1 * e1).sum(-1)
    d20, d21 = (v * e0).sum(-1), (v * e1).sum(-1)
    den = d00 * d11 - d01 * d01
    u = np.divide(d11 * d20 - d01 * d21, den, out=np.zeros_like(den), where=den > 0)
    vv = np.divide(d00 * d21 - d01 * d20, den, out=np.zeros_like(den), where=den > 0)
    interior = a + u[:, None] * e0 + vv[:, None] * e1
    starts = np.stack([a, b, c], 1)
    edges = starts[:, [1, 2, 0]] - starts
    denominator = (edges * edges).sum(-1)
    alpha = np.clip(np.divide(((point - starts) * edges).sum(-1), denominator,
                             out=np.zeros_like(denominator), where=denominator > 0), 0, 1)
    points = np.empty((len(triangles), 4, 3), dtype=interior.dtype)
    points[:, 0] = interior
    points[:, 1:] = starts + alpha[..., None] * edges
    # Original edges rounded weights to float64, then stacked with the interior.
    # Preserve that promotion and rounding even for wider floating point inputs.
    interior_bary = np.stack([1 - u - vv, u, vv], -1)
    bary = np.zeros((len(triangles), 4, 3), dtype=np.result_type(interior_bary.dtype, np.float64))
    bary[:, 0] = interior_bary
    edge_alpha = alpha.astype(np.float64, copy=False)
    edge_complement = (1 - alpha).astype(np.float64, copy=False)
    bary[:, 1, 0], bary[:, 1, 1] = edge_complement[:, 0], edge_alpha[:, 0]
    bary[:, 2, 1], bary[:, 2, 2] = edge_complement[:, 1], edge_alpha[:, 1]
    bary[:, 3, 2], bary[:, 3, 0] = edge_complement[:, 2], edge_alpha[:, 2]
    distance = np.linalg.norm(points - point, axis=-1)
    distance[:, 0] = np.where((den > 0) & (u >= 0) & (vv >= 0) & (u + vv <= 1), distance[:, 0], np.inf)
    best = distance.argmin(-1)
    return distance[np.arange(len(best)), best], bary[np.arange(len(best)), best]


def _cell_bounds(point, corners, box):
    """Rigorous distance lower bound and an on-quad feasible upper bound."""
    np = _numpy()
    u0, u1, v0, v1 = box
    cell_uv = np.array([[u0, v0], [u1, v0], [u0, v1], [u1, v1]])
    cell = bilinear(corners, cell_uv)
    vertices = np.array([[0, 1, 2], [3, 2, 1]])
    distance, bary = _triangle_closest(point, cell[vertices])
    seeds = (cell_uv[vertices] * bary[..., None]).sum(1)
    positions = bilinear(corners, seeds)
    upper = np.linalg.norm(positions - point, axis=-1)
    best = int(np.argmin(upper))
    warp = np.linalg.norm(cell[3] - cell[1] - cell[2] + cell[0]) / 4
    return max(0., float(distance.min()) - float(warp)), float(upper[best]), seeds[best]


def _child_bounds(point, corners, boxes):
    """Evaluate four child boxes together, preserving scalar seeds and bounds."""
    np = _numpy()
    boxes = np.asarray(boxes)
    u0, u1, v0, v1 = boxes.T
    cell_uv = np.stack([np.stack([u0, v0], -1), np.stack([u1, v0], -1),
                        np.stack([u0, v1], -1), np.stack([u1, v1], -1)], 1)
    cell = bilinear(corners, cell_uv)
    vertices = np.array([[0, 1, 2], [3, 2, 1]])
    distance, bary = _triangle_closest(point, cell[:, vertices].reshape(-1, 3, 3))
    distance, bary = distance.reshape(-1, 2), bary.reshape(-1, 2, 3)
    seeds = (cell_uv[:, vertices] * bary[..., None]).sum(2)
    positions = bilinear(corners, seeds)
    upper = np.linalg.norm(positions - point, axis=-1)
    best = upper.argmin(-1)
    result = []
    for i, index in enumerate(best):
        # Keep the original one-vector norm arithmetic, including rounding.
        warp = np.linalg.norm(cell[i, 3] - cell[i, 1] - cell[i, 2] + cell[i, 0]) / 4
        result.append((max(0., float(distance[i].min()) - float(warp)),
                       float(upper[i, index]), seeds[i, index]))
    return result


def _unique_minimum(point, corners):
    """Sufficient global strict-convexity certificate for squared distance.

    P=a+bu+cv+duv. The Hessian diagonals are |b+dv|^2 and |c+du|^2,
    with exact interval minima. Its off-diagonal is bilinear, so its maximum
    absolute value occurs at a corner. Positive diagonals and a positive lower
    determinant bound certify a unique constrained minimum on the unit box.
    A failed sufficient certificate abstains; it does not prove non-uniqueness.
    """
    np = _numpy()
    a, b0, c0, end = corners
    b, c, d = b0 - a, c0 - a, end - b0 - c0 + a
    dd = float(d @ d)
    def minimum_norm_squared(edge):
        position = float(np.clip(-(edge @ d) / dd, 0, 1)) if dd > 0 else 0.
        vector = edge + position * d
        return float(vector @ vector)
    h11, h22 = minimum_norm_squared(b), minimum_norm_squared(c)
    base = float(b @ c + (a - point) @ d)
    bd, cd = float(b @ d), float(c @ d)
    h12 = max(abs(base), abs(base + 2 * bd), abs(base + 2 * cd), abs(base + 2 * bd + 2 * cd + 2 * dd))
    product = h11 * h22
    guard = 1024 * np.finfo(float).eps * max(1., product, h12 * h12)
    return h11 > 0 and h22 > 0 and product - h12 * h12 > guard


def closest_quad(point, corners, tolerance, budget=4096):
    """Certified distance bracket by subdivision; exhaustion is never success."""
    np = _numpy()
    lower, upper, uv = _cell_bounds(point, corners, (0., 1., 0., 1.))
    heap = [(lower, 0, (0., 1., 0., 1.))]
    serial = 1
    while heap and upper - heap[0][0] > tolerance:
        if serial >= budget:
            return {"lower": heap[0][0], "upper": upper, "uv": uv, "converged": False}
        _, _, box = heapq.heappop(heap)
        u0, u1, v0, v1 = box
        um, vm = (u0 + u1) / 2, (v0 + v1) / 2
        children = ((u0, um, v0, vm), (u0, um, vm, v1), (um, u1, v0, vm), (um, u1, vm, v1))
        for child, (lo, hi, seed) in zip(children, _child_bounds(point, corners, children)):
            if hi < upper or (hi == upper and tuple(seed) < tuple(uv)):
                upper, uv = hi, seed
            if lo <= upper:
                heapq.heappush(heap, (lo, serial, child))
            serial += 1
    lower = min(upper, heap[0][0]) if heap else upper
    return {"lower": lower, "upper": upper, "uv": np.asarray(uv), "converged": True}


def project(source, reference, max_distance, tolerance):
    """Certified complete radius candidates and conservative correspondence.

    A bilinear quad lies inside its corner convex hull. Thus every qualifying quad
    has its centroid within max_distance + its maximum corner radius. AABB pruning
    and distance brackets never discard a possible closer or competing quad.
    """
    np = _numpy()
    from scipy.spatial import cKDTree
    qr, qc = np.nonzero(quad_mask(reference))
    xyz = reference["xyz"]
    corners = np.stack([xyz[qr, qc], xyz[qr + 1, qc], xyz[qr, qc + 1], xyz[qr + 1, qc + 1]], 1)
    result_shape = source["valid"].shape
    uv = np.zeros(result_shape + (2,))
    distance = np.full(result_shape, np.inf)
    valid = np.zeros(result_shape, dtype=bool)
    ambiguous = np.zeros(result_shape, dtype=bool)
    unresolved = np.zeros(result_shape, dtype=bool)
    if not len(corners):
        return {"uv": uv, "distance": distance, "valid": valid, "ambiguous": ambiguous, "unresolved": unresolved}
    centers = corners.mean(1)
    radii = np.linalg.norm(corners - centers[:, None], axis=-1).max(1)
    lower_corner, upper_corner = corners.min(1), corners.max(1)
    tree = cKDTree(centers)
    radius = max_distance + float(radii.max()) + tolerance
    for r, c in zip(*np.nonzero(source["valid"])):
        point = source["xyz"][r, c]
        numerical_epsilon = 64 * np.finfo(float).eps * max(1., float(np.linalg.norm(point)), max_distance)
        candidates = sorted(tree.query_ball_point(point, radius))
        matches = []
        unknown_lower = np.inf
        for index in candidates:
            delta = np.maximum(np.maximum(lower_corner[index] - point, point - upper_corner[index]), 0)
            if np.linalg.norm(delta) > max_distance + tolerance:
                continue
            match = closest_quad(point, corners[index], tolerance)
            if not match["converged"]:
                unknown_lower = min(unknown_lower, match["lower"])
                continue
            if match["lower"] <= max_distance + tolerance:
                if not _unique_minimum(point, corners[index]):
                    # One unfolded saddle can itself have distinct nearest UVs.
                    # Never silently discard a possibly qualifying non-certified quad.
                    unknown_lower = min(unknown_lower, match["lower"])
                    continue
                match["uv"] = match["uv"] + [qr[index], qc[index]]
                matches.append(match)
        if not matches:
            unresolved[r, c] = unknown_lower <= max_distance
            continue
        matches.sort(key=lambda m: (m["upper"], tuple(m["uv"])))
        winner = matches[0]
        uv[r, c], distance[r, c] = winner["uv"], winner["upper"]
        # An unresolved quad inside the physical radius might be a remote winding
        # that our ambiguity policy must reject, even if farther than the winner.
        if unknown_lower <= max_distance + numerical_epsilon:
            unresolved[r, c] = True
            continue
        if winner["upper"] > max_distance:
            # A bracket crossing the physical threshold abstains.
            unresolved[r, c] = winner["lower"] <= max_distance
            continue
        # Near-equal nearest points at distinct UVs are not a unique match. Also
        # reject a remote winding within the radius, even if slightly farther.
        for other in matches[1:]:
            uv_gap = np.linalg.norm(other["uv"] - winner["uv"])
            if ((other["lower"] <= winner["upper"] + numerical_epsilon and uv_gap > 1e-5) or
                    (uv_gap > 2 and other["lower"] <= max_distance)):
                ambiguous[r, c] = True
                break
        valid[r, c] = not ambiguous[r, c]
    return {"uv": uv, "distance": distance, "valid": valid, "ambiguous": ambiguous, "unresolved": unresolved}
