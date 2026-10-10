"""Parses a WoW M2 model + its .skin so texture pixels can be weighted by how
much VISIBLE, outward-facing geometry actually maps to them.

Why this exists: `generate_color_data.py` reads raw texture pixels, but a raw
armor texture contains surfaces the rendered model never shows -- hood linings,
undersides, interior faces. Measured on 895 helms, 46% of primary colors
classified as achromatic and a gold hood with a black lining matched "black".
No threshold fixes that, because the black pixels are genuinely in the texture;
they just aren't genuinely on screen. The fix has to come from geometry.

Approach: every triangle contributes weight = (3D area) * max(0, dot(normal,
outward)), where `outward` points from the model's centre to the triangle. A
hood's outer shell faces away from the centre and keeps its weight; the lining
faces back toward the head and drops to zero. That weight is splatted into the
triangle's UV footprint, producing a per-texture weight map the colour
extractor multiplies pixel counts by.

Format notes confirmed empirically (see the probe output that preceded this
file), not taken from spec alone:
  - Files are chunked: MD21 wraps the legacy MD20 body, which itself still
    begins with the "MD20" magic. All MD20-internal offsets are relative to the
    START OF THE MD21 CHUNK CONTENT, not the file.
  - SFID lists .skin FileDataIDs, highest detail first.
  - TXID lists texture FileDataIDs per texture slot. **A zero means a DYNAMIC
    slot** -- one the game binds at runtime, which is precisely the item
    texture this project resolves separately via ItemDisplayInfoMaterialRes.
    So the triangles worth weighting are the ones whose batch points at a
    zero/dynamic slot; baked-in textures (fdid != 0) are model decoration.
"""

import math
import struct
from pathlib import Path

M2Array = "<II"  # count, offset -- ubiquitous in the format


class M2ParseError(Exception):
    pass


def _array(data, base, off):
    """Reads an M2Array header at `off` (absolute) -> (count, absolute offset)."""
    count, rel = struct.unpack_from(M2Array, data, off)
    return count, base + rel


def iter_chunks(data):
    off = 0
    while off + 8 <= len(data):
        magic = data[off:off + 4]
        size = struct.unpack_from("<I", data, off + 4)[0]
        if size > len(data) - off - 8:
            break
        yield magic, off + 8, size
        off += 8 + size


