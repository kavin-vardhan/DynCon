from pathlib import Path
from reportlab.pdfgen import canvas
from reportlab.lib.colors import HexColor
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph
from reportlab.lib.styles import ParagraphStyle

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'output' / 'pdf'
OUT.mkdir(parents=True, exist_ok=True)
for name, filename in [('Regular', 'segoeui.ttf'), ('Bold', 'segoeuib.ttf')]:
    pdfmetrics.registerFont(TTFont(name, str(Path('C:/Windows/Fonts') / filename)))

W, H = 1440, 1080
NAVY = '#132D40'
INK = '#19354A'
MUTED = '#526575'
LINE = '#D6E0E6'
BLUE = '#215CC1'
TEAL = '#00796F'
PALE_BLUE = '#EFF5FE'
PALE_TEAL = '#EAF6F2'
PAPER = '#FFFFFF'
LIGHT = '#F4F7F9'
GOLD = '#9B6516'
pdf = OUT / 'dynamiccontents-demo-flow.pdf'
c = canvas.Canvas(str(pdf), pagesize=(W, H))
c.setTitle('DynamicContents | Tokyo demo flow')
c.setAuthor('DynamicContents')
c.setSubject('Planned five-minute booth experience, based on Tokyo demo plan v3')

def box(x, y, w, h, fill, radius=0, stroke=None):
    c.setFillColor(HexColor(fill))
    c.setStrokeColor(HexColor(stroke or fill))
    if radius:
        c.roundRect(x, H-y-h, w, h, radius, fill=1, stroke=bool(stroke))
    else:
        c.rect(x, H-y-h, w, h, fill=1, stroke=bool(stroke))

def text(s, x, y, size=18, color=INK, bold=False):
    c.setFont('Bold' if bold else 'Regular', size)
    c.setFillColor(HexColor(color))
    c.drawString(x, H-y-size, s)

def para(s, x, y, w, size=18, color=INK, bold=False, maxh=None):
    style = ParagraphStyle('p', fontName='Bold' if bold else 'Regular', fontSize=size,
                           leading=size*1.32, textColor=HexColor(color))
    p = Paragraph(s, style)
    _, h = p.wrap(w, H)
    if maxh is not None and h > maxh:
        raise ValueError(f'Text too tall: {s!r}: {h} > {maxh}')
    p.drawOn(c, x, H-y-h)
    return h

def line(x1,y1,x2,y2,color=LINE,width=1):
    c.setStrokeColor(HexColor(color)); c.setLineWidth(width)
    c.line(x1,H-y1,x2,H-y2)

def arrow(x1,y1,x2,y2,color=MUTED,width=1.8):
    import math
    line(x1,y1,x2,y2,color,width)
    a = math.atan2(y2-y1, x2-x1)
    for d in [-0.55,0.55]:
        line(x2,y2,x2-8*math.cos(a+d),y2-8*math.sin(a+d),color,width)

def number(n,x,y,active=False):
    color = TEAL if active else NAVY
    c.setFillColor(HexColor(color)); c.circle(x,H-y,19,fill=1,stroke=0)
    c.setFont('Bold',18); c.setFillColor(HexColor(PAPER))
    c.drawCentredString(x,H-y-6,str(n))

def footer(page):
    line(48,1032,1392,1032)
    text('Source: DynamicContents Tokyo demo plan v3 | 21 September 2026',48,1044,13,MUTED)
    text('PLANNED EXPERIENCE  /  '+str(page)+' OF 2',1122,1044,13,MUTED)

# PAGE 1 - synchronized lanes, top-to-bottom sequence.
box(0,0,W,H,PAPER)
text('DYNAMICCONTENTS  /  TOKYO',48,30,15,TEAL,True)
text('One street. Two roles. A world that changes live.',48,58,38,NAVY,True)
text('The planned 5-minute demo, from picking up a controller to the next visitor.',48,111,21,MUTED)

box(48,157,1344,61,NAVY,10)
text('1 PC',70,175,19,PAPER,True)
text('2 monitors',172,175,19,PAPER)
text('2 controllers',326,175,19,PAPER)
text('Player = left screen / pad 1',552,175,18,PAPER)
text('Brand = right screen / pad 2',934,175,18,PAPER)

