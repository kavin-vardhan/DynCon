"""`rival2` — the rival's large content for region 2, size class L (spec v1 §3).

v1 only. "Hexagonal pavilion" ~12.5 m across the corners, with a folded six-sided roof to
~7.5 m and a brand band under the eaves. Full walk-in set like every other piece.

The hexagon is built facet by facet rather than as one ring, because a window has to be a real
hole in a flat wall: a ring arc that stops part way along a facet would bulge out past it.
`_facet_wall` is `wall_run` done in the facet's own frame — segments either side of each
opening, under its sill and over its head.
"""

import math

import dc_kit as K
from dc_kit import MeshBuilder as MB

R_OUT = 6.20                                    # circumradius, outer
TP = 0.28                                       # wall thickness, measured on the facet
R_IN = R_OUT - TP / math.cos(math.radians(30.0))
A_OUT = R_OUT * math.cos(math.radians(30.0))    # outer face distance from the centre
A_IN = R_IN * math.cos(math.radians(30.0))
HALF = R_OUT * math.sin(math.radians(30.0))     # half width of a facet

WALL_TOP, CEIL_UNDER = 5.60, 5.35
EAVE_R, ROOF_SHOULDER, APEX = 6.85, 7.26, 7.56
DOOR_W, DOOR_HEAD = 1.80, 2.90
SIGN_Z = 3.95
FRONT, BACK = 270.0, 90.0

VERSIONS = ("v1",)


def _on_facet(P, ang, u0, u1, r0, r1, z0, z1, mat, side_mats=None):
    """A box standing on the facet whose outward normal points `ang` degrees from +X.

    u is measured along the facet from its centre, r outward from the hexagon's centre.
    """
    if u1 - u0 < 1e-6 or r1 - r0 < 1e-6 or z1 - z0 < 1e-6:
        return
    rect = [(u0, r0), (u1, r0), (u1, r1), (u0, r1)]
    P.extrude(MB.rot2d(rect, ang - 90.0), "xy", z0, z1, mat, side_mats=side_mats)


def _facet_wall(P, ang, *, z0, z1, openings=(), half=HALF, r0=A_IN, r1=A_OUT,
                mat="M_Wall", in_mat="M_WallInterior", jamb="M_Trim"):
    """One facet, segmented round its openings. `openings` are (centre, width, sill, head)."""
    mats = [in_mat, jamb, mat, jamb]        # inner face, +u end, outer face, -u end

    def emit(u0, u1, za, zb):
        _on_facet(P, ang, u0, u1, r0, r1, za, zb, mat, side_mats=mats)

    cursor = -half
    for (c, w, sill, head) in sorted(openings, key=lambda o: o[0]):
        u0, u1 = c - w / 2, c + w / 2
        emit(cursor, u0, z0, z1)
        emit(u0, u1, z0, max(z0, sill))
        emit(u0, u1, min(z1, head), z1)
        cursor = u1
    emit(cursor, half, z0, z1)


def _facet_window(P, ang, c, w, sill, head, *, mullions=2):
    """Glass, inner frame and a surround standing proud, in an opening left by _facet_wall."""
    mid = (A_IN + A_OUT) / 2
    u0, u1 = c - w / 2, c + w / 2
    _on_facet(P, ang, u0, u1, mid - 0.02, mid + 0.02, sill, head, "M_Glass")
    for (a, b, za, zb) in ((u0, u0 + 0.06, sill, head), (u1 - 0.06, u1, sill, head),
                           (u0, u1, sill, sill + 0.06), (u0, u1, head - 0.06, head)):
        _on_facet(P, ang, a, b, mid - 0.05, mid + 0.05, za, zb, "M_Trim")
    for i in range(1, mullions + 1):
        g = u0 + (u1 - u0) * i / (mullions + 1)
        _on_facet(P, ang, g - 0.035, g + 0.035, mid - 0.04, mid + 0.04, sill, head, "M_Trim")
    for (a, b, za, zb) in ((u0 - 0.10, u0, sill - 0.10, head + 0.10),
                           (u1, u1 + 0.10, sill - 0.10, head + 0.10),
                           (u0, u1, sill - 0.10, sill), (u0, u1, head, head + 0.10)):
        _on_facet(P, ang, a, b, A_OUT - 0.02, A_OUT + 0.05, za, zb, "M_Trim")


def _facet_point(ang, u, r):
    """World (x, y) of a point on a facet: r out from the centre, u along it (same frame
    as _on_facet, which rotates its (u, r) rectangle by ang - 90)."""
    a = math.radians(ang)
    return (r * math.cos(a) + u * math.sin(a), r * math.sin(a) - u * math.cos(a))


