#!/usr/bin/env python3
"""Build editable DemoFlow and DemoFlowSimple in draw.io, SVG, and PNG.

Requirements: Python 3.10+, Pillow, resvg-py (pip install Pillow resvg-py).
Run: python make_demo_flow.py [--output-dir PATH] [--font-dir PATH]
No diagrams.net application, browser, or network is needed to generate files.
The data below follows section 4 of the v6 plan and the supplied diagram brief.
Two cross-column hand-offs require orthogonal jogs; all others are vertical.
"""
from __future__ import annotations

import argparse
import html
import json
import re
from pathlib import Path
from xml.etree import ElementTree as ET

from PIL import Image, ImageFont
import resvg_py

WIDTH, HEIGHT = 1920, 1080
TITLE = 'Demo flow: bid to live content'
LEGEND = 'solid = next step, dashed = hand-off, bold = key moment'
FOOTER = 'One build, never restarts  |  No content loading screens  |  Demo credits only'
INK, LINE, GRID = '#233444', '#607180', '#DAE1E7'
FONT = 'Arial'
GRID_LEFT, COLUMN_WIDTH, BOX_WIDTH = 242.0, 165.4, 146.0

LANES = [
    dict(id='brand', label='BRAND', sub=['portal, right screen'], y=192, h=184, tint='#EDF4FB'),
    dict(id='platform', label='PLATFORM', sub=['server'], y=384, h=184, tint='#EAF6F2'),
    dict(id='game', label='GAME', sub=['player in mock region,', 'left screen'], y=576, h=258, tint='#F3EFF9'),
    dict(id='other', label='OTHER REGION', sub=['player in mock region 2,', 'preview window'], y=842, h=148, tint='#FFF3E5'),
]

# Column ranges share the exact same grid in every lane. Y varies only where
# the brief assigns two sequential Game events to overlapping column ranges.
BOXES = [
    dict(id='create', lane='brand', col=1, text='Create brand', sub='colour + emblem'),
    dict(id='upload', lane='brand', col=2, text='Upload content'),
    dict(id='game_pick', lane='brand', col=3, text='Pick a game'),
    dict(id='map', lane='brand', col=4, text='Slot map + footfall'),
    dict(id='bid', lane='brand', col=5, text='Pick regions, bid'),
    dict(id='won', lane='brand', col=6, text='Won', sub='nothing else to do'),
    dict(id='report', lane='brand', col=8, text='Report'),
    dict(id='push', lane='brand', col=9, text='Push update'),
    dict(id='summary', lane='brand', col=10, text='Summary'),
    dict(id='check', lane='platform', col=2, text='Check + sign'),
    dict(id='auction', lane='platform', col=5, text='Timed auction per region'),
    dict(id='allocation', lane='platform', col=6, text='Allocation written'),
    dict(id='telemetry', lane='platform', col=8, text='Telemetry'),
    dict(id='queue', lane='platform', col=9, text='New version queued'),
    dict(id='block', lane='platform', col=10, text='Block ends'),
    dict(id='near', lane='game', col=6, y=612, h=78, text='Player nears slot'),
    dict(id='fetch', lane='game', col=7, y=612, h=78, text='Fetch, verify, mount'),
    dict(id='appears', lane='game', col=7, end_col=8, y=729, h=82,
         text='Content appears', sub='no loading screen', key=True),
    dict(id='swap', lane='game', col=9, y=707, h=104,
         text='Swaps after player exits', sub='state kept', key=True),
    dict(id='next', lane='game', col=10, y=707, h=104, text='Next winner swaps in'),
    dict(id='rival', lane='other', col=7, end_col=8, y=878, h=80,
         text="Rival's content here", sub='mock region bid only', key=True),
]

