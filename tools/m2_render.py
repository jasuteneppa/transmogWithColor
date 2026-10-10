"""Rasterises an item's M2 into screen space, so a human can look at it.

Sibling to m2_geometry, and deliberately the same walk over the same triangles
in the opposite direction. m2_geometry splats each triangle INTO UV SPACE to
answer "how much visible surface lands on this texel". This projects the same
triangles onto a screen, z-buffers them, samples the texture and applies a
light, to answer "what does this look like".

WHAT THIS IS FOR. Not colour extraction -- that was tried and does not work.
Measured on 220 labelled appearances, reading colour off a lit render scored
25.0% against 22.7% for the shipped texture path: 15 fixes against 10 breaks,
which is a coin flip (p ~ 0.42). Worse, the mechanism was spurious. Lighting
drags the median value from 0.52 to 0.29, which pushes appearances into the
black bucket, and black is the largest label group -- so `black` went 3% -> 22%
while `white` went 43% -> 0%. That is exploiting the answer key's shape, not
seeing better. Do not wire this into generate_color_data.

It IS how you look at 300 items in an afternoon, which is what label_sheets.py
does with it, and which is the thing the project has never had.

One genuinely useful result did come out of that test: rendering with the light
turned OFF reproduces the shipped UV-weighted result almost exactly (22.3% vs
22.7%, 6 fixes and 7 breaks). m2_geometry's visibility approximation is sound,
and that is now checked rather than assumed.

COVERAGE LIMIT, and it is a big one. Only items with their own model can be
rendered -- cloaks, shoulders, helms, weapons. Chests, legs, gloves and boots
are component textures painted onto the character body, and resolve_model_fdid
deliberately returns 0 for those (see its docstring). So a sample drawn from
what this can draw is heavily weighted toward weapons and skews away from the
armour that matters most. Keep that in mind when labelling: it is a reason to
label the component slots by hand in game, not a reason to trust a sheet as
representative.
"""

import numpy as np
from PIL import Image

import generate_color_data as g
import m2_geometry as m2

RES = 256

# A three-quarter front view, slightly above eye level -- roughly how an item
# sits in the dressing room, and chosen so left/right asymmetry stays visible.
VIEW = np.array([0.55, -0.78, 0.30])
# Key light over the viewer's shoulder. WoW's character lighting is flat and
# frontal; a raking light would carve shadows the game never shows.
LIGHT = np.array([0.40, -0.72, 0.57])
AMBIENT, DIFFUSE = 0.55, 0.75


def _basis(view):
    f = view / np.linalg.norm(view)
    r = np.cross(f, np.array([0.0, 0.0, 1.0]))
    r /= np.linalg.norm(r)
    return r, np.cross(r, f), f


def load_model(model_fdid, session=None):
    """(M2Model, M2Skin) from the local caches. Raises on an unparseable file."""
    model = m2.M2Model(g.fetch_casc_file(model_fdid, session))
    if not model.skin_fdids:
        return None, None
    return model, m2.M2Skin(g.fetch_casc_file(model.skin_fdids[0], session))


def resolve(visual_id, ia, di, mbd, tbm, mbdisp, session=None):
    """(model, skin, {slot: texture array}) for a renderable item, else Nones.

    The slot/texture pairing mirrors build_weight_grid exactly: the Nth resolved
    texture belongs to the Nth DRAWN DYNAMIC slot. Getting that wrong does not
    fail loudly, it silently paints one surface with another surface's atlas --
    the failure that turned a purple helm red when the weight grid had the same
    bug.
    """
    model_fdid = g.resolve_model_fdid(visual_id, ia, di, mbd, mbdisp)
    if not model_fdid:
        return None, None, None  # component slot: no model of its own
    fdids = g.resolve_texture_fdids(visual_id, ia, di, mbd, tbm)
    if not fdids:
        return None, None, None
    try:
        model, skin = load_model(model_fdid, session)
    except Exception:  # noqa: BLE001 - one bad model must not stop a sheet
        return None, None, None
    if model is None:
        return None, None, None

    slots = m2.dynamic_slot_order(model, skin)
    textures = {}
    for i, slot in enumerate(slots):
        if i < len(fdids):
            try:
                textures[slot] = np.asarray(g.fetch_texture(fdids[i], session).convert("RGBA"))
            except Exception:  # noqa: BLE001
                pass
    return (model, skin, textures) if textures else (None, None, None)