class M2Model:
    """Just the pieces needed for texture weighting: vertices and the texture
    slot table. Animation, bones and materials are deliberately not parsed."""

    def __init__(self, data):
        self.skin_fdids = []
        self.texture_fdids = []
        body = None
        for magic, start, size in iter_chunks(data):
            if magic == b"MD21":
                body = start
            elif magic == b"SFID":
                self.skin_fdids = list(struct.unpack_from("<%dI" % (size // 4), data, start))
            elif magic == b"TXID":
                self.texture_fdids = list(struct.unpack_from("<%dI" % (size // 4), data, start))
        if body is None:
            raise M2ParseError("no MD21 chunk (pre-Legion M2 files are not supported)")
        if data[body:body + 4] != b"MD20":
            raise M2ParseError(f"MD21 body magic was {data[body:body+4]!r}, expected MD20")

        version = struct.unpack_from("<I", data, body + 4)[0]
        if version < 264:
            # Older layout inserts playable_animation_lookup, shifting every
            # field this parser reads. Bail rather than silently misparse.
            raise M2ParseError(f"M2 version {version} predates the 264+ header layout")
        self.version = version

        # Header field offsets for the version >= 264 layout, relative to body.
        n_vert, off_vert = _array(data, body, body + 60)
        n_tex, off_tex = _array(data, body, body + 80)
        n_texcombo, off_texcombo = _array(data, body, body + 128)

        self.vertices = self._read_vertices(data, off_vert, n_vert)
        self.texture_types = [
            struct.unpack_from("<I", data, off_tex + i * 16)[0] for i in range(n_tex)
        ]
        self.texture_combos = list(
            struct.unpack_from("<%dH" % n_texcombo, data, off_texcombo)
        ) if n_texcombo else []

    @staticmethod
    def _read_vertices(data, off, count):
        """M2Vertex is 48 bytes: pos(12) weights(4) bones(4) normal(12) uv(8) uv2(8)."""
        out = []
        for i in range(count):
            p = off + i * 48
            px, py, pz = struct.unpack_from("<3f", data, p)
            nx, ny, nz = struct.unpack_from("<3f", data, p + 20)
            u, v = struct.unpack_from("<2f", data, p + 32)
            out.append((px, py, pz, nx, ny, nz, u, v))
        return out

    def dynamic_texture_slots(self):
        """Slots that carry the ITEM's own texture, by M2Texture.type == 2
        (TEX_COMPONENT_OBJECT_SKIN).

        The obvious-looking test -- TXID entry == 0, i.e. "not baked in" -- is
        wrong, and wrong in a way that quietly corrupts results. A zero only
        means the slot is bound at runtime; several runtime slots have nothing
        to do with the item's texture. Measured: visual 125498 has zeros at
        slots 3 and 5, but slot 3 is type 3 (weapon blade) and only slot 5 is
        the item skin, so keying on zeros weighted the helm's purple texture
        with a blade's geometry and turned it red. Visuals 80615 and 97767 were
        likewise pooling a type-3 slot alongside the real one.

        TXID zeros remain the fallback for models with no type-2 slot at all.
        """
        by_type = {i for i, t in enumerate(self.texture_types) if t == 2}
        if by_type:
            return by_type
        if self.texture_fdids:
            return {i for i, f in enumerate(self.texture_fdids) if f == 0}
        return {i for i, t in enumerate(self.texture_types) if t != 0}


class M2Skin:
    """.skin: the render geometry -- vertex indices, triangles, and the batches
    that say which texture slot each submesh draws with."""

    def __init__(self, data):
        if data[:4] != b"SKIN":
            raise M2ParseError(f"skin magic was {data[:4]!r}, expected SKIN")
        base = 0
        n_v, off_v = _array(data, base, 4)
        n_i, off_i = _array(data, base, 12)
        n_sub, off_sub = _array(data, base, 28)
        n_batch, off_batch = _array(data, base, 36)

        self.vertex_map = list(struct.unpack_from("<%dH" % n_v, data, off_v)) if n_v else []
        self.indices = list(struct.unpack_from("<%dH" % n_i, data, off_i)) if n_i else []

        # M2SkinSection, 48 bytes; only the index range is needed here.
        self.submeshes = []
        for i in range(n_sub):
            p = off_sub + i * 48
            index_start, index_count = struct.unpack_from("<2H", data, p + 8)
            self.submeshes.append((index_start, index_count))

        # M2Batch, 24 bytes.
        self.batches = []
        for i in range(n_batch):
            p = off_batch + i * 24
            skin_section = struct.unpack_from("<H", data, p + 4)[0]
            texture_combo_index = struct.unpack_from("<H", data, p + 16)[0]
            self.batches.append((skin_section, texture_combo_index))


def dynamic_slot_order(model, skin):
    """Dynamic texture slots that actually get drawn, in ascending slot order.

    Used to pair a resolved texture with the geometry that wears it: the object
    texture path reads ModelMaterialResourcesID_0/_1 in order, so the Nth
    resolved texture belongs to the Nth dynamic slot."""
    dynamic = model.dynamic_texture_slots()
    drawn = set()
    for _, combo_idx in skin.batches:
        if combo_idx < len(model.texture_combos):
            slot = model.texture_combos[combo_idx]
            if slot in dynamic:
                drawn.add(slot)
    return sorted(drawn)


def build_uv_weight_map(model, skin, resolution=128, only_dynamic=True, slot=None):
    """Splats each triangle's visibility weight into a `resolution`^2 UV grid.

    `slot` restricts the splat to submeshes drawn with that one texture slot.
    Passing it matters whenever a model has more than one dynamic slot: those
    slots are separate textures with separate UV layouts, so pooling them into
    one grid credits one surface's area to another surface's atlas. Measured on
    visual 125498 (two dynamic slots, four submeshes) that inverted the result,
    turning a purple helm red.

    Returns (grid, stats). grid[v][u] is accumulated visible area. The colour
    extractor samples this per texture pixel, so a texture region no visible
    triangle maps to contributes nothing.
    """
    verts = model.vertices
    if not verts or not skin.indices:
        return None, {"reason": "empty geometry"}

    xs = [v[0] for v in verts]
    ys = [v[1] for v in verts]
    zs = [v[2] for v in verts]
    centre = ((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2, (min(zs) + max(zs)) / 2)

    dynamic = model.dynamic_texture_slots()
    wanted_sections = set()
    for skin_section, tex_combo_idx in skin.batches:
        if not only_dynamic:
            wanted_sections.add(skin_section)
        elif tex_combo_idx < len(model.texture_combos):
            section_slot = model.texture_combos[tex_combo_idx]
            if slot is not None:
                if section_slot == slot:
                    wanted_sections.add(skin_section)
            elif section_slot in dynamic:
                wanted_sections.add(skin_section)

    grid = [[0.0] * resolution for _ in range(resolution)]
    total_area = 0.0
    kept_area = 0.0
    tri_count = 0

    for section_idx, (index_start, index_count) in enumerate(skin.submeshes):
        if section_idx not in wanted_sections:
            continue
        for t in range(index_start, index_start + index_count - 2, 3):
            try:
                a, b, c = (verts[skin.vertex_map[skin.indices[t + k]]] for k in range(3))
            except (IndexError, KeyError):
                continue
            tri_count += 1

            e1 = (b[0] - a[0], b[1] - a[1], b[2] - a[2])
            e2 = (c[0] - a[0], c[1] - a[1], c[2] - a[2])
            cx = e1[1] * e2[2] - e1[2] * e2[1]
            cy = e1[2] * e2[0] - e1[0] * e2[2]
            cz = e1[0] * e2[1] - e1[1] * e2[0]
            area = 0.5 * math.sqrt(cx * cx + cy * cy + cz * cz)
            if area <= 0:
                continue
            total_area += area

            nx = (a[3] + b[3] + c[3]) / 3
            ny = (a[4] + b[4] + c[4]) / 3
            nz = (a[5] + b[5] + c[5]) / 3
            nlen = math.sqrt(nx * nx + ny * ny + nz * nz) or 1.0
            nx, ny, nz = nx / nlen, ny / nlen, nz / nlen

            ox = (a[0] + b[0] + c[0]) / 3 - centre[0]
            oy = (a[1] + b[1] + c[1]) / 3 - centre[1]
            oz = (a[2] + b[2] + c[2]) / 3 - centre[2]
            olen = math.sqrt(ox * ox + oy * oy + oz * oz)
            if olen < 1e-6:
                facing = 1.0  # degenerate at the centre; don't punish it
            else:
                facing = (nx * ox + ny * oy + nz * oz) / olen
            if facing <= 0:
                continue  # faces inward: lining, underside, interior
            weight = area * facing
            kept_area += area

            _splat_uv_triangle(grid, resolution, a[6], a[7], b[6], b[7], c[6], c[7], weight)

    stats = {
        "triangles": tri_count,
        "total_area": total_area,
        "kept_area": kept_area,
        "kept_fraction": (kept_area / total_area) if total_area else 0.0,
        "sections_used": len(wanted_sections),
        "sections_total": len(skin.submeshes),
    }
    return grid, stats


def _splat_uv_triangle(grid, res, u1, v1, u2, v2, u3, v3, weight):
    """Rasterises the UV triangle, distributing `weight` over covered cells.

    Coverage is tested barycentrically at each cell centre rather than over the
    triangle's bounding box. That distinction is not cosmetic: a bounding-box
    splat leaks weight into UV regions the triangle never touches, and on a
    thin diagonal triangle the box can be several times the real footprint.
    It showed up as an appearance whose primary colour swung purple -> red
    while 91% of its geometry was retained -- weight bleeding across a UV
    seam into an unrelated part of the atlas.

    Weight is area-proportional (each covered cell gets an equal share of the
    triangle's weight), so the grid stays an honest 'visible area per texel'.
    """
    ax, ay = u1 * res, v1 * res
    bx, by = u2 * res, v2 * res
    cx, cy = u3 * res, v3 * res

    min_u, max_u = int(math.floor(min(ax, bx, cx))), int(math.ceil(max(ax, bx, cx)))
    min_v, max_v = int(math.floor(min(ay, by, cy))), int(math.ceil(max(ay, by, cy)))

    denom = (by - cy) * (ax - cx) + (cx - bx) * (ay - cy)
    if abs(denom) < 1e-12:
        return  # degenerate in UV space: zero texture footprint

    cells = []
    for vv in range(min_v, max_v + 1):
        py = vv + 0.5
        for uu in range(min_u, max_u + 1):
            px = uu + 0.5
            l1 = ((by - cy) * (px - cx) + (cx - bx) * (py - cy)) / denom
            l2 = ((cy - ay) * (px - cx) + (ax - cx) * (py - cy)) / denom
            l3 = 1.0 - l1 - l2
            if l1 >= -1e-9 and l2 >= -1e-9 and l3 >= -1e-9:
                cells.append((uu % res, vv % res))

    if not cells:
        # Triangle smaller than a texel and straddling no centre. Drop it on the
        # single cell containing its centroid so its weight isn't silently lost.
        cells = [(int((ax + bx + cx) / 3) % res, int((ay + by + cy) / 3) % res)]

    share = weight / len(cells)
    for uu, vv in cells:
        grid[vv][uu] += share