# Each edge is part of the single source data used by both SVG and draw.io.
# Route types are lane sequence, vertical hand-off, or explicit orthogonal jog.
ARROWS = [
    *[dict(source=a, target=b, kind='solid', route='horizontal') for a,b in zip(
        ['create','upload','game_pick','map','bid','won','report','push'],
        ['upload','game_pick','map','bid','won','report','push','summary'])],
    *[dict(source=a, target=b, kind='solid', route='horizontal') for a,b in zip(
        ['check','auction','allocation','telemetry','queue'],
        ['auction','allocation','telemetry','queue','block'])],
    dict(source='near', target='fetch', kind='solid', route='horizontal'),
    dict(source='fetch', target='appears', kind='solid', route='vertical', column=7),
    dict(source='appears', target='swap', kind='solid', route='horizontal_jog'),
    dict(source='swap', target='next', kind='solid', route='horizontal'),
    dict(source='upload', target='check', kind='dashed', route='vertical', column=2),
    dict(source='bid', target='auction', kind='dashed', route='vertical', column=5),
    dict(source='auction', target='won', kind='dashed', route='auction_win'),
    dict(source='allocation', target='near', kind='dashed', route='vertical', column=6),
    dict(source='allocation', target='rival', kind='dashed', route='region'),
    dict(source='appears', target='telemetry', kind='dashed', route='vertical', column=8),
    dict(source='telemetry', target='report', kind='dashed', route='vertical', column=8),
    dict(source='push', target='queue', kind='dashed', route='vertical', column=9),
    dict(source='queue', target='swap', kind='dashed', route='vertical', column=9),
    dict(source='block', target='next', kind='dashed', route='vertical', column=10),
    dict(source='block', target='summary', kind='dashed', route='vertical', column=10),
]

# Plain-language companion: the winning path, with three short outcome notes.
SIMPLE_TITLE = 'The demo, in simple terms'
SIMPLE_SUBTITLE = 'You choose the building. The player keeps playing.'
SIMPLE_FOOTER = 'The game keeps running  |  No loading screens  |  Pretend credits only'
SIMPLE_BOXES = [
    dict(id='s_create', role='You', text='Create your brand', sub='Colour, symbol, add building', fill='#EDF4FB'),
    dict(id='s_place', role='You', text='Choose your place', sub='Game, spot, mock region', fill='#EDF4FB'),
    dict(id='s_bid', role='You', text='Bid and win', sub='Use pretend credits', fill='#EDF4FB'),
    dict(id='s_appear', role='Player', text='Your building appears', sub='Player walks nearby', fill='#EAF6F2', key=True),
    dict(id='s_report', role='You', text='See who visits', sub='Visits and time spent', fill='#EDF4FB'),
    dict(id='s_update', role='You + Player', text='Update the building', sub='After the player leaves', fill='#EAF6F2', key=True),
    dict(id='s_end', role='Player', text='Time runs out', sub='Another building replaces yours', fill='#F3EFF9'),
    dict(id='s_region', role='Elsewhere', text='mock region 2', sub="Rival's building appears here", fill='#FFF3E5', key=True, below=3),
    dict(id='s_choices', role='What stays', text="Player's choices stay", sub='Lights, door and screen', fill='#EAF6F2', below=5),
    dict(id='s_results', role='You', text='See your results', sub='Then start again', fill='#EDF4FB', below=6),
]
SIMPLE_ARROWS = [
    *[dict(source=a['id'], target=b['id'], kind='solid') for a,b in zip(SIMPLE_BOXES[:6],SIMPLE_BOXES[1:7])],
    dict(source='s_appear', target='s_region', kind='dashed'),
    dict(source='s_update', target='s_choices', kind='dashed'),
    dict(source='s_end', target='s_results', kind='dashed'),
]


def column_center(col):
    return GRID_LEFT + (col-.5)*COLUMN_WIDTH


def font_paths(font_dir):
    if font_dir:
        roots = [Path(font_dir)]
    else:
        roots = [Path('C:/Windows/Fonts'), Path('/Library/Fonts'),
                 Path('/System/Library/Fonts/Supplemental'),
                 Path('/usr/share/fonts/truetype/msttcorefonts')]
    for root in roots:
        for normal,bold in [('arial.ttf','arialbd.ttf'),('Arial.ttf','Arial Bold.ttf')]:
            if (root/normal).exists() and (root/bold).exists():
                return root/normal, root/bold
    raise RuntimeError('Arial font files not found. Pass --font-dir containing arial.ttf and arialbd.ttf.')