box(48,233,1344,55,LIGHT,8)
text('BEFORE THE TOUR',66,248,14,MUTED,True)
text('Idle street: built-in house campaigns compete every 2 minutes; buildings change. Pick up a controller to begin.',249,247,17,INK)

text('ACT / START',48,312,13,MUTED,True)
text('PLAYER  /  WHAT THEY DO & SEE',270,308,16,BLUE,True)
text('BRAND  /  WHAT THEY CONTROL',710,308,16,TEAL,True)
text('VISIBLE RESULT',1132,308,16,NAVY,True)
line(48,341,1392,341)

rows = [
    ('1','0:00','Arrive',
     'Pick a profile. Explore the street.',
     'The returning profile already owns and wears a jacket.',
     'Show Player B beside the portal.',
     'A different profile and low-spec setting receive a different Lane stall and lighter content.',
     'Same street.\nDifferent experience.'),
    ('2','0:30','Be the brand',
     'Explore while the Brand sets up.',
     'The Corner slot starts as the house ramen shop.',
     'Set up a campaign and submit.',
     'Package → fit → rating → sign → auction. The default bid wins.',
     'The campaign wins\na place in the world.'),
    ('3','1:30','It appears',
     'Walk toward the Corner slot.',
     'Content downloads and is checked. The new building appears; walk in and interact.',
     'Watch campaign activity arrive live.',
     'Views, time inside and spend begin updating.',
     'New content arrives\nwithout a loading screen.'),
    ('4','2:30','Shop',
     'Visit the Plaza clothing store.',
     'Try on, then buy with demo credits. A redeemed digital item stays owned.',
     'Change a price; watch the funnel.',
     'Seen → tried → bought. A physical item produces a mock order reference and QR.',
     'Try-on is temporary.\nA purchase is owned.'),
    ('5','3:45','The live update',
     'Collect 3 of 5 tokens in the Brand building.',
     'Stay inside for the update, then exit and re-enter. Progress is still 3 of 5; the jacket stays on.',
     'Push the Season 2 update.',
     'The update waits while the Player is inside, then swaps when they leave.',
     'The building changes.\nProgress survives.'),
    ('6','4:45','Budget out',
     'Watch the house campaign return.',
     'If still inside, the handback waits until the Player leaves.',
     'Campaign credits reach zero.',
     'The slot is re-auctioned; the house wins it back. Show the campaign summary.',
     'The campaign ends.\nThe game keeps running.'),
]

start, rh = 349, 90
for i,(n,t,title,p1,p2,b1,b2,result) in enumerate(rows):
    y = start+i*rh
    if n=='5': box(48,y,1344,rh-4,PALE_TEAL,8)
    elif i%2==0: box(250,y,1142,rh-4,'#F8FAFC',5)
    if i<5: arrow(70,y+46,70,y+rh+15,TEAL if n=='5' else LINE,2)
    number(n,70,y+27,n=='5')
    text(t,103,y+5,15,TEAL if n=='5' else MUTED,True)
    text(title,103,y+30,18,INK,True)
    ph=para(p1,270,y+8,407,17,INK,True,maxh=46)
    para(p2,270,y+12+ph,407,15.5,MUTED,maxh=rh-18-ph)
    bh=para(b1,710,y+8,389,17,INK,True,maxh=46)
    para(b2,710,y+12+bh,389,15.5,MUTED,maxh=rh-18-bh)
    para(result.replace('\n','<br/>'),1132,y+19,242,18,TEAL if n=='5' else INK,True,maxh=65)

box(48,903,1344,46,NAVY,8)
text('RESET → ATTRACT → NEXT VISITOR',66,916,16,PAPER,True)
text('Visitor campaign and progress clear. The running game returns to the idle street.',435,916,16,PAPER)
text('ALL TOUR LONG',48,965,13,TEAL,True)
text('Build number • uptime • restarts: 0 • loading screens: 0',201,961,18,INK,True)
text('90-SECOND EXPRESS',48,997,13,MUTED,True)
text('Act 2 on defaults (three button presses) → Act 3: approach, watch it appear, enter.',249,993,17,INK)
footer(1)
c.showPage()

