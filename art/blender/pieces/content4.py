"""`content4` — small uploadable content, size class S, fits every slot (spec v1 §3).

v1  "Cabin": 6 x 5 m, gable roof, door on the gable end, a rectangular window each side.
v2  Mono-pitch (shed) roof, porch on columns with a solid sign upstand, round windows.

Both versions share the same footprint, the same interior box and the same socket set, so the
state kept across an update (lights A/B, door, screen image) carries over unchanged. The
interior layout and the palette differ, so the swap reads from across the booth.
"""

import dc_kit as K

HX, HY, T = 3.0, 2.5, 0.22          # 6 x 5 m footprint, 0.22 m walls
WALL_TOP = 4.25
CEIL_UNDER = 4.05
RIDGE = 4.90                        # v1 gable
SHED_LOW, SHED_HIGH = 4.35, 4.95    # v2 mono-pitch
DOOR_W, DOOR_HEAD = 1.70, 2.75
WIN_Z = 2.05                        # centre height of the v2 round windows
SIGN_Z = 3.57                       # v1, on the front wall, clear of the door frame

VERSIONS = ("v1", "v2")


def _shell(P, *, round_windows, layout):
    """Everything both versions share: plinth, four walls, ceiling, door, interior."""
    floor_top = P.plinth(HX, HY, skirt=0.18, base_h=0.09, deck_h=0.05)
    ix0, ix1 = -HX + T, HX - T
    iy0, iy1 = -HY + T, HY - T

    # front (-Y) gable end: door plus a window either side. They go here and not on the back
    # wall because the back wall is where the screen and its two fixtures live.
    front = [dict(center=0.0, width=DOOR_W, sill=0.0, head=DOOR_HEAD)] + \
            [dict(center=sx * 2.05, width=1.00, sill=1.15, head=2.55) for sx in (-1, 1)]
    P.wall_run(along="x", outer=-HY, out_sign=-1, t=T, a=-HX, b=HX, z0=0.0, z1=WALL_TOP,
               openings=front)
    for o in front[1:]:
        P.window(along="x", outer=-HY, out_sign=-1, t=T, center=o["center"], width=o["width"],
                 sill=o["sill"], head=o["head"], mullions=0, surround=0.08)
    # back (+Y) gable end: solid, with a panel rhythm outside
    P.wall_run(along="x", outer=HY, out_sign=1, t=T, a=-HX, b=HX, z0=0.0, z1=WALL_TOP)
    P.panel_joints(along="x", outer=HY, out_sign=1, a=-HX + 0.35, b=HX - 0.35,
                   z0=0.46, z1=WALL_TOP - 0.10, pitch=1.15)

    # the two long side walls, inset by half a wall so they bury into the gable ends
    side_ops = ([P.round_window_opening(WIN_Z)] if round_windows
                else [dict(center=0.0, width=1.60, sill=1.10, head=2.70)])
    for sx in (-1, 1):
        ops = side_ops
        P.wall_run(along="y", outer=sx * HX, out_sign=sx, t=T,
                   a=-HY + T / 2, b=HY - T / 2, z0=0.0, z1=WALL_TOP, openings=ops)
        if round_windows:
            P.round_window(along="y", outer=sx * HX, out_sign=sx, t=T, center=0.0, z=WIN_Z)
        else:
            P.window(along="y", outer=sx * HX, out_sign=sx, t=T,
                     center=0.0, width=1.60, sill=1.10, head=2.70)
        P.panel_joints(along="y", outer=sx * HX, out_sign=sx, a=-HY + 0.35, b=HY - 0.35,
                       z0=0.46, z1=WALL_TOP - 0.10, pitch=1.15, skip=((-1.25, 1.25),))

    P.ceiling((ix0, iy0), (ix1, iy1), CEIL_UNDER, WALL_TOP)
    P.base_course(HX, HY, floor_top - 0.02, floor_top + 0.30, skip_front=(-1.20, 1.20))

    P.add_door(hinge=(-DOOR_W / 2, -HY + T / 2, floor_top),
               width=DOOR_W, height=DOOR_HEAD - floor_top, open_sign=1)
    # the door surround IS the brand accent — solid wall, never glass
    P.door_frame(along="x", outer=-HY, out_sign=-1, t=T, center=0.0, width=DOOR_W,
                 head=DOOR_HEAD, mat="M_BrandAccent", w=0.15, proud=0.055)
    for sx in (-1, 1):
        P.wall_lamp((sx * 1.30, -HY, 2.25), (0.0, -1.0, 0.0))

    P.standard_interior(lo=(ix0, iy0, floor_top), hi=(ix1, iy1, CEIL_UNDER),
                        door_center_x=0.0, lights_a=(2, 1), light_b_z=2.25, layout=layout,
                        side_light_f=0.84,
                        tall_avoid=[(o["center"] - o["width"] / 2 - 0.25,
                                     o["center"] + o["width"] / 2 + 0.25) for o in side_ops])
    return floor_top