def wrap(text, width, font):
    words=text.split()
    lines=[]
    current=''
    for word in words:
        trial=(current+' '+word).strip()
        if font.getlength(trial)>width and current:
            lines.append(current)
            current=word
        else:
            current=trial
    if current:
        lines.append(current)
    return lines


def layout(normal_path, bold_path):
    main_font = ImageFont.truetype(str(normal_path), 18)
    sub_font = ImageFont.truetype(str(normal_path), 13)
    result={}
    for raw in BOXES:
        b=dict(raw)
        end=b.get('end_col',b['col'])
        b['x']=column_center(b['col'])-BOX_WIDTH/2
        b['w']=BOX_WIDTH+(end-b['col'])*COLUMN_WIDTH
        b.setdefault('y',238 if b['lane']=='brand' else 430)
        b.setdefault('h',92)
        b['cx']=b['x']+b['w']/2
        b['cy']=b['y']+b['h']/2
        b['lines']=wrap(b['text'],b['w']-20,main_font)
        b['sub_lines']=wrap(b.get('sub',''),b['w']-18,sub_font)
        height=len(b['lines'])*23+(8+len(b['sub_lines'])*17 if b['sub_lines'] else 0)
        b['text_top']=b['cy']-height/2
        b['text_height']=height
        result[b['id']]=b
    return result


def routes(boxes):
    result=[]
    for raw in ARROWS:
        e=dict(raw)
        a,b=boxes[e['source']],boxes[e['target']]
        route=e['route']
        if route in ('horizontal','horizontal_jog'):
            start=(a['x']+a['w'],a['cy']); end=(b['x'],b['cy'])
            if route=='horizontal':
                assert a['cy']==b['cy']
                points=[start,end]
            else:
                mid=(start[0]+end[0])/2
                points=[start,(mid,start[1]),(mid,end[1]),end]
        elif route=='vertical':
            x=column_center(e['column'])
            down=b['cy']>a['cy']
            points=[(x,a['y']+a['h'] if down else a['y']),
                    (x,b['y'] if down else b['y']+b['h'])]
        elif route=='auction_win':
            x=a['cx']+45
            points=[(x,a['y']),(x,398),(b['cx'],398),(b['cx'],b['y']+b['h'])]
        elif route=='region':
            x=a['x']+a['w']-19
            gutter=GRID_LEFT+6*COLUMN_WIDTH
            points=[(x,a['y']+a['h']),(x,552),(gutter,552),
                    (gutter,862),(column_center(7),862),(column_center(7),b['y'])]
        else:
            raise ValueError(route)
        e['points']=points
        result.append(e)
    return result


def intersects_interior(p,q,b,pad=0):
    left,right=b['x']-pad,b['x']+b['w']+pad
    top,bottom=b['y']-pad,b['y']+b['h']+pad
    if abs(p[0]-q[0])<.001:
        return left<p[0]<right and max(min(p[1],q[1]),top)<min(max(p[1],q[1]),bottom)-.001
    assert abs(p[1]-q[1])<.001, (p,q)
    return top<p[1]<bottom and max(min(p[0],q[0]),left)<min(max(p[0],q[0]),right)-.001


