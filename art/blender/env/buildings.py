"""Background blocks, the arcade and the shed.

These frame the slots; they are **not** content. Every one of them is closed - no doors, no
openings a Player could walk into, nothing that could be mistaken for a piece of dynamic
content. They are told apart from the content the same way the content pieces are told apart
from each other: by shape and tone, never by theme, and never by text, a sign or a logo.

Anchor convention: origin at the ground-contact centre, long axis along +X, the face that is
meant to address the street looks along **-Y**.
"""

import env_kit as E

PIECES = ("block_low", "block_mid", "block_tall", "arcade", "shed")


def _block(pid, palette, *, hx, hy, storeys, storey_h, base_h=0.55, parapet=0.85,
           cols_x=5, cols_y=4, alt=False):
    """One closed background block: base course, walls, window grid, cornice, parapet."""
    top = base_h + storeys * storey_h
    wall = "M_WallAlt" if alt else "M_Wall"
    P = E.EnvPiece(pid, "building", palette=palette, collision="blocking",
                   footprint=(hx * 2, hy * 2))
    P.notes.append("Closed: no door and no opening. It frames a slot, it is not content.")

    # base course, a little proud
    P.box((-hx - 0.10, -hy - 0.10, 0.0), (hx + 0.10, hy + 0.10, base_h), "M_Trim")
    # the shell
    P.box((-hx, -hy, base_h), (hx, hy, top), wall)
    # cornice
    P.box((-hx - 0.18, -hy - 0.18, top), (hx + 0.18, hy + 0.18, top + 0.22), "M_Trim")
    # roof deck and parapet
    P.box((-hx, -hy, top + 0.22), (hx, hy, top + 0.30), "M_Roof")
    for (ax, ay, bx, by) in ((-hx, -hy, hx, -hy + 0.22), (-hx, hy - 0.22, hx, hy),
                             (-hx, -hy, -hx + 0.22, hy), (hx - 0.22, -hy, hx, hy)):
        P.box((ax, ay, top + 0.22), (bx, by, top + 0.22 + parapet), "M_Trim")

    # a storey band at every floor line, so height reads at a distance
    for s in range(1, storeys):
        z = base_h + s * storey_h
        P.box((-hx - 0.06, -hy - 0.06, z - 0.09), (hx + 0.06, hy + 0.06, z + 0.03), "M_Trim")

    # windows on all four faces
    for s in range(storeys):
        z0 = base_h + s * storey_h + 0.45
        z1 = base_h + (s + 1) * storey_h - 0.35
        P.window_grid(along="x", outer=-hy, out_sign=-1.0, a=-hx + 1.1, b=hx - 1.1,
                      z0=z0, z1=z1, rows=1, cols=cols_x)
        P.window_grid(along="x", outer=hy, out_sign=1.0, a=-hx + 1.1, b=hx - 1.1,
                      z0=z0, z1=z1, rows=1, cols=cols_x)
        P.window_grid(along="y", outer=-hx, out_sign=-1.0, a=-hy + 1.1, b=hy - 1.1,
                      z0=z0, z1=z1, rows=1, cols=cols_y)
        P.window_grid(along="y", outer=hx, out_sign=1.0, a=-hy + 1.1, b=hy - 1.1,
                      z0=z0, z1=z1, rows=1, cols=cols_y)
    return P


def block_low(palette):
    """Two storeys, 14 x 10 m - the everyday block that lines a side street."""
    return _block("block_low", palette, hx=7.0, hy=5.0, storeys=2, storey_h=3.5,
                  cols_x=5, cols_y=3)


def block_mid(palette):
    """Four storeys, 16 x 12 m, the second wall tone - a row of these is not one colour."""
    return _block("block_mid", palette, hx=8.0, hy=6.0, storeys=4, storey_h=3.4,
                  cols_x=6, cols_y=4, alt=True)


def block_tall(palette):
    """Six storeys, 14 x 14 m - the back of the skyline, behind the tall slot."""
    return _block("block_tall", palette, hx=7.0, hy=7.0, storeys=6, storey_h=3.3,
                  cols_x=5, cols_y=5)


