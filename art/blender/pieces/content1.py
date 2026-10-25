"""`content1` — large uploadable content, size class L (spec v1 §3).

v1  "Hall": 12 x 10 m, glazed front under a solid fascia, flat roof with a parapet.
v2  Same footprint, sawtooth (north-light) roof, vertical fins instead of the glass front,
    entrance canopy, and a much darker palette.
"""

import dc_kit as K

HX, HY, T = 6.0, 5.0, 0.25          # 12 x 10 m footprint, 0.25 m walls
DOOR_W = 1.80

VERSIONS = ("v1", "v2")


def build(version):
    if version == "v1":
        return _v1()
    if version == "v2":
        return _v2()
    raise ValueError("content1 has no %s" % version)


def _side_walls(P, *, wall_top, windows, joints=True):
    """The two long side walls, inset by half a wall so they bury into the end walls."""
    for sx in (-1, 1):
        ops = [dict(center=c, width=w, sill=s, head=h) for (c, w, s, h) in windows]
        P.wall_run(along="y", outer=sx * HX, out_sign=sx, t=T,
                   a=-HY + T / 2, b=HY - T / 2, z0=0.0, z1=wall_top, openings=ops)
        for (c, w, s, h) in windows:
            P.window(along="y", outer=sx * HX, out_sign=sx, t=T, center=c, width=w,
                     sill=s, head=h, mullions=1)
        if joints:
            skip = [(c - w / 2 - 0.3, c + w / 2 + 0.3) for (c, w, s, h) in windows]
            P.panel_joints(along="y", outer=sx * HX, out_sign=sx, a=-HY + 0.4, b=HY - 0.4,
                           z0=0.55, z1=wall_top - 0.15, pitch=1.3, skip=skip)


