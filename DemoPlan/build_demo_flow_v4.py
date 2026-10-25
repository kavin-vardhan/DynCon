"""Generate the v4 visitor flow as a simple, editable vector chart and PDF."""
from pathlib import Path
from html import escape
from reportlab.pdfgen import canvas
from reportlab.lib.colors import HexColor
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'output' / 'pdf'
OUT.mkdir(parents=True, exist_ok=True)
STEM = 'dynamiccontents-demo-flow-v4'
W, H = 900, 1666
for name, file in [('Regular','segoeui.ttf'), ('Bold','segoeuib.ttf')]:
    pdfmetrics.registerFont(TTFont(name, str(Path('C:/Windows/Fonts') / file)))

c = canvas.Canvas(str(OUT / (STEM+'.pdf')), pagesize=(W,H))
c.setTitle('DynamicContents v4 - demo flowchart')
c.setAuthor('DynamicContents')
c.setSubject('Main visitor path from the Tokyo demo plan v4; planned experience')
svg = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" role="img" aria-labelledby="title desc">',
       '<title id="title">DynamicContents v4 demo flowchart</title>',
       '<desc id="desc">Follow eight steps from starting the stamp rally, booking a venue, playing, updating without losing progress, and booking expiry to the next visitor.</desc>']
INK='#183448'; MUTED='#526879'; BLUE='#245EB3'; TEAL='#00776C'; LINE='#8296A5'

def rect(x,y,w,h,fill,stroke=None,r=0,sw=1):
    c.setFillColor(HexColor(fill)); c.setStrokeColor(HexColor(stroke or fill)); c.setLineWidth(sw)
    c.roundRect(x,H-y-h,w,h,r,fill=1,stroke=bool(stroke))
    svg.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{r}" fill="{fill}" stroke="{stroke or "none"}" stroke-width="{sw}"/>')

def txt(s,x,y,size=19,color=INK,bold=False,center=False):
    font='Bold' if bold else 'Regular'
    c.setFont(font,size); c.setFillColor(HexColor(color))
    if center: c.drawCentredString(x,H-y,s)
    else: c.drawString(x,H-y,s)
    svg.append(f'<text x="{x}" y="{y}" font-family="Segoe UI, Arial, sans-serif" font-size="{size}" font-weight="{700 if bold else 400}" fill="{color}" text-anchor="{"middle" if center else "start"}">{escape(s)}</text>')

def multiline(s,x,y,w,size=19,color=INK,bold=False,max_lines=3):
    lines=[]
    for paragraph in s.split('\n'):
        current=''
        for word in paragraph.split():
            trial=(current+' '+word).strip()
            if pdfmetrics.stringWidth(trial,'Bold' if bold else 'Regular',size)>w:
                lines.append(current); current=word
            else: current=trial
        lines.append(current)
    assert len(lines)<=max_lines, (s,lines)
    for j,line in enumerate(lines): txt(line,x,y+j*25,size,color,bold)
    return len(lines)*25

def segment(x1,y1,x2,y2,color=LINE,width=2.5):
    c.setStrokeColor(HexColor(color)); c.setLineWidth(width)
    c.line(x1,H-y1,x2,H-y2)
    svg.append(f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{color}" stroke-width="{width}"/>')

def arrow(x,y1,y2,color=LINE):
    segment(x,y1,x,y2,color)
    segment(x,y2,x-6,y2-8,color)
    segment(x,y2,x+6,y2-8,color)

rect(0,0,W,H,'#FFFFFF')
txt('DYNAMICCONTENTS  /  TOKYO DEMO  /  V4',48,46,15,TEAL,True)
txt('How the demo unfolds',48,98,40,INK,True)
txt('One street. Two controllers. About five minutes.',48,133,21,MUTED)
txt('PLAYER',48,180,14,BLUE,True)
txt('Play a stamp rally',118,180,18,INK)
txt('BRAND',457,180,14,TEAL,True)
txt('Book venues with demo credits',525,180,18,INK)
txt('Demo clock: 1 demo hour = 1 real minute',48,213,17,MUTED)
txt('Planned experience',682,213,15,MUTED)

steps = [
    ('0:00','PLAYER','Start the stamp rally',
     'Pick a profile. Collect tokens and earn stamps by playing activities inside venues.'),
    ('0:30','BRAND','Book a place on the street',
     'Compare footfall and bids. Choose a slot, building and hours. Checks pass; win a 3-hour booking.'),
    ('1:30','PLAYER','A new venue appears',
     'Follow the “new venue” ping. Walk in and explore. The game carries on without a loading screen.'),
    ('2:15','PLAYER + BRAND','Play the activity. See the results.',
     'Player works toward a stamp. Brand watches live views, visits and time spent in the venue.'),
    ('3:15','BRAND','Send the Season 2 update',
     'Player is still inside, at 3 of 5 tokens. The update waits until the Player leaves.'),
    ('','PLAYER','Walk out, then back in',
     'Season 2 replaces the venue after exit.\nProgress is still 3 of 5 tokens.'),
    ('4:30','PLAYER + BRAND','The booking runs out',
     'The next auction brings back the original venue.\nEarned stamps stay; the swap waits if the Player is inside.'),
    ('END','BOOTH','Reset for the next visitor',
     'Reset the booking, credits, stamps and progress.\nReturn to the idle street with the game still running.'),
]

X,BW,BH,GAP,Y = 155,697,125,35,245
for i,(time,role,title,detail) in enumerate(steps):
    y=Y+i*(BH+GAP)
    active=i in (4,5)
    fill='#EAF6F2' if active else ('#F1F5F8' if i in (0,7) else '#FFFFFF')
    stroke=TEAL if active else '#C9D5DE'
    accent=TEAL if active or role=='BRAND' else BLUE
    rect(X,y,BW,BH,fill,stroke,14 if i in (0,7) else 8,1.4)
    txt(time,48,y+46,20,MUTED,True)
    txt(f'{i+1:02d}',X+19,y+33,17,accent,True)
    txt(role,X+61,y+25,12,accent,True)
    txt(title,X+61,y+53,25,INK,True)
    assert pdfmetrics.stringWidth(title,'Bold',25) <= BW-85, title
    multiline(detail,X+61,y+80,BW-86,18,INK,max_lines=2)
    if i<7: arrow(X+BW/2,y+BH+6,y+BH+GAP-7,TEAL if i==4 else LINE)

rect(48,1551,804,46,INK,r=7)
txt('The building changes. The Player keeps playing.',450,1581,22,'#FFFFFF',True,True)
txt('Main route shown. Times are approximate; the booking lasts 3 real minutes from the win.',48,1622,14,MUTED)
txt('Source: DynamicContents_Tokyo_demo_plan_v4.md',48,1646,13,MUTED)
c.save()
svg.append('</svg>')
(OUT/(STEM+'.svg')).write_text('\n'.join(svg),encoding='utf-8')
print(OUT/(STEM+'.pdf'))
print(OUT/(STEM+'.svg'))
