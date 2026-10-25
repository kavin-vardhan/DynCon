"""`rival1` — the rival's large content for region 1, size class L (spec v1 §3).

v1 only. "L-shaped hall" in a ~13 x 13 m box: a tall main bar running front to back with the
door, and a lower wing off the back-right corner, open to the main bar through a wide portal.
Flat roofs with parapets, ~6.5 m.

A rival piece is content like any other — the Player can walk in, flip both light switches,
open the door and look at the screen — so it carries the full interactable set and the same
state schema. Its identity (colour + emblem) is runtime data; the geometry is neutral.
"""

import dc_kit as K

# main bar and wing, in plan
MX0, MX1 = -6.30, 2.30          # main bar, x
MY0, MY1 = -6.00, 6.30          # main bar, y (the front wall is at MY0)
WX1, WY0 = 6.30, 1.30           # wing reaches to x = WX1, starting at y = WY0
T = 0.26

WALL_TOP, CEIL_UNDER = 6.00, 5.75
WING_TOP, WING_CEIL = 4.90, 4.65
SLAB, PARAPET = 0.20, 0.32
DOOR_X, DOOR_W, DOOR_HEAD = -2.00, 1.80, 2.95
SIGN_Z = 4.90

VERSIONS = ("v1",)


def _parapet_ring(P, x0, y0, x1, y1, z0, z1, *, t=0.26, sides="nsew"):
    """Parapet walls standing on a roof slab edge."""
    if "s" in sides:
        P.box((x0, y0, z0), (x1, y0 + t, z1), "M_Wall", faces={"+z": "M_Trim"})
    if "n" in sides:
        P.box((x0, y1 - t, z0), (x1, y1, z1), "M_Wall", faces={"+z": "M_Trim"})
    if "w" in sides:
        P.box((x0, y0, z0), (x0 + t, y1, z1), "M_Wall", faces={"+z": "M_Trim"})
    if "e" in sides:
        P.box((x1 - t, y0, z0), (x1, y1, z1), "M_Wall", faces={"+z": "M_Trim"})


