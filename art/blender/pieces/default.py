"""`default` — the developer's default placeholder (spec v1 §3).

Size class S. v1 only. An open canopy: plinth, four posts, flat roof slab, a bench.
Deliberately has NO door, switches, screen, sign or brand accent — it is what a slot shows
before anything is resolved into it, so it must never look like a brand's content.
"""

import dc_kit as K

PALETTE = {
    "M_Wall":         {"color": "#C8C6C1"},
    "M_WallInterior": {"color": "#D4D2CD"},
    "M_Floor":        {"color": "#8D8B86"},
    "M_Roof":         {"color": "#6A6966"},
    "M_Trim":         {"color": "#56554F"},
}

HX = HY = 3.0           # 6 x 6 m plinth
POST = 0.30
ROOF_UNDER = 3.80       # underside of the fascia, i.e. the clear height under the canopy
ROOF_TOP = 4.02

VERSIONS = ("v1",)


def build(version):
    P = K.Piece("default", version, "S", palette=PALETTE)
    P.notes.append("Placeholder: no door, switches, screen, sign or brand accent by design.")
    P.notes.append("Roof underside is 3.80 m (not ~3.6) so the canopy still clears 3.5 m above the deck.")

    floor_top = P.plinth(HX, HY, skirt=0.18, base_h=0.09, deck_h=0.05)

    # four posts
    for sx in (-1, 1):
        for sy in (-1, 1):
            x, y = sx * (HX - 0.60), sy * (HY - 0.60)
            P.box((x - POST / 2, y - POST / 2, floor_top - 0.03),
                  (x + POST / 2, y + POST / 2, ROOF_UNDER + 0.06), "M_Trim")

    # flat roof slab with a fascia band under its edge
    roof_top = P.flat_roof(HX, HY, ROOF_UNDER + 0.08, ROOF_TOP, overhang=0.20)

    # a bench, off to one side
    P.bench((1.25, 1.50, floor_top), length=1.9, depth=0.52, seat_z=floor_top + 0.46, axis="x")

    P.interior_volume((-HX + 0.45, -HY + 0.45, floor_top), (HX - 0.45, HY - 0.45, ROOF_UNDER))
    P.standard_markers(roof_top=roof_top, front_y=-HY)

    # under the canopy, looking across it — aimed slightly up so the roof soffit frames the shot
    P.preview_int = ((-4.60, -5.10, floor_top + 1.56), (1.10, 1.30, floor_top + 1.90))
    return P