def render(model, skin, textures, res=RES, exposure=1.0, lit=True):
    """An RGBA image of the item, transparent where no geometry covers, or None.

    Alpha is coverage, not the texture's alpha -- a caller compositing this onto
    a background wants the silhouette. Texture alpha is still honoured per-pixel
    (cut-outs stay cut out); those pixels simply end up uncovered.
    """
    verts = np.array(model.vertices, dtype=np.float64)
    if len(verts) == 0 or not skin.indices:
        return None

    slot_of_section = {}
    for section, combo in skin.batches:
        if combo < len(model.texture_combos):
            slot_of_section.setdefault(section, model.texture_combos[combo])

    tris, uvs, norms, slots = [], [], [], []
    for si, (start, count) in enumerate(skin.submeshes):
        slot = slot_of_section.get(si)
        if slot is None or slot not in textures:
            continue
        for t in range(start, start + count - 2, 3):
            try:
                idx = [skin.vertex_map[skin.indices[t + k]] for k in range(3)]
            except (IndexError, KeyError):
                continue
            v = verts[idx]
            tris.append(v[:, 0:3]); norms.append(v[:, 3:6]); uvs.append(v[:, 6:8])
            slots.append(slot)
    if not tris:
        return None
    tris, norms, uvs = np.array(tris), np.array(norms), np.array(uvs)

    flat = tris.reshape(-1, 3)
    centre = (flat.min(0) + flat.max(0)) / 2
    right, up, fwd = _basis(VIEW)
    sx, sy, dz = (tris - centre) @ right, (tris - centre) @ up, (tris - centre) @ fwd
    # Orthographic, fitted to the bounding box: items differ hugely in scale
    # (a ring vs a two-hander) and a fixed FOV would render most of them tiny.
    scale = (res - 8) / (max(np.ptp(sx), np.ptp(sy)) or 1.0)
    px, py = sx * scale + res / 2, res / 2 - sy * scale

    L = LIGHT / np.linalg.norm(LIGHT)
    n = norms / (np.linalg.norm(norms, axis=2, keepdims=True) + 1e-9)
    shade = AMBIENT + DIFFUSE * np.clip(n @ L, 0, None) if lit else np.ones(n.shape[:2])

    zbuf = np.full((res, res), np.inf)
    out = np.zeros((res, res, 3), np.float64)
    cov = np.zeros((res, res), bool)

    for i in range(len(tris)):
        ax, ay, bx, by, cx, cy = px[i, 0], py[i, 0], px[i, 1], py[i, 1], px[i, 2], py[i, 2]
        den = (by - cy) * (ax - cx) + (cx - bx) * (ay - cy)
        if abs(den) < 1e-9:
            continue  # degenerate on screen
        x0, x1 = int(max(0, np.floor(min(ax, bx, cx)))), int(min(res - 1, np.ceil(max(ax, bx, cx))))
        y0, y1 = int(max(0, np.floor(min(ay, by, cy)))), int(min(res - 1, np.ceil(max(ay, by, cy))))
        if x1 < x0 or y1 < y0:
            continue
        Y, X = np.mgrid[y0:y1 + 1, x0:x1 + 1]
        Xc, Yc = X + 0.5, Y + 0.5
        l1 = ((by - cy) * (Xc - cx) + (cx - bx) * (Yc - cy)) / den
        l2 = ((cy - ay) * (Xc - cx) + (ax - cx) * (Yc - cy)) / den
        l3 = 1.0 - l1 - l2
        m = (l1 >= 0) & (l2 >= 0) & (l3 >= 0)
        if not m.any():
            continue
        z = l1 * dz[i, 0] + l2 * dz[i, 1] + l3 * dz[i, 2]
        near = zbuf[y0:y1 + 1, x0:x1 + 1]
        m &= z < near
        if not m.any():
            continue
        u = l1 * uvs[i, 0, 0] + l2 * uvs[i, 1, 0] + l3 * uvs[i, 2, 0]
        v = l1 * uvs[i, 0, 1] + l2 * uvs[i, 1, 1] + l3 * uvs[i, 2, 1]
        tex = textures[slots[i]]
        th, tw = tex.shape[0], tex.shape[1]
        texel = tex[np.clip((v % 1.0) * th, 0, th - 1).astype(int),
                    np.clip((u % 1.0) * tw, 0, tw - 1).astype(int)]
        m &= texel[:, :, 3] > g.ALPHA_THRESHOLD
        if not m.any():
            continue
        sh = l1 * shade[i, 0] + l2 * shade[i, 1] + l3 * shade[i, 2]
        rgb = np.clip(texel[:, :, :3] * (sh * exposure)[:, :, None], 0, 255)

        near[m] = z[m]
        zbuf[y0:y1 + 1, x0:x1 + 1] = near
        blk = out[y0:y1 + 1, x0:x1 + 1]; blk[m] = rgb[m]
        out[y0:y1 + 1, x0:x1 + 1] = blk
        cvb = cov[y0:y1 + 1, x0:x1 + 1]; cvb[m] = True
        cov[y0:y1 + 1, x0:x1 + 1] = cvb

    if cov.sum() < 200:
        return None  # nothing meaningful drawn; a caller should skip this item
    rgba = np.zeros((res, res, 4), np.uint8)
    rgba[:, :, :3] = out.astype(np.uint8)
    rgba[:, :, 3] = np.where(cov, 255, 0)
    return Image.fromarray(rgba, "RGBA")