def build(version):
    P = K.Piece("rival1", version, "L")
    P.notes.append("L plan: the main bar carries the door, the screen and the fit-out; the "
                   "wing is a lower side room open to it through a 3 m portal.")
    P.notes.append("VOLUME_Interior is the main bar — the wing is walkable but is not where "
                   "dwell is measured.")

    floor_top = _floors(P)

    ix0, ix1 = MX0 + T, MX1 - T          # main bar interior
    iy0, iy1 = MY0 + T, MY1 - T
    wx0, wx1 = MX1, WX1 - T              # wing interior
    wy0, wy1 = WY0 + T, MY1 - T

    # ---------------------------------------------------------------- walls
    front = [dict(center=DOOR_X, width=DOOR_W, sill=0.0, head=DOOR_HEAD),
             dict(center=-5.00, width=1.80, sill=1.20, head=3.40),
             dict(center=0.90, width=1.80, sill=1.20, head=3.40)]
    P.wall_run(along="x", outer=MY0, out_sign=-1, t=T, a=MX0, b=MX1, z0=0.0, z1=WALL_TOP,
               openings=front)
    for o in front[1:]:
        P.window(along="x", outer=MY0, out_sign=-1, t=T, center=o["center"], width=o["width"],
                 sill=o["sill"], head=o["head"], mullions=1)

    # back wall: full height behind the main bar, wing height behind the wing
    P.wall_run(along="x", outer=MY1, out_sign=1, t=T, a=MX0, b=MX1, z0=0.0, z1=WALL_TOP)
    P.panel_joints(along="x", outer=MY1, out_sign=1, a=MX0 + 0.4, b=MX1 - 0.4,
                   z0=0.55, z1=WALL_TOP - 0.20, pitch=1.45)
    wing_back = [dict(center=4.30, width=1.60, sill=1.20, head=3.20)]
    P.wall_run(along="x", outer=MY1, out_sign=1, t=T, a=MX1, b=WX1, z0=0.0, z1=WING_TOP,
               openings=wing_back)
    for o in wing_back:
        P.window(along="x", outer=MY1, out_sign=1, t=T, center=o["center"], width=o["width"],
                 sill=o["sill"], head=o["head"], mullions=1)

    # west wall of the main bar
    west = [(c, 1.80, 1.20, 3.40) for c in (-2.60, 0.40, 3.40)]
    P.wall_run(along="y", outer=MX0, out_sign=-1, t=T, a=MY0 + T / 2, b=MY1 - T / 2,
               z0=0.0, z1=WALL_TOP,
               openings=[dict(center=c, width=w, sill=s, head=h) for (c, w, s, h) in west])
    for (c, w, s, h) in west:
        P.window(along="y", outer=MX0, out_sign=-1, t=T, center=c, width=w, sill=s, head=h,
                 mullions=1)
    P.panel_joints(along="y", outer=MX0, out_sign=-1, a=MY0 + 0.4, b=MY1 - 0.4,
                   z0=0.55, z1=WALL_TOP - 0.20, pitch=1.35,
                   skip=[(c - w / 2 - 0.3, c + w / 2 + 0.3) for (c, w, s, h) in west])

    # east wall of the main bar: outside wall as far as the wing, then the party wall
    east = [(-3.00, 1.80, 1.20, 3.40)]
    P.wall_run(along="y", outer=MX1, out_sign=1, t=T, a=MY0 + T / 2, b=WY0, z0=0.0, z1=WALL_TOP,
               openings=[dict(center=c, width=w, sill=s, head=h) for (c, w, s, h) in east])
    for (c, w, s, h) in east:
        P.window(along="y", outer=MX1, out_sign=1, t=T, center=c, width=w, sill=s, head=h,
                 mullions=1)
    P.wall_run(along="y", outer=MX1, out_sign=1, t=T, a=WY0, b=MY1 - T / 2, z0=0.0, z1=WING_TOP,
               mat="M_WallInterior",
               openings=[dict(center=4.10, width=3.00, sill=0.0, head=3.60, reveal=True)])
    P.wall_run(along="y", outer=MX1, out_sign=1, t=T, a=WY0, b=MY1 - T / 2,
               z0=WING_TOP, z1=WALL_TOP)

    # wing: south and east walls
    P.wall_run(along="x", outer=WY0, out_sign=-1, t=T, a=MX1, b=WX1, z0=0.0, z1=WING_TOP,
               openings=[dict(center=4.30, width=2.40, sill=1.20, head=3.40)])
    P.window(along="x", outer=WY0, out_sign=-1, t=T, center=4.30, width=2.40, sill=1.20,
             head=3.40, mullions=2)
    wing_east = [(c, 1.50, 1.20, 3.20) for c in (2.80, 5.00)]
    P.wall_run(along="y", outer=WX1, out_sign=1, t=T, a=WY0 + T / 2, b=MY1 - T / 2,
               z0=0.0, z1=WING_TOP,
               openings=[dict(center=c, width=w, sill=s, head=h) for (c, w, s, h) in wing_east])
    for (c, w, s, h) in wing_east:
        P.window(along="y", outer=WX1, out_sign=1, t=T, center=c, width=w, sill=s, head=h,
                 mullions=1)

    # ---------------------------------------------------------------- roofs
    P.ceiling((ix0, iy0), (ix1, iy1), CEIL_UNDER, WALL_TOP)
    P.ceiling((wx0, wy0), (wx1, wy1), WING_CEIL, WING_TOP)

    mx0, my0, mx1, my1 = MX0 - 0.12, MY0 - 0.12, MX1 + 0.12, MY1 + 0.12
    P.box((mx0, my0, WALL_TOP), (mx1, my1, WALL_TOP + SLAB), "M_Roof", faces={"-z": "M_Trim"})
    roof_top = WALL_TOP + SLAB + PARAPET
    _parapet_ring(P, mx0, my0, mx1, my1, WALL_TOP + SLAB, roof_top)
    P.box((mx0 - 0.05, my0 - 0.05, roof_top), (mx1 + 0.05, my1 + 0.05, roof_top + 0.09), "M_Trim")

    wx_a, wy_a, wx_b, wy_b = MX1, WY0 - 0.12, WX1 + 0.12, MY1 + 0.12
    P.box((wx_a, wy_a, WING_TOP), (wx_b, wy_b, WING_TOP + 0.18), "M_Roof", faces={"-z": "M_Trim"})
    wing_roof_top = WING_TOP + 0.18 + 0.28
    _parapet_ring(P, wx_a, wy_a, wx_b, wy_b, WING_TOP + 0.18, wing_roof_top, t=0.24, sides="nse")
    P.box((wx_a, wy_a - 0.05, wing_roof_top), (wx_b + 0.05, wy_b + 0.05, wing_roof_top + 0.09),
          "M_Trim")

    for (px, py) in ((4.00, 3.10), (4.00, 5.10)):
        P.roof_plant_box((px, py), size=(1.5, 0.9), h=0.42, z0=WING_TOP + 0.18)
    P.downpipe(MX0 - 0.10, MY1 - 0.40, 0.10, roof_top - 0.20)
    P.downpipe(WX1 + 0.10, WY0 + 0.40, 0.10, wing_roof_top - 0.20)

    # ---------------------------------------------------------------- front detail
    P.add_door(hinge=(DOOR_X - DOOR_W / 2, MY0 + T / 2, floor_top),
               width=DOOR_W, height=DOOR_HEAD - floor_top, open_sign=1)
    P.door_frame(along="x", outer=MY0, out_sign=-1, t=T, center=DOOR_X, width=DOOR_W,
                 head=DOOR_HEAD, mat="M_BrandAccent", w=0.16, proud=0.06)
    for sx in (-1, 1):
        P.wall_lamp((DOOR_X + sx * 1.35, MY0, 2.30), (0.0, -1.0, 0.0))
    # brand band right across the front, under the sign
    P.box((MX0 - 0.06, MY0 - 0.08, 3.60), (MX1 + 0.06, MY0 + 0.02, 3.96), "M_BrandAccent")
    P.add_sign((DOOR_X, MY0, SIGN_Z), (0.0, -1.0, 0.0), depth=0.13)

    P.entrance_step(center_x=DOOR_X, y_out=-6.70, y_in=MY0 + 0.06, half_w=1.55, z_top=floor_top)
    P.entrance_mat(center_x=DOOR_X, y0=-6.44, y1=-6.18, half_w=0.98, z=floor_top)
    for sx in (-1, 1):
        P.planter((DOOR_X + sx * 2.75, -6.42), size=(1.20, 0.80), h=0.58)

    # ---------------------------------------------------------------- interior
    blocked = [(c - w / 2 - 0.30, c + w / 2 + 0.30) for (c, w, s, h) in west + east]
    blocked.append((2.40, 5.80))            # the portal into the wing
    P.standard_interior(lo=(ix0, iy0, floor_top), hi=(ix1, iy1, CEIL_UNDER),
                        door_center_x=DOOR_X, lights_a=(3, 2), light_b_z=2.55, layout="a",
                        side_light_f=0.36, tall_avoid=blocked)

    # the wing's own fit-out, laid out by hand: the standard layouts assume one rectangle
    P.light_a_fixture(3.60, 2.90, WING_CEIL - 0.09)
    P.light_a_fixture(5.10, 4.90, WING_CEIL - 0.09)
    P.wall_lamp((wx1, 3.60, 2.45), (-1.0, 0.0, 0.0))
    P.display_plinth((3.30, 4.70), size=0.78, h=0.95, z0=floor_top, shape="cone")
    P.display_plinth((5.30, 2.60), size=0.78, h=0.88, z0=floor_top, shape="sphere")
    P.bench((4.95, 5.55, floor_top), length=2.0, depth=0.52, seat_z=floor_top + 0.46, axis="x")
    P.skirting((wx0, wy0, floor_top), (wx1, wy1, WING_CEIL))

    P.standard_markers(roof_top=roof_top, front_y=MY0)
    return P


