"""`rivalsmall` — the rival's content for the small slots, size class S (spec v1 §3).

v1 only. "Cube kiosk" ~5 x 5 m under a slanted roof that rises from 4.25 m at the door to
4.80 m at the back. Small, but the full walk-in set: door, two switches, screen, sign, both
light groups.

The same geometry serves every region — the server recolours it per region at runtime — so
nothing here is tied to one rival; the preview just happens to be dressed as region 1's.
"""

import dc_kit as K

HX = HY = 2.50                  # 5 x 5 m
T = 0.20
WALL_TOP, CEIL_UNDER = 3.95, 3.78
EAVE_FRONT, EAVE_BACK = 4.25, 4.80
OVER = 0.26                     # roof overhang
DOOR_W, DOOR_HEAD = 1.70, 2.80     # 2.80 - the 0.14 floor leaves the 2.6 m clear opening
SIGN_Z = 3.40

VERSIONS = ("v1",)


def build(version):
    P = K.Piece("rivalsmall", version, "S")
    P.notes.append("Mono-pitch roof low at the door (4.25 m) and high at the back (4.80 m), "
                   "inside the 5.0 m the small class allows.")

    floor_top = P.plinth(HX, HY, skirt=0.18, base_h=0.09, deck_h=0.05)
    ix0, ix1 = -HX + T, HX - T
    iy0, iy1 = -HY + T, HY - T

    # ---------------------------------------------------------------- walls
    front = [dict(center=0.0, width=DOOR_W, sill=0.0, head=DOOR_HEAD)] + \
            [dict(center=sx * 1.75, width=0.90, sill=1.20, head=2.55) for sx in (-1, 1)]
    P.wall_run(along="x", outer=-HY, out_sign=-1, t=T, a=-HX, b=HX, z0=0.0, z1=WALL_TOP,
               openings=front)
    for o in front[1:]:
        P.window(along="x", outer=-HY, out_sign=-1, t=T, center=o["center"], width=o["width"],
                 sill=o["sill"], head=o["head"], mullions=0, surround=0.08)

    P.wall_run(along="x", outer=HY, out_sign=1, t=T, a=-HX, b=HX, z0=0.0, z1=WALL_TOP)
    P.panel_joints(along="x", outer=HY, out_sign=1, a=-HX + 0.3, b=HX - 0.3,
                   z0=0.46, z1=WALL_TOP - 0.12, pitch=1.05)

    side = [(0.0, 1.30, 1.15, 2.55)]
    for sx in (-1, 1):
        P.wall_run(along="y", outer=sx * HX, out_sign=sx, t=T, a=-HY + T / 2, b=HY - T / 2,
                   z0=0.0, z1=WALL_TOP,
                   openings=[dict(center=c, width=w, sill=s, head=h) for (c, w, s, h) in side])
        for (c, w, s, h) in side:
            P.window(along="y", outer=sx * HX, out_sign=sx, t=T, center=c, width=w,
                     sill=s, head=h, mullions=1, surround=0.09)
        P.panel_joints(along="y", outer=sx * HX, out_sign=sx, a=-HY + 0.3, b=HY - 0.3,
                       z0=0.46, z1=WALL_TOP - 0.12, pitch=1.05, skip=((-1.0, 1.0),))

    P.ceiling((ix0, iy0), (ix1, iy1), CEIL_UNDER, WALL_TOP)
    P.base_course(HX, HY, 0.04, 0.44, skip_front=(-1.15, 1.15))

    # mono-pitch roof, solid so there is no gap over the wall head
    P.roof_prism([(-HY - OVER, WALL_TOP - 0.06), (HY + OVER, WALL_TOP - 0.06),
                  (HY + OVER, EAVE_BACK), (-HY - OVER, EAVE_FRONT)],
                 "yz", -HX - OVER, HX + OVER)
    P.downpipe(HX + 0.10, HY - 0.30, 0.10, EAVE_BACK - 0.35)

    # ---------------------------------------------------------------- brand, door, sign
    P.add_door(hinge=(-DOOR_W / 2, -HY + T / 2, floor_top),
               width=DOOR_W, height=DOOR_HEAD - floor_top, open_sign=1)
    P.door_frame(along="x", outer=-HY, out_sign=-1, t=T, center=0.0, width=DOOR_W,
                 head=DOOR_HEAD, mat="M_BrandAccent", w=0.15, proud=0.055)
    # brand pilasters at the two front corners and a fascia along the low eave
    for sx in (-1, 1):
        x0, x1 = sorted((sx * 2.34, sx * 2.50))
        P.box((x0, -HY - 0.06, 0.0), (x1, -HY + 0.02, WALL_TOP), "M_BrandAccent")
    P.box((-HX - OVER - 0.02, -HY - OVER - 0.08, WALL_TOP),
          (HX + OVER + 0.02, -HY - OVER + 0.04, EAVE_FRONT - 0.03), "M_BrandAccent")

    for sx in (-1, 1):
        P.wall_lamp((sx * 1.22, -HY, 2.20), (0.0, -1.0, 0.0))
    P.add_sign((0.0, -HY, SIGN_Z), (0.0, -1.0, 0.0))

    P.entrance_step(center_x=0.0, y_out=-3.08, y_in=-HY + 0.06, half_w=1.05, z_top=floor_top)
    P.entrance_mat(center_x=0.0, y0=-2.90, y1=-2.70, half_w=0.72, z=floor_top)
    for sx in (-1, 1):
        P.planter((sx * 2.00, -2.92), size=(0.95, 0.70), h=0.54)

    # ---------------------------------------------------------------- interior
    P.standard_interior(lo=(ix0, iy0, floor_top), hi=(ix1, iy1, CEIL_UNDER),
                        door_center_x=0.0, lights_a=(2, 2), light_b_z=2.25, layout="b",
                        side_light_f=0.76,
                        tall_avoid=[(c - w / 2 - 0.25, c + w / 2 + 0.25)
                                    for (c, w, s, h) in side])
    P.standard_markers(roof_top=EAVE_BACK, front_y=-HY)
    return P