def check(boxes,edges,normal_path):
    assert len(boxes)<=24
    assert sum(bool(b.get('key')) for b in boxes.values())==3
    assert len(TITLE.split())<=6
    expected_keys={'Content appears',"Rival's content here",'Swaps after player exits'}
    assert {b['text'] for b in boxes.values() if b.get('key')}==expected_keys
    fonts={18:ImageFont.truetype(str(normal_path),18),13:ImageFont.truetype(str(normal_path),13)}
    for b in boxes.values():
        assert len(b['text'].split())<=4, b['text']
        assert len(b.get('sub','').split())<=4, b.get('sub')
        assert not re.search(r'\d',b['text']+b.get('sub',''))
        assert b['text_top']>=b['y']+10, b['id']
        assert b['text_top']+b['text_height']<=b['y']+b['h']-10,b['id']
        assert all(fonts[18].getlength(line)<=b['w']-20 for line in b['lines'])
        assert all(fonts[13].getlength(line)<=b['w']-18 for line in b['sub_lines'])
        assert abs(b['x']-(column_center(b['col'])-BOX_WIDTH/2))<.001
        lane=next(l for l in LANES if l['id']==b['lane'])
        assert lane['y']<=b['y'] and b['y']+b['h']<=lane['y']+lane['h']
        for other in boxes.values():
            if b['id']>=other['id']: continue
            assert not (max(b['x'],other['x'])<min(b['x']+b['w'],other['x']+other['w']) and
                        max(b['y'],other['y'])<min(b['y']+b['h'],other['y']+other['h'])), (b['id'],other['id'])
    for e in edges:
        for p,q in zip(e['points'],e['points'][1:]):
            for b in boxes.values():
                assert not intersects_interior(p,q,b), (e['source'],e['target'],'crosses',b['id'])
                if b['id'] not in (e['source'],e['target']):
                    assert not intersects_interior(p,q,b,3), (e['source'],e['target'],'too near',b['id'])


def svg_text(parts,text,x,y,size=18,color=INK,anchor='start',weight=400):
    parts.append(f'<text x="{x:.2f}" y="{y:.2f}" font-family="Arial, sans-serif" font-size="{size}" '
                 f'font-weight="{weight}" fill="{color}" text-anchor="{anchor}">{html.escape(text)}</text>')


def svg_document(boxes,edges):
    p=[f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}" viewBox="0 0 {WIDTH} {HEIGHT}" role="img" aria-labelledby="title desc">',
       f'<title id="title">{html.escape(TITLE)}</title>',
       '<desc id="desc">Four lanes follow a winning bid in mock region through allocation, live content, reporting, a safe update, and the next winner. Mock region 2 resolves separately.</desc>',
       '<defs><marker id="arrow" markerWidth="9" markerHeight="9" refX="8" refY="4.5" orient="auto" markerUnits="userSpaceOnUse"><path d="M 0 0 L 8 4.5 L 0 9 Z" fill="'+LINE+'"/></marker></defs>',
       '<rect width="1920" height="1080" fill="#FFFFFF"/>']
    svg_text(p,TITLE,32,69,40,weight=600)
    svg_text(p,LEGEND,32,119,19,color=LINE)
    for l in LANES:
        p.append(f'<rect x="24" y="{l["y"]}" width="1872" height="{l["h"]}" fill="{l["tint"]}"/>')
        p.append(f'<path d="M 228 {l["y"]} V {l["y"]+l["h"]}" stroke="#C8D2DB" stroke-width="1"/>')
        label_y=l['y']+l['h']/2-12
        svg_text(p,l['label'],44,label_y,20,weight=600)
        for i,line in enumerate(l['sub']):
            svg_text(p,line,44,label_y+27+i*19,14,color=LINE)
    # The common grid is subtle but visible across every lane. No step numerals.
    for col in range(1,10):
        x=GRID_LEFT+col*COLUMN_WIDTH
        p.append(f'<path d="M {x:.2f} 192 V 990" stroke="{GRID}" stroke-width="0.7" stroke-dasharray="2 7"/>')
    for e in edges:
        pts=' '.join(f'{x:.2f},{y:.2f}' for x,y in e['points'])
        dash=' stroke-dasharray="7 5"' if e['kind']=='dashed' else ''
        p.append(f'<polyline points="{pts}" fill="none" stroke="{LINE}" stroke-width="1.8"{dash} marker-end="url(#arrow)" stroke-linejoin="round"/>')
    for b in boxes.values():
        stroke=INK if b.get('key') else '#8796A4'
        width=3.5 if b.get('key') else 1.2
        p.append(f'<g id="{b["id"]}"><rect x="{b["x"]:.2f}" y="{b["y"]}" width="{b["w"]:.2f}" height="{b["h"]}" rx="10" fill="#FFFFFF" stroke="{stroke}" stroke-width="{width}"/>')
        y=b['text_top']+18
        for line in b['lines']:
            svg_text(p,line,b['cx'],y,18,anchor='middle'); y+=23
        if b['sub_lines']:
            y+=3
            for line in b['sub_lines']:
                svg_text(p,line,b['cx'],y,13,color=LINE,anchor='middle'); y+=17
        p.append('</g>')
    p.append('<rect x="24" y="1016" width="1872" height="44" fill="#F2F4F6"/>')
    svg_text(p,FOOTER,960,1045,19,anchor='middle')
    p.append('</svg>')
    return '\n'.join(p)


