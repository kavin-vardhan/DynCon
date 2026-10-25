"""`content2` — large uploadable content, size class L (spec v1 §3).

v1  "Drum": a round hall with a ribbon window band and a shallow domed ceiling, entered
    through a flat-fronted entrance block that carries the door and the sign.
v2  Twelve-sided faceted prism, folded conical roof, a ring of external columns with brand
    colour wrapped round them.

The round forms stay flat shaded with plenty of segments, so they read as faceted
architectural models rather than smooth CAD surfaces — same language as the other pieces.
A flat chord panel inside carries the screen: a 16:9 screen cannot sit on a curved wall.
"""

import math

import dc_kit as K

DOOR_W = 1.80
SIGN_SIZE = (2.80, 1.40)        # a little narrower than the L default: it has to fit a facet
SCREEN_PANEL_HALF = 3.00

VERSIONS = ("v1", "v2")


def build(version):
    if version == "v1":
        return _v1()
    if version == "v2":
        return _v2()
    raise ValueError("content2 has no %s" % version)


def _interior(P, *, r_in, panel_front, panel_back, ceil_z, floor_top, segs, layout,
              start_deg=0.0, span_deg=360.0, lamp_x=None):
    """Round-room fit-out: ring floor border, ring skirting, flat screen panel, furniture."""
    # flat chord panel on the +Y side so the screen has something straight to sit on
    top = ceil_z - 0.25
    P.box((-SCREEN_PANEL_HALF, panel_front, floor_top), (SCREEN_PANEL_HALF, panel_back, top),
          "M_WallInterior", faces={"+z": "M_Trim"})
    for (xa, xb, za, zb) in ((-SCREEN_PANEL_HALF - 0.09, -SCREEN_PANEL_HALF, floor_top, top),
                             (SCREEN_PANEL_HALF, SCREEN_PANEL_HALF + 0.09, floor_top, top),
                             (-SCREEN_PANEL_HALF - 0.09, SCREEN_PANEL_HALF + 0.09, top - 0.11, top)):
        P.box((xa, panel_front - 0.07, za), (xb, panel_front + 0.02, zb), "M_Trim")

    P.sb.ring((0.0, 0.0), r_in - 0.035, r_in, "xy", floor_top, floor_top + 0.13, "M_Trim",
              segs=segs, start_deg=start_deg, span_deg=span_deg)
    P.sb.ring((0.0, 0.0), r_in - 0.92, r_in - 0.78, "xy", floor_top, floor_top + 0.012, "M_Trim",
              segs=segs)
    P.box((-P.PATH_HALF, -r_in, floor_top), (P.PATH_HALF, panel_front, floor_top + 0.008),
          "M_WallInterior")

    lamp_x = lamp_x if lamp_x is not None else r_in
    for (sx, nrm) in ((-lamp_x, (1.0, 0.0, 0.0)), (lamp_x, (-1.0, 0.0, 0.0))):
        P.wall_lamp((sx, 0.0, 2.55), nrm)


