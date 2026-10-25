"""`content4` — small uploadable content, size class S, fits every slot (spec v1 §3).

v1  "Cabin": 6 x 5 m, gable roof, door on the gable end, a rectangular window each side.
v2  Mono-pitch (shed) roof, porch on posts, round windows.

Both versions share the same footprint, the same interior box and the same socket set, so the
state kept across an update (lights A/B, door, screen image) carries over unchanged.
"""

import dc_kit as K

PALETTE = {
    "M_Wall":         {"color": "#E2DBCB"},     # sand
    "M_WallInterior": {"color": "#F2EDE3"},
    "M_Floor":        {"color": "#9B8F7D"},
    "M_Roof":         {"color": "#7A6E60"},
    "M_Trim":         {"color": "#4E4639"},
    "M_Door":         {"color": "#8F7E62"},
}

HX, HY, T = 3.0, 2.5, 0.22          # 6 x 5 m footprint, 0.22 m walls
WALL_TOP = 4.05
CEIL_UNDER = 3.90
RIDGE = 4.78                        # v1 gable
SHED_LOW, SHED_HIGH = 4.20, 4.90    # v2 mono-pitch
DOOR_W, DOOR_HEAD = 1.70, 2.80
WIN_Z = 2.05                        # centre height of the v2 round windows

VERSIONS = ("v1", "v2")


def _shell(P, *, round_windows):
    """Everything both versions share: plinth, four walls, ceiling, interior kit."""
    floor_top = P.plinth(HX, HY, skirt=0.18, base_h=0.09, deck_h=0.05)
    ix0, ix1 = -HX + T, HX - T
    iy0, iy1 = -HY + T, HY - T

    # front (-Y) gable end, with the door
    P.wall_run(along="x", outer=-HY, out_sign=-1, t=T, a=-HX, b=HX, z0=0.0, z1=WALL_TOP,
               openings=[dict(center=0.0, width=DOOR_W, sill=0.0, head=DOOR_HEAD)])
    # back (+Y) gable end
    P.wall_run(along="x", outer=HY, out_sign=1, t=T, a=-HX, b=HX, z0=0.0, z1=WALL_TOP)

    # the two long side walls, inset by half a wall so they bury into the gable ends
    for sx in (-1, 1):
        if round_windows:
            ops = [P.round_window_opening(WIN_Z)]
        else:
            ops = [dict(center=0.0, width=1.60, sill=1.10, head=2.70)]
        P.wall_run(along="y", outer=sx * HX, out_sign=sx, t=T,
                   a=-HY + T / 2, b=HY - T / 2, z0=0.0, z1=WALL_TOP, openings=ops)
        if round_windows:
            P.round_window(along="y", outer=sx * HX, out_sign=sx, t=T, center=0.0, z=WIN_Z)
        else:
            P.window(along="y", outer=sx * HX, out_sign=sx, t=T,
                     center=0.0, width=1.60, sill=1.10, head=2.70)

    P.ceiling((ix0, iy0), (ix1, iy1), CEIL_UNDER, WALL_TOP)

    P.add_door(hinge=(-DOOR_W / 2, -HY + T / 2, floor_top),
               width=DOOR_W, height=DOOR_HEAD - floor_top, open_sign=1)

    P.standard_interior(lo=(ix0, iy0, floor_top), hi=(ix1, iy1, CEIL_UNDER),
                        door_center_x=0.0, lights_a=(2, 1), light_b_z=2.25)
    return floor_top


def _doorstep(P, *, y_out, half_w):
    P.box((-half_w - 0.20, y_out, 0.0), (half_w + 0.20, -HY + 0.06, 0.09), "M_Trim")
    P.box((-half_w, y_out + 0.15, 0.09), (half_w, -HY + 0.06, 0.14), "M_Floor")


def build(version):
    if version == "v1":
        return _v1()
    if version == "v2":
        return _v2()
    raise ValueError("content4 has no %s" % version)


# ----------------------------------------------------------------------------------- v1
def _v1():
    P = K.Piece("content4", "v1", "S", palette=PALETTE)
    P.notes.append("Gable ridge is 4.78 m (spec says ~4.6) so a flat 3.90 m ceiling still "
                   "clears 3.5 m and the sign band fits above the door.")
    _shell(P, round_windows=False)
    _doorstep(P, y_out=-2.95, half_w=1.05)

    # solid gable roof: no gap is possible between wall top and roof underside
    P.roof_prism([(-HX - 0.26, WALL_TOP - 0.06), (0.0, RIDGE), (HX + 0.26, WALL_TOP - 0.06)],
                 "xz", -HY - 0.22, HY + 0.22)

    # brand accent: the door surround
    for sx in (-1, 1):
        x0, x1 = sorted((sx * 0.85, sx * 1.13))
        P.box((x0, -HY - 0.05, 0.0), (x1, -HY + 0.02, DOOR_HEAD), "M_BrandAccent")
    P.box((-1.13, -HY - 0.05, DOOR_HEAD), (1.13, -HY + 0.02, DOOR_HEAD + 0.12), "M_BrandAccent")

    P.add_sign((0.0, -HY, 3.45), (0.0, -1.0, 0.0))
    P.standard_markers(roof_top=RIDGE, front_y=-HY)
    return P


# ----------------------------------------------------------------------------------- v2
def _v2():
    P = K.Piece("content4", "v2", "S", palette=PALETTE)
    P.notes.append("Same footprint, interior and socket set as v1; shed roof, porch and round "
                   "windows make the update obvious from across the booth.")
    _shell(P, round_windows=True)

    # mono-pitch roof, low at the front
    P.roof_prism([(-HY - 0.22, WALL_TOP - 0.06), (HY + 0.22, WALL_TOP - 0.06),
                  (HY + 0.22, SHED_HIGH), (-HY - 0.22, SHED_LOW)],
                 "yz", -HX - 0.26, HX + 0.26)

    # porch: deck, two posts (the brand accent frames the entrance), canopy.
    # Depth is set by the class S footprint: nothing may reach past 3.5 m from the anchor.
    P.box((-2.12, -3.44, 0.0), (2.12, -HY + 0.06, 0.09), "M_Trim")
    P.box((-1.90, -3.30, 0.09), (1.90, -HY + 0.06, 0.14), "M_Floor")
    for sx in (-1, 1):
        P.box((sx * 1.82 - 0.12, -3.32, 0.0), (sx * 1.82 + 0.12, -3.08, 3.68), "M_BrandAccent")
    P.box((-2.00, -3.34, 3.58), (2.00, -HY + 0.06, 3.74), "M_Roof", faces={"-z": "M_Trim"})

    # sign hangs from the front edge of the porch canopy, clear of the door head
    P.add_sign((0.0, -3.31, 3.22), (0.0, -1.0, 0.0))
    P.standard_markers(roof_top=SHED_HIGH, front_y=-HY)
    return P
