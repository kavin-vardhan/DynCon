"""`rival3` — the rival's large content for region 3, size class L (spec v1 §3).

v1 only. "Barrel-vault hall" ~12 x 10 m, 7 m to the crown. Low side walls carry a segmental
vault whose underside IS the room's ceiling, so walking in you are under the arch rather than
under a flat slab. The two end walls close the arch with a solid tympanum; the front one
carries the sign, framed by a brand-coloured archivolt that follows the arch.

The vault is one extrusion with per-edge materials (`side_mats`): roof outside, interior
finish inside. Group-A fixtures hang from stems, because the ceiling height changes with x.
"""

import math

import dc_kit as K
from dc_kit import MeshBuilder as MB

HX = 6.00                       # outer face of the side walls
HY = 5.00                       # outer face of the end walls
TE = 0.30                       # end wall thickness
SPRING = 3.60                   # top of the side walls = springing of the vault
CROWN = 7.00                    # outside of the crown
TV = 0.30                       # vault thickness

_H = CROWN - SPRING
R_OUT = (_H * _H + HX * HX) / (2 * _H)
Z_C = CROWN - R_OUT                                     # centre of the arcs
R_IN = R_OUT - TV
X_IN = math.sqrt(R_IN * R_IN - (SPRING - Z_C) ** 2)     # inner face of the side walls
TS = HX - X_IN                                          # side wall thickness
TH_OUT = math.degrees(math.atan2(SPRING - Z_C, HX))
TH_IN = math.degrees(math.atan2(SPRING - Z_C, X_IN))
CREST_IN = Z_C + R_IN

VAULT_Y = HY + 0.30             # the vault oversails both end walls
NSEG = 22                       # flat shaded, plenty of facets (spec call 9 of brief 003)
# segs that make `ring` land on exactly the same angular stations as the vault's own facets,
# so a rib or the archivolt sits flat on the arch instead of cutting across it
RIB_SEGS = NSEG * 360.0 / (180.0 - 2 * TH_OUT)

DOOR_W, DOOR_HEAD = 1.80, 2.95
SIGN_Z = 5.00
FIT_TOP = 4.60                  # where the group-A fixtures hang

VERSIONS = ("v1",)


def _vault(P):
    """The barrel itself: inner arc left to right, then back along the outer arc."""
    inner = MB.arc2d(0.0, Z_C, R_IN, NSEG, 180.0 - TH_IN, -(180.0 - 2 * TH_IN))
    outer = MB.arc2d(0.0, Z_C, R_OUT, NSEG, TH_OUT, 180.0 - 2 * TH_OUT)
    mats = (["M_WallInterior"] * NSEG + ["M_Trim"] + ["M_Roof"] * NSEG + ["M_Trim"])
    P.extrude(inner + outer, "xz", -VAULT_Y, VAULT_Y, "M_Roof",
              cap_mat="M_Trim", side_mats=mats)
    for y in (-2.10, 2.10):     # purlin ribs across the back of the vault
        P.sb.ring((0.0, Z_C), R_OUT, R_OUT + 0.07, "xz", y - 0.09, y + 0.09, "M_Trim",
                  segs=RIB_SEGS, start_deg=TH_OUT, span_deg=180.0 - 2 * TH_OUT)


def _tympanum(P, y0, y1, *, cap_a, cap_b, mat="M_Wall"):
    """The solid crescent that closes the arch at one end of the barrel.

    cap_a is the face at y0 (looking -Y), cap_b the face at y1 (looking +Y).
    """
    prof = ([(-X_IN, SPRING), (X_IN, SPRING)]
            + MB.arc2d(0.0, Z_C, R_IN, NSEG, TH_IN, 180.0 - 2 * TH_IN))
    P.extrude(prof, "xz", y0, y1, mat, cap_a_mat=cap_a, cap_b_mat=cap_b)