def build(version):
    if version == "v1":
        return _v1()
    if version == "v2":
        return _v2()
    raise ValueError("content4 has no %s" % version)


# ----------------------------------------------------------------------------------- v1
def _v1():
    P = K.Piece("content4", "v1", "S")
    P.notes.append("Gable ridge is 4.90 m (spec says ~4.6): a flat 4.05 m ceiling clears 3.5 m "
                   "and the sign band still fits on solid wall above the door frame.")
    floor_top = _shell(P, round_windows=False, layout="a")

    # solid gable roof: no gap is possible between wall top and roof underside
    P.roof_prism([(-HX - 0.26, WALL_TOP - 0.06), (0.0, RIDGE), (HX + 0.26, WALL_TOP - 0.06)],
                 "xz", -HY - 0.22, HY + 0.22)

    P.entrance_step(center_x=0.0, y_out=-2.98, y_in=-HY + 0.06, half_w=1.05, z_top=floor_top)
    P.entrance_mat(center_x=0.0, y0=-2.80, y1=-2.62, half_w=0.72, z=floor_top)
    for sx in (-1, 1):
        P.planter((sx * 2.20, -2.78), size=(1.05, 0.70), h=0.54)

    P.add_sign((0.0, -HY, SIGN_Z), (0.0, -1.0, 0.0))
    P.standard_markers(roof_top=RIDGE, front_y=-HY)
    return P


# ----------------------------------------------------------------------------------- v2
def _v2():
    P = K.Piece("content4", "v2", "S")
    P.notes.append("Same footprint, interior box and socket set as v1. Shed roof, a porch on "
                   "brand-coloured columns, round windows and a warmer palette.")
    floor_top = _shell(P, round_windows=True, layout="b")

    # mono-pitch roof, low at the front
    P.roof_prism([(-HY - 0.22, WALL_TOP - 0.06), (HY + 0.22, WALL_TOP - 0.06),
                  (HY + 0.22, SHED_HIGH), (-HY - 0.22, SHED_LOW)],
                 "yz", -HX - 0.26, HX + 0.26)

    # porch: deck, two brand-coloured columns, canopy, and a solid upstand carrying the sign.
    # Nothing reaches past 3.5 m from the anchor (class S footprint).
    P.box((-2.14, -3.40, 0.0), (2.14, -HY + 0.06, 0.09), "M_Trim")
    P.box((-1.92, -3.26, 0.09), (1.92, -HY + 0.06, floor_top), "M_Floor")
    for sx in (-1, 1):
        P.box((sx * 1.90 - 0.14, -3.28, 0.0), (sx * 1.90 + 0.14, -3.00, 3.11), "M_BrandAccent")
    P.box((-2.06, -3.34, 2.95), (2.06, -HY + 0.06, 3.11), "M_Roof", faces={"-z": "M_Trim"})
    P.box((-2.06, -3.34, 3.11), (2.06, -3.22, 4.21), "M_Wall")          # sign upstand
    P.box((-2.06, -3.36, 4.21), (2.06, -3.20, 4.30), "M_Trim")          # upstand coping

    P.entrance_mat(center_x=0.0, y0=-3.10, y1=-2.88, half_w=0.75, z=floor_top)
    for sx in (-1, 1):
        P.planter((sx * 2.50, -3.00), size=(0.95, 0.70), h=0.52)

    P.add_sign((0.0, -3.34, 3.66), (0.0, -1.0, 0.0))
    P.standard_markers(roof_top=SHED_HIGH, front_y=-HY)
    return P