def build(version):
    P = K.Piece("rival2", version, "L")
    P.notes.append("Six facets: the front one is flat to -Y so the door, the sign and the "
                   "brand band sit on straight wall; the back one carries the screen.")

    floor_top = P.round_plinth(R_OUT, segs=6, skirt=0.24)

    # ---------------------------------------------------------------- walls
    windows = {210.0: (0.0, 2.80, 1.25, 3.50), 330.0: (0.0, 2.80, 1.25, 3.50),
               150.0: (0.0, 2.20, 1.25, 3.50), 30.0: (0.0, 2.20, 1.25, 3.50)}
    _facet_wall(P, FRONT, z0=0.0, z1=WALL_TOP,
                openings=[(0.0, DOOR_W, 0.0, DOOR_HEAD)])
    _facet_wall(P, BACK, z0=0.0, z1=WALL_TOP)
    for ang, (c, w, sill, head) in sorted(windows.items()):
        _facet_wall(P, ang, z0=0.0, z1=WALL_TOP, openings=[(c, w, sill, head)])
        _facet_window(P, ang, c, w, sill, head, mullions=2)
        _on_facet(P, ang, -HALF + 0.35, -HALF + 0.42, A_OUT - 0.02, A_OUT + 0.04,
                  0.55, WALL_TOP - 0.30, "M_Trim")
        _on_facet(P, ang, HALF - 0.42, HALF - 0.35, A_OUT - 0.02, A_OUT + 0.04,
                  0.55, WALL_TOP - 0.30, "M_Trim")
    P.panel_joints(along="x", outer=A_OUT, out_sign=1, a=-2.2, b=2.2,
                   z0=0.55, z1=WALL_TOP - 0.30, pitch=1.1)
    for u in (-2.50, -1.70, 1.70, 2.50):         # front facet, either side of the door
        _on_facet(P, FRONT, u - 0.035, u + 0.035, A_OUT - 0.02, A_OUT + 0.04,
                  0.55, WALL_TOP - 0.30, "M_Trim")

    # base course, brand band and cornice: full rings, so they land exactly on the six corners
    P.sb.ring((0.0, 0.0), R_OUT - 0.02, R_OUT + 0.07, "xy", 0.04, 0.50, "M_Trim", segs=6)
    P.sb.ring((0.0, 0.0), R_OUT - 0.03, R_OUT + 0.09, "xy", 4.86, 5.22, "M_BrandAccent", segs=6)
    P.sb.ring((0.0, 0.0), R_IN - 0.05, R_OUT + 0.12, "xy", 5.38, WALL_TOP, "M_Trim", segs=6)

    # ---------------------------------------------------------------- roof
    P.sb.disc((0.0, 0.0), R_IN + 0.02, "xy", CEIL_UNDER, WALL_TOP - 0.18, "M_Trim",
              segs=6, cap_mat="M_WallInterior")
    P.sb.ring((0.0, 0.0), 6.58, 6.92, "xy", WALL_TOP - 0.22, WALL_TOP - 0.02, "M_Trim", segs=6)
    P.sb.cone((0.0, 0.0), EAVE_R, WALL_TOP - 0.06, ROOF_SHOULDER, "M_Roof", segs=6, r_top=0.95)
    P.sb.disc((0.0, 0.0), 1.02, "xy", ROOF_SHOULDER, ROOF_SHOULDER + 0.18, "M_Trim", segs=6)
    P.sb.cone((0.0, 0.0), 1.10, ROOF_SHOULDER + 0.18, APEX, "M_Roof", segs=6)
    for v in (0.0, 60.0, 120.0, 180.0):          # on the corners, never across a window
        a = math.radians(v)
        P.downpipe((R_OUT + 0.08) * math.cos(a), (R_OUT + 0.08) * math.sin(a),
                   0.10, WALL_TOP - 0.40)

    # ---------------------------------------------------------------- entrance
    P.add_door(hinge=(-DOOR_W / 2, -A_OUT + TP / 2, floor_top),
               width=DOOR_W, height=DOOR_HEAD - floor_top, open_sign=1)
    P.door_frame(along="x", outer=-A_OUT, out_sign=-1, t=TP, center=0.0, width=DOOR_W,
                 head=DOOR_HEAD, mat="M_BrandAccent", w=0.17, proud=0.06)
    for sx in (-1, 1):
        P.wall_lamp((sx * 1.36, -A_OUT, 2.30), (0.0, -1.0, 0.0))
    P.add_sign((0.0, -A_OUT, SIGN_Z), (0.0, -1.0, 0.0), depth=0.13)

    P.entrance_step(center_x=0.0, y_out=-6.08, y_in=-A_OUT + 0.06, half_w=1.55, z_top=floor_top)
    P.entrance_mat(center_x=0.0, y0=-5.84, y1=-5.58, half_w=0.98, z=floor_top)
    for sx in (-1, 1):
        P.planter((sx * 3.40, -5.72), size=(1.20, 0.80), h=0.58)

    # ---------------------------------------------------------------- interior
    P.sb.ring((0.0, 0.0), R_IN - 0.04, R_IN, "xy", floor_top, floor_top + 0.13, "M_Trim", segs=6)
    P.sb.ring((0.0, 0.0), R_IN - 1.00, R_IN - 0.86, "xy", floor_top, floor_top + 0.012,
              "M_Trim", segs=6)
    P.box((-P.PATH_HALF, -A_IN, floor_top), (P.PATH_HALF, A_IN, floor_top + 0.008),
          "M_WallInterior")
    for ang in (150.0, 210.0):
        x, y = _facet_point(ang, 0.0, A_IN)
        P.wall_lamp((x, y, 2.45), (-math.cos(math.radians(ang)), -math.sin(math.radians(ang)), 0.0))

    P.standard_interior(lo=(-2.90, -3.20, floor_top), hi=(2.90, A_IN, CEIL_UNDER),
                        door_center_x=0.0, lights_a=(2, 3), light_b_z=2.55, layout="b",
                        floor=False, skirt=False, side_lights=False,
                        switch_surface=(0.99, -A_IN), screen_z=2.05)
    P.preview_int = ((-0.35, -4.55, floor_top + 1.74), (0.15, A_IN - 0.1, floor_top + 2.75))
    P.standard_markers(roof_top=APEX, front_y=-A_OUT)
    return P