def drawio_document(boxes,edges):
    root=ET.Element('mxfile',host='app.diagrams.net',type='device',version='26.0.0')
    diagram=ET.SubElement(root,'diagram',id='demo-flow',name='Demo flow')
    model=ET.SubElement(diagram,'mxGraphModel',dx='1920',dy='1080',grid='1',gridSize='10',
                        guides='1',tooltips='1',connect='1',arrows='1',fold='1',page='1',
                        pageScale='1',pageWidth='1920',pageHeight='1080',math='0',shadow='0',background='#FFFFFF')
    cells=ET.SubElement(model,'root')
    ET.SubElement(cells,'mxCell',id='0')
    ET.SubElement(cells,'mxCell',id='1',parent='0')

    def vertex(id,value,x,y,w,h,style):
        cell=ET.SubElement(cells,'mxCell',id=id,value=value,style=style,vertex='1',parent='1')
        ET.SubElement(cell,'mxGeometry',x=f'{x:.2f}',y=f'{y:.2f}',width=f'{w:.2f}',height=f'{h:.2f}',**{'as':'geometry'})
        return cell

    textstyle=f'text;html=1;strokeColor=none;fillColor=none;align=left;verticalAlign=middle;fontFamily={FONT};fontColor={INK};spacing=0;'
    vertex('title',TITLE,32,28,1800,52,textstyle+'fontSize=40;fontStyle=1;')
    vertex('legend',LEGEND,32,94,1600,32,textstyle+f'fontSize=19;fontColor={LINE};')
    for l in LANES:
        vertex('lane-'+l['id'],'',24,l['y'],1872,l['h'],f'rounded=0;fillColor={l["tint"]};strokeColor=none;connectable=0;')
        label='<div style="font-size:20px;font-weight:bold">'+l['label']+'</div><div style="margin-top:12px;font-size:14px;line-height:19px;color:'+LINE+'">'+'<br/>'.join(l['sub'])+'</div>'
        vertex('label-'+l['id'],label,44,l['y'],178,l['h'],textstyle+'fontSize=20;')
        vertex('divider-'+l['id'],'',228,l['y'],.7,l['h'],'fillColor=#C8D2DB;strokeColor=none;connectable=0;')
    for col in range(1,10):
        x=GRID_LEFT+col*COLUMN_WIDTH
        cell=ET.SubElement(cells,'mxCell',id='grid-'+str(col),style=f'endArrow=none;startArrow=none;strokeColor={GRID};strokeWidth=0.7;dashed=1;dashPattern=2 7;',edge='1',parent='1')
        geo=ET.SubElement(cell,'mxGeometry',relative='1',**{'as':'geometry'})
        ET.SubElement(geo,'mxPoint',x=str(x),y='192',**{'as':'sourcePoint'})
        ET.SubElement(geo,'mxPoint',x=str(x),y='990',**{'as':'targetPoint'})
    # Explicit anchors and waypoint arrays preserve the reviewed orthogonal paths.
    for i,e in enumerate(edges):
        a,b=boxes[e['source']],boxes[e['target']]
        start,end=e['points'][0],e['points'][-1]
        sx,sy=(start[0]-a['x'])/a['w'],(start[1]-a['y'])/a['h']
        tx,ty=(end[0]-b['x'])/b['w'],(end[1]-b['y'])/b['h']
        style=f'edgeStyle=none;rounded=0;html=1;endArrow=block;endFill=1;endSize=8;strokeColor={LINE};strokeWidth=1.8;exitX={sx};exitY={sy};entryX={tx};entryY={ty};exitPerimeter=0;entryPerimeter=0;'
        if e['kind']=='dashed': style+='dashed=1;dashPattern=7 5;'
        edge=ET.SubElement(cells,'mxCell',id='flow-'+str(i),source=e['source'],target=e['target'],style=style,edge='1',parent='1')
        geo=ET.SubElement(edge,'mxGeometry',relative='1',**{'as':'geometry'})
        if len(e['points'])>2:
            points=ET.SubElement(geo,'Array',**{'as':'points'})
            for x,y in e['points'][1:-1]:
                ET.SubElement(points,'mxPoint',x=f'{x:.2f}',y=f'{y:.2f}')
    for b in boxes.values():
        value='<div style="font-size:18px;line-height:23px">'+'<br/>'.join(html.escape(t) for t in b['lines'])+'</div>'
        if b['sub_lines']:
            value+='<div style="margin-top:8px;font-size:13px;line-height:17px;color:'+LINE+'">'+'<br/>'.join(html.escape(t) for t in b['sub_lines'])+'</div>'
        style=f'rounded=1;absoluteArcSize=1;arcSize=20;whiteSpace=wrap;html=1;fillColor=#FFFFFF;strokeColor={INK if b.get("key") else "#8796A4"};strokeWidth={3.5 if b.get("key") else 1.2};fontColor={INK};fontFamily={FONT};fontSize=18;align=center;verticalAlign=middle;spacing=0;'
        vertex(b['id'],value,b['x'],b['y'],b['w'],b['h'],style)
    vertex('footer',FOOTER,24,1016,1872,44,f'rounded=0;html=1;fillColor=#F2F4F6;strokeColor=none;fontFamily={FONT};fontColor={INK};fontSize=19;align=center;verticalAlign=middle;')
    ET.indent(root,space='  ')
    return ET.tostring(root,encoding='unicode',xml_declaration=True)