def build(version):
    P = K.Piece("rival3", version, "L")
    P.notes.append("The vault underside is the ceiling: there is no flat soffit, so the "
                   "group-A fixtures hang on stems and VOLUME_Interior is the biggest box "
                   "that fits under the arch, not the whole floor area.")

    floor_top = P.plinth(HX, HY, skirt=0.24, base_h=0.09, deck_h=0.05)
    ix0, ix1 = -X_IN, X_IN
    iy0, iy1 = -HY + TE, HY - TE

    # ---------------------------------------------------------------- walls
    front = [dict(center=0.0, width=DOOR_W, sill=0.0, head=DOOR_HEAD)] + \
            [dict(center=sx * 3.60, width=1.80, sill=1.15, head=3.40) for sx in (-1, 1)]
    P.wall_run(along="x", outer=-HY, out_sign=-1, t=TE, a=-HX, b=HX, z0=0.0, z1=SPRING,
               openings=front)
    for o in front[1:]:
        P.window(along="x", outer=-HY, out_sign=-1, t=TE, center=o["center"], width=o["width"],
                 sill=o["sill"], head=o["head"], mullions=1)

    back = [dict(center=sx * 4.30, width=1.80, sill=1.15, head=3.40) for sx in (-1, 1)]
    P.wall_run(along="x", outer=HY, out_sign=1, t=TE, a=-HX, b=HX, z0=0.0, z1=SPRING,
               openings=back)
    for o in back:
        P.window(along="x", outer=HY, out_sign=1, t=TE, center=o["center"], width=o["width"],
                 sill=o["sill"], head=o["head"], mullions=1)

    side = [(c, 2.40, 1.15, 3.40) for c in (-2.80, 2.80)]
    for sx in (-1, 1):
        P.wall_run(along="y", outer=sx * HX, out_sign=sx, t=TS, a=-HY + TE / 2, b=HY - TE / 2,
                   z0=0.0, z1=SPRING,
                   openings=[dict(center=c, width=w, sill=s, head=h) for (c, w, s, h) in side])
        for (c, w, s, h) in side:
            P.window(along="y", outer=sx * HX, out_sign=sx, t=TS, center=c, width=w,
                     sill=s, head=h, mullions=2)
        P.panel_joints(along="y", outer=sx * HX, out_sign=sx, a=-HY + 0.5, b=HY - 0.5,
                       z0=0.55, z1=SPRING - 0.20, pitch=1.25,
                       skip=[(c - w / 2 - 0.35, c + w / 2 + 0.35) for (c, w, s, h) in side])
    P.base_course(HX, HY, 0.04, 0.50, skip_front=(-1.5, 1.5))

    # ---------------------------------------------------------------- vault and ends
    _vault(P)
    _tympanum(P, -HY, -HY + TE, cap_a="M_Wall", cap_b="M_WallInterior")
    _tympanum(P, HY - TE, HY, cap_a="M_WallInterior", cap_b="M_Wall")
    for y0, y1 in ((-VAULT_Y - 0.12, -VAULT_Y), (VAULT_Y, VAULT_Y + 0.12)):
        P.sb.ring((0.0, Z_C), R_OUT - 0.10, R_OUT + 0.12, "xz", y0, y1, "M_BrandAccent",
                  segs=RIB_SEGS, start_deg=TH_OUT, span_deg=180.0 - 2 * TH_OUT)

    # ---------------------------------------------------------------- entrance
    P.add_door(hinge=(-DOOR_W / 2, -HY + TE / 2, floor_top),
               width=DOOR_W, height=DOOR_HEAD - floor_top, open_sign=1)
    P.door_frame(along="x", outer=-HY, out_sign=-1, t=TE, center=0.0, width=DOOR_W,
                 head=DOOR_HEAD, mat="M_BrandAccent", w=0.17, proud=0.06)
    for sx in (-1, 1):
        P.wall_lamp((sx * 1.36, -HY, 2.30), (0.0, -1.0, 0.0))
    P.add_sign((0.0, -HY, SIGN_Z), (0.0, -1.0, 0.0), depth=0.13)

    P.entrance_step(center_x=0.0, y_out=-5.80, y_in=-HY + 0.06, half_w=1.55, z_top=floor_top)
    P.entrance_mat(center_x=0.0, y0=-5.56, y1=-5.30, half_w=0.98, z=floor_top)
    for sx in (-1, 1):
        P.planter((sx * 3.10, -5.50), size=(1.20, 0.80), h=0.58)
    for sx in (-1, 1):
        P.downpipe(sx * (HX + 0.10), HY - 0.45, 0.10, SPRING - 0.25)

    # ---------------------------------------------------------------- interior
    P.standard_interior(lo=(ix0, iy0, floor_top), hi=(ix1, iy1, FIT_TOP),
                        door_center_x=0.0, lights_a=(3, 3), light_b_z=2.55, layout="a",
                        side_light_f=0.50,
                        light_a_stem=lambda x, y: Z_C + math.sqrt(max(0.0, R_IN * R_IN - x * x)),
                        tall_avoid=[(c - w / 2 - 0.35, c + w / 2 + 0.35)
                                    for (c, w, s, h) in side],
                        volume=((-4.40, iy0, floor_top), (4.40, iy1, 5.00)))
    P.preview_int = ((-0.40, iy0 + 0.50, floor_top + 1.72), (0.15, iy1 - 0.10, floor_top + 3.10))
    P.standard_markers(roof_top=CROWN, front_y=-HY)
    return P