def _floors(P):
    """Floor slab and base course of an L plan — the centred helpers assume a rectangle."""
    base_h, deck_h = 0.09, 0.05
    top = base_h + deck_h
    s = 0.22
    # two rectangles that only touch, never overlap: overlapping slabs would leave two
    # coplanar top faces fighting each other wherever the skirt is exposed
    P.box((MX0 - s, MY0 - s, 0.0), (MX1 + s, MY1 + s, base_h), "M_Trim")
    P.box((MX1 + s, WY0 - s, 0.0), (WX1 + s, MY1 + s, base_h), "M_Trim")
    P.box((MX0, MY0, base_h), (MX1, MY1, top), "M_Floor")
    P.box((MX1, WY0, base_h), (WX1, MY1, top), "M_Floor")
    for (x0, y0, x1, y1) in (
            (MX0 - 0.06, MY0 - 0.06, MX1 + 0.06, MY0 + 0.06),      # front
            (MX0 - 0.06, MY0 - 0.06, MX0 + 0.06, MY1 + 0.06),      # west
            (MX0 - 0.06, MY1 - 0.06, WX1 + 0.06, MY1 + 0.06),      # north
            (WX1 - 0.06, WY0 - 0.06, WX1 + 0.06, MY1 + 0.06),      # wing east
            (MX1 - 0.06, WY0 - 0.06, WX1 + 0.06, WY0 + 0.06),      # wing south
            (MX1 - 0.06, MY0 - 0.06, MX1 + 0.06, WY0 + 0.06)):     # main east
        P.box((x0, y0, 0.04), (x1, y1, 0.50), "M_Trim")
    P.clearances["floor_top_z"] = round(top, 4)
    return top