def simple_documents(normal,bold):
    boxes={}
    for i,raw in enumerate(SIMPLE_BOXES):
        b=dict(raw)
        small='below' in b
        b.update(x=48+264*(b['below'] if small else i),y=714 if small else 310,w=240,h=184 if small else 254)
        b['cx']=b['x']+120
        b['cy']=b['y']+b['h']/2
        b['texts']=[]
        # Text areas use the same positions in SVG and editable draw.io children.
        specs=[('role',16,False,16,23),('text',22 if small else 26,True,51 if small else 74,56 if small else 74),
               ('sub',18 if small else 20,False,122 if small else 178,50 if small else 54)]
        for field,size,heavy,y,h in specs:
            font=ImageFont.truetype(str(bold if heavy else normal),size)
            lines=wrap(b[field],208,font)
            leading=size+5
            assert len(lines)*leading<=h,(b['id'],field,lines)
            assert all(font.getlength(t)<=208 for t in lines)
            b['texts'].append(dict(lines=lines,size=size,heavy=heavy,y=y,h=h,leading=leading))
        assert len(b['text'].split())<=4 and len(b['sub'].split())<=4
        boxes[b['id']]=b
    edges=[]
    for raw in SIMPLE_ARROWS:
        e=dict(raw)
        a,b=boxes[e['source']],boxes[e['target']]
        e['points']=([(a['x']+a['w'],a['cy']),(b['x'],b['cy'])] if e['kind']=='solid'
                     else [(a['cx'],a['y']+a['h']),(b['cx'],b['y'])])
        for p,q in zip(e['points'],e['points'][1:]):
            assert not any(intersects_interior(p,q,box) for box in boxes.values())
        edges.append(e)
    for i,a in enumerate(boxes.values()):
        for b in list(boxes.values())[i+1:]:
            assert not (max(a['x'],b['x'])<min(a['x']+a['w'],b['x']+b['w']) and
                        max(a['y'],b['y'])<min(a['y']+a['h'],b['y']+b['h']))

    svg=[f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}" viewBox="0 0 {WIDTH} {HEIGHT}" role="img" aria-labelledby="title desc">',
         f'<title id="title">{SIMPLE_TITLE}</title>',
         '<desc id="desc">A winning bid makes your building appear in mock region. A rival appears in mock region 2. Updates wait for the player to leave, and keep their choices.</desc>',
         '<defs><marker id="arrow" markerWidth="10" markerHeight="10" refX="9" refY="5" orient="auto" markerUnits="userSpaceOnUse"><path d="M 0 0 L 9 5 L 0 10 Z" fill="'+LINE+'"/></marker></defs>',
         '<rect width="1920" height="1080" fill="#FFFFFF"/>']
    svg_text(svg,SIMPLE_TITLE,48,92,44,weight=700)
    svg_text(svg,SIMPLE_SUBTITLE,48,142,25,color=LINE)
    for e in edges:
        pts=' '.join(f'{x},{y}' for x,y in e['points'])
        dash=' stroke-dasharray="8 6"' if e['kind']=='dashed' else ''
        svg.append(f'<polyline points="{pts}" fill="none" stroke="{LINE}" stroke-width="2.2"{dash} marker-end="url(#arrow)"/>')
    for b in boxes.values():
        svg.append(f'<g id="{b["id"]}"><rect x="{b["x"]}" y="{b["y"]}" width="{b["w"]}" height="{b["h"]}" rx="12" fill="{b["fill"]}" stroke="{INK if b.get("key") else "#BBC8D1"}" stroke-width="{3 if b.get("key") else 1.2}"/>')
        for t in b['texts']:
            y=b['y']+t['y']+(t['h']-len(t['lines'])*t['leading'])/2+t['size']
            for line in t['lines']:
                svg_text(svg,line,b['cx'],y,t['size'],color=INK if t['heavy'] else LINE,anchor='middle',weight=700 if t['heavy'] else 400)
                y+=t['leading']
        svg.append('</g>')
    svg.append('<rect x="24" y="990" width="1872" height="60" fill="#F2F4F6"/>')
    svg_text(svg,SIMPLE_FOOTER,960,1028,23,anchor='middle')
    svg.append('</svg>')

    root=ET.Element('mxfile',host='app.diagrams.net',type='device')
    diagram=ET.SubElement(root,'diagram',id='simple-demo',name='Simple demo flow')
    model=ET.SubElement(diagram,'mxGraphModel',page='1',pageScale='1',pageWidth='1920',pageHeight='1080',background='#FFFFFF')
    cells=ET.SubElement(model,'root')
    ET.SubElement(cells,'mxCell',id='0')
    ET.SubElement(cells,'mxCell',id='1',parent='0')
    def vertex(id,value,x,y,w,h,style,parent='1'):
        cell=ET.SubElement(cells,'mxCell',id=id,value=value,style=style,vertex='1',parent=parent)
        ET.SubElement(cell,'mxGeometry',x=str(x),y=str(y),width=str(w),height=str(h),**{'as':'geometry'})
    textstyle=f'text;html=1;strokeColor=none;fillColor=none;fontFamily={FONT};fontColor={INK};align=left;verticalAlign=middle;spacing=0;'
    vertex('simple-title',SIMPLE_TITLE,48,43,1824,58,textstyle+'fontSize=44;fontStyle=1;')
    vertex('simple-subtitle',SIMPLE_SUBTITLE,48,116,1824,35,textstyle+f'fontSize=25;fontColor={LINE};')
    for i,e in enumerate(edges):
        horizontal=e['kind']=='solid'
        style=f'edgeStyle=none;rounded=0;endArrow=block;endFill=1;endSize=9;strokeColor={LINE};strokeWidth=2.2;exitPerimeter=0;entryPerimeter=0;'
        style+=('exitX=1;exitY=0.5;entryX=0;entryY=0.5;' if horizontal else 'exitX=0.5;exitY=1;entryX=0.5;entryY=0;dashed=1;dashPattern=8 6;')
        edge=ET.SubElement(cells,'mxCell',id=f'simple-edge-{i}',source=e['source'],target=e['target'],style=style,edge='1',parent='1')
        ET.SubElement(edge,'mxGeometry',relative='1',**{'as':'geometry'})
    for b in boxes.values():
        style=f'rounded=1;absoluteArcSize=1;arcSize=24;fillColor={b["fill"]};strokeColor={INK if b.get("key") else "#BBC8D1"};strokeWidth={3 if b.get("key") else 1.2};'
        vertex(b['id'],'',b['x'],b['y'],b['w'],b['h'],style)
        for i,t in enumerate(b['texts']):
            value=f'<div style="font-size:{t["size"]}px;line-height:{t["leading"]}px">'+'<br/>'.join(html.escape(line) for line in t['lines'])+'</div>'
            vertex(f'{b["id"]}-text-{i}',value,16,t['y'],208,t['h'],textstyle+f'align=center;fontSize={t["size"]};fontStyle={1 if t["heavy"] else 0};fontColor={INK if t["heavy"] else LINE};',b['id'])
    vertex('simple-footer',SIMPLE_FOOTER,24,990,1872,60,textstyle+'align=center;fontSize=23;fillColor=#F2F4F6;')
    ET.indent(root,space='  ')
    return boxes,edges,'\n'.join(svg),ET.tostring(root,encoding='unicode',xml_declaration=True)


