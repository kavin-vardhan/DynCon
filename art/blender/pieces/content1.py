"""`content1` — large uploadable content, size class L (spec v1 §3).

v1  "Hall": 12 x 10 m, flat roof with a parapet, full-height glazed front with the door in the
    middle and a sign band above it.
v2  (next brief) sawtooth roof, vertical fins, entrance canopy.
"""

import dc_kit as K

PALETTE = {
    "M_Wall":         {"color": "#CBD2D6"},     # cool blue-grey
    "M_WallInterior": {"color": "#E8ECEE"},
    "M_Floor":        {"color": "#8C939A"},
    "M_Roof":         {"color": "#5E666C"},
    "M_Trim":         {"color": "#3C4349"},
}

HX, HY, T = 6.0, 5.0, 0.25          # 12 x 10 m footprint, 0.25 m walls
WALL_TOP = 5.60
CEIL_UNDER = 5.45
DOOR_W, DOOR_HEAD = 1.80, 2.95

VERSIONS = ("v1", "v2")
IMPLEMENTED = ("v1",)           # v2 arrives in the next brief


def build(version):
    if version == "v1":
        return _v1()
    raise ValueError("content1 %s is not built yet" % version)


def _v1():
    P = K.Piece("content1", "v1", "L", palette=PALETTE)
    P.notes.append("Glazed front runs the full 12 m; the sign band is a solid panel mounted "
                   "proud of the glazing above the door, so the facade stays fully glazed.")

    floor_top = P.plinth(HX, HY, skirt=0.25, base_h=0.09, deck_h=0.05)
    ix0, ix1 = -HX + T, HX - T
    iy0, iy1 = -HY + T, HY - T

    # back wall, then the two side walls buried into it
    P.wall_run(along="x", outer=HY, out_sign=1, t=T, a=-HX, b=HX, z0=0.0, z1=WALL_TOP)
    for sx in (-1, 1):
        P.wall_run(along="y", outer=sx * HX, out_sign=sx, t=T,
                   a=-HY + T / 2, b=HY - T / 2, z0=0.0, z1=WALL_TOP)

    # full-height glazed front, door in the middle
    P.glazed_run(along="x", outer=-HY, out_sign=-1, t=T, a=-HX, b=HX,
                 z0=floor_top, z1=WALL_TOP,
                 door=dict(center=0.0, width=DOOR_W, head=DOOR_HEAD),
                 pane_max=1.75, mullion=0.11, frame=0.16)

    # solid piers either side of the door: they stiffen the glazed front, give the door
    # something to close against, and carry the two switches
    # sit just behind the glazing so nothing is coplanar with a mullion or a pane
    pier_y0, pier_y1 = iy0 - 0.04, iy0 + 0.33
    for sx in (-1, 1):
        x0, x1 = sorted((sx * 0.90, sx * 1.80))
        P.box((x0, pier_y0, floor_top), (x1, pier_y1, 3.30), "M_Wall",
              faces={"+y": "M_WallInterior", "-x": "M_WallInterior", "+x": "M_WallInterior"})

    P.ceiling((ix0, iy0), (ix1, iy1), CEIL_UNDER, CEIL_UNDER + 0.07)
    roof_top = P.flat_roof(HX, HY, WALL_TOP, WALL_TOP + 0.25, overhang=0.12, parapet=(0.40, 0.25))

    P.add_door(hinge=(-DOOR_W / 2, -HY + T / 2, floor_top),
               width=DOOR_W, height=DOOR_HEAD - floor_top, open_sign=1)

    P.standard_interior(lo=(ix0, iy0, floor_top), hi=(ix1, iy1, CEIL_UNDER),
                        door_center_x=0.0, lights_a=(3, 2), light_b_z=2.60,
                        switch_surface=(1.17, pier_y1))

    # brand accent: a band right across the facade, above the door transom
    P.box((-HX - 0.06, -HY - 0.07, 2.86), (HX + 0.06, -HY + 0.02, 3.16), "M_BrandAccent")

    P.add_sign((0.0, -HY, 4.30), (0.0, -1.0, 0.0), depth=0.13)
    P.standard_markers(roof_top=roof_top, front_y=-HY)
    return P