def arcade(palette):
    """16 m of colonnade, 5 m deep: piers, arches and a roof you can walk under."""
    P = E.EnvPiece("arcade", "building", palette=palette, collision="blocking",
                   footprint=(16.0, 5.0))
    P.notes.append("Runs along +X, open on -Y; walk through between the piers.")
    hx, hy = 8.0, 2.5
    pier_w, pier_d = 0.72, 0.72
    head = 4.3
    bays = 5
    step = (2 * hx - pier_w) / bays
    crown_top = head + (step - pier_w) / 2.0 + 0.55
    top = crown_top + 0.75

    # back wall, closed
    P.box((-hx, hy - 0.45, 0.0), (hx, hy, top), "M_Wall")
    # plinth under the whole thing
    P.box((-hx, -hy, 0.0), (hx, hy, 0.16), "M_Paving")

    y_front = -hy + 0.25
    for i in range(bays + 1):
        x = -hx + pier_w / 2 + i * step
        P.box((x - pier_w / 2, y_front, 0.16), (x + pier_w / 2, y_front + pier_d, head),
              "M_Trim")

    # the spandrel over each bay: a rectangle with a semicircular arch taken out of it
    for i in range(bays):
        xa = -hx + pier_w + i * step
        xb = xa + step - pier_w
        mid = (xa + xb) / 2.0
        r = (xb - xa) / 2.0
        crown = head + r + 0.55
        prof = E.MeshBuilder.arc2d(mid, head, r, 8, 180.0, -180.0)
        prof = prof + [(xb, crown), (xa, crown)]
        P.extrude(prof, "xz", y_front, y_front + pier_d, "M_Wall", cap_mat="M_Wall")

    # entablature over the arches, then the roof
    P.box((-hx, y_front - 0.12, crown_top), (hx, hy, crown_top + 0.30), "M_Trim")
    P.box((-hx - 0.22, y_front - 0.22, crown_top + 0.30), (hx + 0.22, hy + 0.12, top),
          "M_Roof")
    # ceiling of the walkway, between the piers and the back wall
    P.box((-hx, y_front + pier_d, head), (hx, hy - 0.45, head + 0.16), "M_Trim")
    return P


def shed(palette):
    """6 x 4 m mono-pitch timber shed: the small thing that makes a waterfront a working one."""
    P = E.EnvPiece("shed", "building", palette=palette, collision="blocking",
                   footprint=(6.0, 4.0))
    hx, hy = 3.0, 2.0
    P.box((-hx - 0.08, -hy - 0.08, 0.0), (hx + 0.08, hy + 0.08, 0.22), "M_Trim")
    # walls as vertical boarding
    boards = 16
    step = (2 * hx) / boards
    for i in range(boards):
        x0 = -hx + i * step + 0.015
        x1 = x0 + step - 0.03
        for (y0, y1) in ((-hy, -hy + 0.12), (hy - 0.12, hy)):
            P.box((x0, y0, 0.22), (x1, y1, 3.0), "M_Timber")
    for (xa, xb) in ((-hx, -hx + 0.12), (hx - 0.12, hx)):
        P.box((xa, -hy, 0.22), (xb, hy, 3.0), "M_Timber")
    # mono-pitch roof, falling towards -Y
    P.extrude([(-hy - 0.35, 2.95), (hy + 0.35, 3.45), (hy + 0.35, 3.60), (-hy - 0.35, 3.10)],
              "yz", -hx - 0.3, hx + 0.3, "M_Roof")
    # a shuttered opening, closed
    P.box((-1.1, -hy - 0.06, 0.6), (1.1, -hy + 0.02, 2.3), "M_Trim")
    for i in range(7):
        z = 0.72 + i * 0.22
        P.box((-1.05, -hy - 0.09, z), (1.05, -hy - 0.055, z + 0.13), "M_Timber")
    return P


BUILDERS = {name: globals()[name] for name in PIECES}