def write_outputs(base,svg,drawio,boxes,edges,normal,bold):
    base.with_suffix('.svg').write_text(svg,encoding='utf-8')
    base.with_suffix('.drawio').write_text(drawio,encoding='utf-8')
    base.with_suffix('.png').write_bytes(resvg_py.svg_to_bytes(
        svg_path=str(base.with_suffix('.svg')),width=WIDTH,height=HEIGHT,
        font_files=[str(normal),str(bold)],font_family=FONT,skip_system_fonts=True))
    with Image.open(base.with_suffix('.png')) as png:
        assert png.size==(WIDTH,HEIGHT)
    mx=ET.parse(base.with_suffix('.drawio'))
    assert all(mx.find(f'.//mxCell[@id="{id}"]') is not None for id in boxes)
    assert len(mx.findall('.//mxCell[@source]'))==len(edges)
    assert not re.search(r'Japan|India',svg+drawio,re.I)
    print(json.dumps({'diagram':base.name,'size':[WIDTH,HEIGHT],'flow_boxes':len(boxes),
                      'connectors':len(edges),'automated_checks':'PASS',
                      'files':[str(base.with_suffix(ext)) for ext in ('.drawio','.svg','.png')]},indent=2))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir',type=Path,default=Path(__file__).resolve().parent)
    parser.add_argument('--font-dir',type=Path)
    args=parser.parse_args()
    normal,bold=font_paths(args.font_dir)
    boxes=layout(normal,bold)
    edges=routes(boxes)
    check(boxes,edges,normal)
    args.output_dir.mkdir(parents=True,exist_ok=True)
    write_outputs(args.output_dir/'DemoFlow',svg_document(boxes,edges),drawio_document(boxes,edges),boxes,edges,normal,bold)
    simple_boxes,simple_edges,svg,drawio=simple_documents(normal,bold)
    write_outputs(args.output_dir/'DemoFlowSimple',svg,drawio,simple_boxes,simple_edges,normal,bold)


if __name__=='__main__':
    main()