# PAGE 2 - three causal flows and clearly separated optional paths.
box(0,0,W,H,PAPER)
text('DYNAMICCONTENTS  /  KEY MOMENTS',48,30,15,TEAL,True)
text('What makes the demo convincing',48,58,38,NAVY,True)
text('Three simple cause-and-effect sequences to explain while the visitor plays.',48,111,21,MUTED)

def chain_node(x,y,w,label,detail,color=BLUE,fill=PALE_BLUE):
    box(x,y,w,104,fill,8)
    text(label,x+17,y+14,20,color,True)
    para(detail,x+17,y+47,w-34,17,INK,maxh=53)

text('01',48,164,16,BLUE,True)
text('Publish → appear',89,158,25,NAVY,True)
text('Act 2 → Act 3',1198,165,16,MUTED)
xs=[48,322,596,870,1144]
labels=[('Submit','Pick a ready-made building and campaign settings.'),
        ('Check & allocate','Validate and sign; win the auction for a slot.'),
        ('Player approaches','The game looks up the winning content.'),
        ('Load safely','Download → verify → mount into the game.'),
        ('Enter & interact','The building appears. Live campaign stats update.')]
for i,(lab,detail) in enumerate(labels):
    chain_node(xs[i],205,248,lab,detail)
    if i<4: arrow(xs[i]+252,257,xs[i+1]-5,257,BLUE)
text('On-screen proof',48,324,15,BLUE,True)
text('Resolving → downloading → verifying → mounting → active. Re-publish the same building: cache hit.',210,321,17,INK)

line(48,365,1392,365)
text('02',48,389,16,TEAL,True)
text('Update the building. Keep the progress.',89,383,25,NAVY,True)
text('Act 5 / headline moment',1160,391,15,TEAL,True)

swap=[('Play Season 1','Inside the building, collect 3 of 5 tokens.'),
      ('Brand pushes S2','The update is queued. The Player keeps playing.'),
      ('Player exits','Save progress and release the old building.'),
      ('Season 2 appears','Load the new version and restore saved progress.'),
      ('Player re-enters','Still 3 of 5 tokens. Purchased jacket still owned.')]
for i,(lab,detail) in enumerate(swap):
    chain_node(xs[i],431,248,lab,detail,TEAL,PALE_TEAL)
    if i<4: arrow(xs[i]+252,483,xs[i+1]-5,483,TEAL)
text('On-screen proof',48,550,15,TEAL,True)
text('“Swap pending” while occupied → swap after exit → matching progress before and after.',210,547,17,INK)

line(48,591,1392,591)
text('03',48,615,16,BLUE,True)
text('Try it. Buy it. Keep it.',89,609,25,NAVY,True)
text('Act 4 / simulated store',1190,617,15,MUTED)

commerce=[('Try on','Temporary preview; leaving removes it.'),
          ('Choose to buy','Pay with demo credits in the simulated store.'),
          ('Receive receipt','The store returns a signed demo receipt.'),
          ('Redeem','Server verifies the receipt and records ownership.'),
          ('Get the item','Digital: permanent item. Physical: mock ref + QR.')]
for i,(lab,detail) in enumerate(commerce):
    chain_node(xs[i],657,248,lab,detail)
    if i<4: arrow(xs[i]+252,709,xs[i+1]-5,709,BLUE)
text('On-screen proof',48,776,15,BLUE,True)
text('Seen → tried → bought. The returning profile starts with a pre-seeded jacket to show ownership across sessions.',210,773,17,INK)

line(48,817,1392,817)
text('OPTIONAL DETOURS',48,838,14,MUTED,True)
text('Use only when a visitor asks',244,835,17,MUTED)
optional=[('Invalid content','Too tall or wrong age rating → reject with a reason.'),
          ('Low bid','House wins → the ramen shop stays in place.'),
          ('Download problem','Corrupt: placeholder + retry. Paused: resume download.')]
for x,(title,detail) in zip([48,507,966],optional):
    text(title,x,873,18,INK,True)
    para(detail,x,903,414,16,MUTED,maxh=45)

box(48,966,1344,47,LIGHT,8)
text('DEMO BOUNDARY',65,981,13,MUTED,True)
text('Prebuilt content • automatic checks • demo credits • mock fulfilment • local PC backend by default',247,978,17,INK)
footer(2)
c.save()
print(pdf)