# ----------------------------------------------------------------------------------- v1
def _v1():
    WALL_TOP, GLAZE_TOP, CEIL_UNDER = 6.10, 3.80, 5.85
    DOOR_HEAD = 2.95
    P = K.Piece("content1", "v1", "L")
    P.notes.append("The glazed front stops at 3.80 m and a solid 2.30 m fascia carries the sign "
                   "and the brand band — signs never mount on glazing.")

    floor_top = P.plinth(HX, HY, skirt=0.25, base_h=0.09, deck_h=0.05)
    ix0, ix1 = -HX + T, HX - T
    iy0, iy1 = -HY + T, HY - T

    # back wall with a window rhythm, then the side walls buried into it
    back = [(sx * 4.55, 2.20, 1.10, 3.30) for sx in (-1, 1)]
    P.wall_run(along="x", outer=HY, out_sign=1, t=T, a=-HX, b=HX, z0=0.0, z1=WALL_TOP,
               openings=[dict(center=c, width=w, sill=s, head=h) for (c, w, s, h) in back])
    for (c, w, s, h) in back:
        P.window(along="x", outer=HY, out_sign=1, t=T, center=c, width=w, sill=s, head=h, mullions=1)
    P.panel_joints(along="x", outer=HY, out_sign=1, a=-HX + 0.4, b=HX - 0.4, z0=0.55,
                   z1=WALL_TOP - 0.15, pitch=1.35,
                   skip=[(c - w / 2 - 0.3, c + w / 2 + 0.3) for (c, w, s, h) in back])
    _side_walls(P, wall_top=WALL_TOP, windows=[(c, 1.50, 1.10, 3.30) for c in (-3.0, 0.0, 3.0)])

    # glazed front, door in the middle, then the solid fascia above it
    P.glazed_run(along="x", outer=-HY, out_sign=-1, t=T, a=-HX, b=HX,
                 z0=floor_top, z1=GLAZE_TOP,
                 door=dict(center=0.0, width=DOOR_W, head=DOOR_HEAD),
                 pane_max=1.75, mullion=0.11, frame=0.16)
    P.fascia_band(along="x", outer=-HY, out_sign=-1, a=-HX, b=HX, z0=GLAZE_TOP, z1=WALL_TOP, t=T)

    # solid piers either side of the door: they stiffen the glazed front and carry the switches
    pier_y0, pier_y1 = iy0 - 0.04, iy0 + 0.33
    for sx in (-1, 1):
        x0, x1 = sorted((sx * 0.90, sx * 1.80))
        P.box((x0, pier_y0, floor_top), (x1, pier_y1, 3.30), "M_Wall",
              faces={"+y": "M_WallInterior", "-x": "M_WallInterior", "+x": "M_WallInterior"})

    P.ceiling((ix0, iy0), (ix1, iy1), CEIL_UNDER, CEIL_UNDER + 0.17)
    roof_top = P.flat_roof(HX, HY, WALL_TOP, WALL_TOP + 0.25, overhang=0.12, parapet=(0.42, 0.25))
    P.coping(HX + 0.12, HY + 0.12, roof_top, wide=0.30)
    P.base_course(HX, HY, 0.04, 0.46, skip_front=(-1.6, 1.6))

    # roof furniture and rainwater
    for (px, py) in ((-3.4, 2.6), (0.2, 3.1), (3.3, 2.4)):
        P.roof_plant_box((px, py), size=(1.7, 0.95), h=0.44, z0=WALL_TOP + 0.25)
    for sx in (-1, 1):
        P.downpipe(sx * (HX + 0.10), HY - 0.30, 0.10, roof_top - 0.10)

    P.add_door(hinge=(-DOOR_W / 2, -HY + T / 2, floor_top),
               width=DOOR_W, height=DOOR_HEAD - floor_top, open_sign=1)
    P.door_frame(along="x", outer=-HY, out_sign=-1, t=T, center=0.0, width=DOOR_W,
                 head=DOOR_HEAD, mat="M_BrandAccent", w=0.16, proud=0.06)

    P.entrance_step(center_x=0.0, y_out=-5.70, y_in=-HY + 0.06, half_w=1.60, z_top=floor_top)
    P.entrance_mat(center_x=0.0, y0=-5.44, y1=-5.18, half_w=1.05, z=floor_top)
    for sx in (-1, 1):
        P.planter((sx * 2.70, -5.42), size=(1.25, 0.80), h=0.58)

    # brand band and sign, both on the solid fascia
    P.box((-HX - 0.06, -HY - 0.08, GLAZE_TOP), (HX + 0.06, -HY + 0.02, GLAZE_TOP + 0.32),
          "M_BrandAccent")
    P.add_sign((0.0, -HY, 5.10), (0.0, -1.0, 0.0), depth=0.13)
    for sx in (-1, 1):
        P.wall_lamp((sx * 2.65, -HY, 4.75), (0.0, -1.0, 0.0))

    P.standard_interior(lo=(ix0, iy0, floor_top), hi=(ix1, iy1, CEIL_UNDER),
                        door_center_x=0.0, lights_a=(3, 2), light_b_z=2.60, layout="a",
                        switch_surface=(1.17, pier_y1), side_light_f=0.68)
    P.standard_markers(roof_top=roof_top, front_y=-HY)
    return P