# ----------------------------------------------------------------------------------- v1
def _v1():
    R_OUT, T = 5.80, 0.28
    R_IN = R_OUT - T
    WALL_TOP, APEX = 5.50, 8.00
    DOOR_HEAD = 2.90
    BAY_HALF, BAY_FRONT, BAY_TOP = 2.40, -6.30, 5.10
    SEGS = 64

    P = K.Piece("content2", "v1", "L")
    P.notes.append("The drum is entered through a flat-fronted entrance block: a curved wall "
                   "has nowhere flat for a door leaf, a sign or a 16:9 screen.")

    floor_top = P.round_plinth(R_OUT, segs=SEGS, skirt=0.22)

    # the drum wall, opened where the entrance block meets it
    gap = math.degrees(math.asin(BAY_HALF / R_OUT))
    a0, span = 270.0 + gap, 360.0 - 2 * gap
    for (z0, z1) in ((0.0, 2.40), (3.80, WALL_TOP)):
        P.sb.ring((0.0, 0.0), R_IN, R_OUT, "xy", z0, z1, "M_Wall", segs=SEGS,
                  face_mat="M_Trim", start_deg=a0, span_deg=span, inner_mat="M_WallInterior")
    # ribbon window: glass at mid thickness, trim at sill and head, mullions every 12 degrees
    mid = (R_IN + R_OUT) / 2
    P.sb.ring((0.0, 0.0), mid - 0.03, mid + 0.03, "xy", 2.40, 3.80, "M_Glass", segs=SEGS,
              start_deg=a0, span_deg=span)
    for (za, zb) in ((2.32, 2.46), (3.74, 3.88)):
        P.sb.ring((0.0, 0.0), R_IN - 0.03, R_OUT + 0.05, "xy", za, zb, "M_Trim", segs=SEGS,
                  start_deg=a0, span_deg=span)
    n_mull = int(span // 12)
    for i in range(n_mull + 1):
        P.sb.ring((0.0, 0.0), R_IN, R_OUT + 0.04, "xy", 2.40, 3.80, "M_Trim", segs=SEGS,
                  start_deg=a0 + span * i / n_mull - 0.7, span_deg=1.4)
    # brand band on solid wall above the ribbon
    P.sb.ring((0.0, 0.0), R_OUT - 0.05, R_OUT + 0.07, "xy", 4.02, 4.38, "M_BrandAccent",
              segs=SEGS, start_deg=a0, span_deg=span)

    # domed roof: the outside is the roof, the inside is the room's ceiling
    P.sb.dome_shell((0.0, 0.0), R_OUT, R_IN, WALL_TOP, APEX - WALL_TOP, APEX - 0.26 - WALL_TOP,
                    "M_Roof", segs=48, rings=10, inner_mat="M_WallInterior", rim_mat="M_Trim")

    # entrance block
    for sx in (-1, 1):
        P.wall_run(along="y", outer=sx * BAY_HALF, out_sign=sx, t=T, a=BAY_FRONT, b=-5.05,
                   z0=0.0, z1=BAY_TOP)
    P.wall_run(along="x", outer=BAY_FRONT, out_sign=-1, t=T, a=-BAY_HALF, b=BAY_HALF,
               z0=0.0, z1=BAY_TOP,
               openings=[dict(center=0.0, width=DOOR_W, sill=0.0, head=DOOR_HEAD)])
    P.box((-BAY_HALF - 0.12, BAY_FRONT - 0.12, BAY_TOP), (BAY_HALF + 0.12, -5.00, BAY_TOP + 0.22),
          "M_Roof", faces={"-z": "M_WallInterior"})
    P.box((-BAY_HALF - 0.17, BAY_FRONT - 0.17, BAY_TOP + 0.22),
          (BAY_HALF + 0.17, -5.00, BAY_TOP + 0.32), "M_Trim")
    P.panel_joints(along="x", outer=BAY_FRONT, out_sign=-1, a=-BAY_HALF + 0.2, b=BAY_HALF - 0.2,
                   z0=0.55, z1=BAY_TOP - 0.2, pitch=0.78, skip=((-1.65, 1.65),))

    P.add_door(hinge=(-DOOR_W / 2, BAY_FRONT + T / 2, floor_top),
               width=DOOR_W, height=DOOR_HEAD - floor_top, open_sign=1)
    P.door_frame(along="x", outer=BAY_FRONT, out_sign=-1, t=T, center=0.0, width=DOOR_W,
                 head=DOOR_HEAD, mat="M_BrandAccent", w=0.16, proud=0.06)
    for sx in (-1, 1):
        P.wall_lamp((sx * 1.33, BAY_FRONT, 2.30), (0.0, -1.0, 0.0))

    P.entrance_step(center_x=0.0, y_out=BAY_FRONT - 0.58, y_in=BAY_FRONT + 0.06,
                    half_w=1.55, z_top=floor_top)
    P.entrance_mat(center_x=0.0, y0=BAY_FRONT - 0.42, y1=BAY_FRONT - 0.18, half_w=0.95, z=floor_top)
    for sx in (-1, 1):
        P.planter((sx * 3.35, BAY_FRONT + 0.36), size=(1.15, 0.78), h=0.56)
    for ang in (55.0, 125.0):
        P.downpipe(R_OUT * math.cos(math.radians(ang)) + 0.09 * math.cos(math.radians(ang)),
                   R_OUT * math.sin(math.radians(ang)) + 0.09 * math.sin(math.radians(ang)),
                   0.10, WALL_TOP - 0.15)

    panel_front = 4.60
    _interior(P, r_in=R_IN, panel_front=panel_front, panel_back=5.60, ceil_z=WALL_TOP,
              floor_top=floor_top, segs=SEGS, layout="a", start_deg=a0, span_deg=span)
    P.standard_interior(lo=(-3.0, -3.3, floor_top), hi=(3.0, panel_front, WALL_TOP),
                        door_center_x=0.0, lights_a=(2, 2), light_b_z=2.55, layout="a",
                        floor=False, skirt=False, side_lights=False,
                        switch_surface=(0.99, BAY_FRONT + T), screen_z=2.00)
    P.preview_int = ((-0.35, -5.40, floor_top + 1.74), (0.15, panel_front - 0.1, floor_top + 2.95))
    P.add_sign((0.0, BAY_FRONT, 4.05), (0.0, -1.0, 0.0), size=SIGN_SIZE, depth=0.13)
    P.standard_markers(roof_top=APEX, front_y=-R_OUT)
    return P


# ----------------------------------------------------------------------------------- v2
def _v2():
    R_OUT = 6.15
    TP = 0.28                                  # wall thickness measured on the facet
    R_IN = R_OUT - TP / math.cos(math.radians(15.0))
    WALL_TOP, CEIL_UNDER, APEX = 5.80, 5.60, 8.50
    DOOR_HEAD = 2.85
    EAVE_R, COL_R = 6.88, 6.52
    SEGS = 12
    FY_OUT = -R_OUT * math.cos(math.radians(15.0))      # front facet, outer face
    FY_IN = FY_OUT + TP
    FX = R_OUT * math.sin(math.radians(15.0))           # half width of a facet

    P = K.Piece("content2", "v2", "L")
    P.notes.append("Twelve facets with one of them flat to the front, so the door, the sign "
                   "and the brand-wrapped columns all sit on straight surfaces.")

    floor_top = P.round_plinth(R_OUT + 0.10, segs=SEGS, skirt=0.26)

    # eleven facets as a ring arc; the twelfth is the flat front wall
    P.sb.ring((0.0, 0.0), R_IN, R_OUT, "xy", 0.0, WALL_TOP, "M_Wall", segs=SEGS,
              face_mat="M_Trim", start_deg=285.0, span_deg=330.0, inner_mat="M_WallInterior")
    P.wall_run(along="x", outer=FY_OUT, out_sign=-1, t=TP, a=-FX, b=FX, z0=0.0, z1=WALL_TOP,
               openings=[dict(center=0.0, width=DOOR_W, sill=0.0, head=DOOR_HEAD)])

    # a window in every other facet
    for k in range(12):
        ang = 30.0 * k                       # facet centres
        if abs(((ang - 270.0) + 180) % 360 - 180) < 1.0 or k % 2:
            continue
        P.sb.ring((0.0, 0.0), R_IN - 0.02, R_OUT + 0.02, "xy", 1.25, 3.55, "M_Glass",
                  segs=SEGS, start_deg=ang - 9.0, span_deg=18.0)
        for (za, zb) in ((1.15, 1.27), (3.53, 3.65)):
            P.sb.ring((0.0, 0.0), R_IN, R_OUT + 0.05, "xy", za, zb, "M_Trim",
                      segs=SEGS, start_deg=ang - 10.5, span_deg=21.0)

    # cornice, ceiling and the folded twelve-sided roof
    P.sb.ring((0.0, 0.0), R_IN - 0.05, R_OUT + 0.10, "xy", WALL_TOP - 0.22, WALL_TOP, "M_Trim",
              segs=SEGS, start_deg=15.0)
    P.sb.disc((0.0, 0.0), R_IN + 0.02, "xy", CEIL_UNDER, WALL_TOP - 0.20, "M_Trim",
              segs=SEGS, cap_mat="M_WallInterior")
    P.sb.cone((0.0, 0.0), EAVE_R, WALL_TOP - 0.06, APEX, "M_Roof", segs=SEGS, start_deg=15.0)

    # ring of external columns, brand colour wrapped round each one, with a ring beam over
    for k in range(12):
        ang = math.radians(30.0 * k)
        if abs(30.0 * k - 270.0) < 1.0:
            continue                          # leave the entrance clear
        cx, cy = COL_R * math.cos(ang), COL_R * math.sin(ang)
        P.sb.disc((cx, cy), 0.26, "xy", 0.0, WALL_TOP - 0.10, "M_Trim", segs=10)
        P.sb.disc((cx, cy), 0.30, "xy", 0.95, 1.65, "M_BrandAccent", segs=10)
        P.sb.disc((cx, cy), 0.31, "xy", 0.0, 0.26, "M_Trim", segs=10)
    P.sb.ring((0.0, 0.0), COL_R - 0.30, COL_R + 0.30, "xy", WALL_TOP - 0.42, WALL_TOP - 0.10,
              "M_Trim", segs=SEGS, start_deg=0.0)

    P.add_door(hinge=(-DOOR_W / 2, FY_OUT + TP / 2, floor_top),
               width=DOOR_W, height=DOOR_HEAD - floor_top, open_sign=1)
    P.door_frame(along="x", outer=FY_OUT, out_sign=-1, t=TP, center=0.0, width=DOOR_W,
                 head=DOOR_HEAD, mat="M_BrandAccent", w=0.16, proud=0.06)
    for sx in (-1, 1):
        P.wall_lamp((sx * 1.32, FY_OUT, 2.25), (0.0, -1.0, 0.0))

    P.entrance_step(center_x=0.0, y_out=FY_OUT - 0.72, y_in=FY_OUT + 0.06, half_w=1.55, z_top=floor_top)
    P.entrance_mat(center_x=0.0, y0=FY_OUT - 0.48, y1=FY_OUT - 0.22, half_w=0.95, z=floor_top)
    for sx in (-1, 1):
        P.planter((sx * 3.05, FY_OUT - 0.22), size=(1.15, 0.78), h=0.56)
    face_r = R_OUT * math.cos(math.radians(15.0)) + 0.09
    for ang in (60.0, 120.0):                     # facet centres, so the pipe sits on flat wall
        a = math.radians(ang)
        P.downpipe(face_r * math.cos(a), face_r * math.sin(a), 0.10, WALL_TOP - 0.30)

    panel_front = 4.70
    _interior(P, r_in=R_IN, panel_front=panel_front,
              panel_back=5.70, ceil_z=CEIL_UNDER, floor_top=floor_top, segs=SEGS, layout="b",
              start_deg=285.0, span_deg=330.0,
              lamp_x=R_IN * math.cos(math.radians(15.0)))
    P.standard_interior(lo=(-3.0, -3.3, floor_top), hi=(3.0, panel_front, CEIL_UNDER),
                        door_center_x=0.0, lights_a=(2, 2), light_b_z=2.55, layout="b",
                        floor=False, skirt=False, side_lights=False,
                        switch_surface=(0.99, FY_IN), screen_z=2.00)
    P.preview_int = ((-0.35, -4.60, floor_top + 1.74), (0.15, panel_front - 0.1, floor_top + 2.85))
    P.add_sign((0.0, FY_OUT, 3.95), (0.0, -1.0, 0.0), size=SIGN_SIZE, depth=0.13)
    P.standard_markers(roof_top=APEX, front_y=FY_OUT)
    return P