# ----------------------------------------------------------------------------------- v2
def _v2():
    WALL_TOP, CEIL_UNDER = 5.70, 5.45
    DOOR_HEAD = 2.85
    LOW, PEAK = 5.95, 7.50
    P = K.Piece("content1", "v2", "L")
    P.notes.append("Same footprint and socket set as v1. Solid front behind deep fins, an "
                   "entrance canopy on brand-coloured columns, sawtooth north-light roof.")

    floor_top = P.plinth(HX, HY, skirt=0.25, base_h=0.09, deck_h=0.05)
    ix0, ix1 = -HX + T, HX - T
    iy0, iy1 = -HY + T, HY - T

    back = [(sx * 4.30, 2.20, 1.20, 3.60) for sx in (-1, 1)]
    P.wall_run(along="x", outer=HY, out_sign=1, t=T, a=-HX, b=HX, z0=0.0, z1=WALL_TOP,
               openings=[dict(center=c, width=w, sill=s, head=h) for (c, w, s, h) in back])
    for (c, w, s, h) in back:
        P.window(along="x", outer=HY, out_sign=1, t=T, center=c, width=w, sill=s, head=h, mullions=2)
    _side_walls(P, wall_top=WALL_TOP, windows=[(c, 2.10, 1.20, 3.90) for c in (-2.3, 2.3)])

    # solid front with the door and two windows
    front = [dict(center=0.0, width=DOOR_W, sill=0.0, head=DOOR_HEAD)] + \
            [dict(center=sx * 3.70, width=1.60, sill=1.10, head=3.30) for sx in (-1, 1)]
    P.wall_run(along="x", outer=-HY, out_sign=-1, t=T, a=-HX, b=HX, z0=0.0, z1=WALL_TOP,
               openings=front)
    for o in front[1:]:
        P.window(along="x", outer=-HY, out_sign=-1, t=T, center=o["center"], width=o["width"],
                 sill=o["sill"], head=o["head"], mullions=1)
    P.fins(along="x", outer=-HY, out_sign=-1, a=-HX, b=HX, z0=0.50, z1=WALL_TOP - 0.20,
           pitch=0.80, w=0.13, depth=0.36, skip=((-1.75, 1.75),))

    P.ceiling((ix0, iy0), (ix1, iy1), CEIL_UNDER, WALL_TOP)
    P.base_course(HX, HY, 0.04, 0.46, skip_front=(-1.6, 1.6))

    # sawtooth roof: three teeth, the vertical faces glazed to the north (+Y)
    ys = [-HY - 0.12 + (2 * HY + 0.24) * k / 3.0 for k in range(4)]
    prof = [(ys[0], WALL_TOP - 0.06), (ys[3], WALL_TOP - 0.06), (ys[3], PEAK)]
    for k in (2, 1):
        prof += [(ys[k], LOW), (ys[k], PEAK)]
    prof += [(ys[0], LOW)]
    P.roof_prism(prof, "yz", -HX - 0.12, HX + 0.12)
    for k in (1, 2):
        P.box((-HX + 0.10, ys[k] - 0.03, LOW + 0.10), (HX - 0.10, ys[k] + 0.06, PEAK - 0.10), "M_Glass")
        for i in range(5):
            x = -HX + 0.10 + (2 * HX - 0.20) * (i + 1) / 6.0
            P.box((x - 0.05, ys[k] - 0.02, LOW + 0.10), (x + 0.05, ys[k] + 0.09, PEAK - 0.10), "M_Trim")

    P.add_door(hinge=(-DOOR_W / 2, -HY + T / 2, floor_top),
               width=DOOR_W, height=DOOR_HEAD - floor_top, open_sign=1)
    P.door_frame(along="x", outer=-HY, out_sign=-1, t=T, center=0.0, width=DOOR_W,
                 head=DOOR_HEAD, mat="M_Trim", w=0.16, proud=0.06)

    # entrance canopy on brand-coloured columns, with a brand edge band
    P.box((-2.70, -6.00, 3.10), (2.70, -HY + 0.06, 3.30), "M_Roof", faces={"-z": "M_Trim"})
    P.box((-2.76, -6.06, 3.30), (2.76, -5.88, 3.46), "M_BrandAccent")
    for sx in (-1, 1):
        P.box((sx * 2.40 - 0.17, -5.92, 0.0), (sx * 2.40 + 0.17, -5.58, 3.30), "M_BrandAccent")

    P.entrance_step(center_x=0.0, y_out=-6.14, y_in=-HY + 0.06, half_w=1.70, z_top=floor_top)
    P.entrance_mat(center_x=0.0, y0=-5.60, y1=-5.32, half_w=1.05, z=floor_top)
    for sx in (-1, 1):
        P.planter((sx * 4.00, -5.70), size=(1.30, 0.80), h=0.58)

    P.add_sign((0.0, -HY, 4.35), (0.0, -1.0, 0.0), depth=0.13)
    for sx in (-1, 1):
        P.wall_lamp((sx * 1.35, -HY, 2.25), (0.0, -1.0, 0.0))

    P.standard_interior(lo=(ix0, iy0, floor_top), hi=(ix1, iy1, CEIL_UNDER),
                        door_center_x=0.0, lights_a=(3, 2), light_b_z=2.50, layout="b",
                        side_light_f=0.50)
    P.standard_markers(roof_top=PEAK, front_y=-HY)
    return P
