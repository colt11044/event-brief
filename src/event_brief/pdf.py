"""Offline, bounded local portrait loading and PDF rendering."""
import hashlib
import io
import os
import stat
import warnings as warning_control
from html import escape
from pathlib import Path
from .core import coverage_report, substantive, text, claim_source_ids, badge_label, signal_display, visual_confidence_display, render_html

MAX_PORTRAIT_BYTES = 10 * 1024 * 1024
MAX_PORTRAIT_PIXELS = 16_000_000


def load_local_portrait(portrait, portrait_dir):
    """Read only a named, hash-pinned raster in an explicitly selected directory."""
    if portrait_dir is None or not portrait.get('local_asset'):
        raise ValueError('No explicitly supplied local portrait asset')
    name = portrait['local_asset']
    if not isinstance(name, str) or name in {'', '.', '..'} or '/' in name or '\\' in name or ':' in name or any(ord(ch) < 32 for ch in name) or Path(name).is_absolute():
        raise ValueError('Portrait asset must be a single filename')
    # An explicit directory plus an O_NOFOLLOW leaf prevents payload-driven path traversal.
    directory = os.open(str(portrait_dir), os.O_RDONLY | os.O_DIRECTORY)
    try:
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        with os.fdopen(fd, 'rb') as source:
            if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
                raise ValueError('Portrait asset must be a regular file')
            raw = source.read(MAX_PORTRAIT_BYTES + 1)
    finally:
        os.close(directory)
    if len(raw) > MAX_PORTRAIT_BYTES:
        raise ValueError('Portrait asset exceeds 10 MiB')
    if hashlib.sha256(raw).hexdigest() != portrait.get('local_asset_sha256'):
        raise ValueError('Portrait asset checksum mismatch')
    from PIL import Image as RasterImage
    with warning_control.catch_warnings():
        warning_control.simplefilter('error', RasterImage.DecompressionBombWarning)
        with RasterImage.open(io.BytesIO(raw)) as image:
            if image.format not in {'PNG', 'JPEG', 'WEBP'}:
                raise ValueError('Portrait must be PNG, JPEG or WebP')
            if image.width * image.height > MAX_PORTRAIT_PIXELS:
                raise ValueError('Portrait exceeds pixel limit')
            image.load()
            normalized = io.BytesIO()
            pixels = image.convert('RGBA' if 'A' in image.getbands() else 'RGB')
            # Pillow carries ICC/EXIF metadata through convert(). Export pixels only.
            pixels.info.clear()
            pixels.save(normalized, format='PNG')
    if normalized.tell() > MAX_PORTRAIT_BYTES:
        raise ValueError('Normalized portrait exceeds 10 MiB')
    return normalized.getvalue()


def portrait_assets(data, portrait_dir):
    assets = {}
    notes = []
    for index, person in enumerate(data['people']):
        portrait = person.get('portrait') or {}
        if portrait.get('state') != 'verified_public':
            continue
        try:
            assets[index] = load_local_portrait(portrait, portrait_dir)
        except Exception as exc:
            notes.append('Portrait ' + str(index + 1) + ' unavailable in print: ' + str(exc))
    return assets, notes


def offline_html(data, assets):
    """Ignore original HTML markup and expose only preloaded in-memory images."""
    resources = {'hermes-portrait:' + str(index): raw for index, raw in assets.items()}
    def fetch_resource(url, *args, **kwargs):
        if url not in resources:
            raise ValueError('External resource loading is disabled')
        return {'string': resources[url], 'mime_type': 'image/png'}
    return render_html(data, portrait_sources={index: 'hermes-portrait:' + str(index) for index in assets}), fetch_resource


def reportlab_pdf(data, output, assets=None):
    assets = assets or {}

    from reportlab.lib import colors
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    font_dir = Path(__file__).resolve().parent / "assets" / "fonts"
    pdfmetrics.registerFont(TTFont("BriefSans", str(font_dir / "DejaVuSans.ttf")))
    pdfmetrics.registerFont(TTFont("BriefSans-Bold", str(font_dir / "DejaVuSans-Bold.ttf")))
    pdfmetrics.registerFontFamily("BriefSans", normal="BriefSans", bold="BriefSans-Bold", italic="BriefSans", boldItalic="BriefSans-Bold")
    from reportlab.lib.enums import TA_CENTER
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image, KeepTogether, HRFlowable
    ink = colors.HexColor('#18212b')
    muted = colors.HexColor('#536171')
    accent = colors.HexColor('#0d5c63')
    styles = {
        'title': ParagraphStyle('title', fontName='BriefSans-Bold', fontSize=23, leading=27, textColor=ink, spaceAfter=9),
        'h2': ParagraphStyle('h2', fontName='BriefSans-Bold', fontSize=15, leading=19, textColor=accent, spaceBefore=14, spaceAfter=8, keepWithNext=True),
        'name': ParagraphStyle('name', fontName='BriefSans-Bold', fontSize=17, leading=21, textColor=ink, spaceAfter=4),
        'body': ParagraphStyle('body', fontName='BriefSans', fontSize=11, leading=15, textColor=ink, spaceAfter=6),
        'small': ParagraphStyle('small', fontName='BriefSans', fontSize=10, leading=13, textColor=muted, spaceAfter=5),
        'source': ParagraphStyle('source', fontName='BriefSans', fontSize=10, leading=13, textColor=muted, spaceAfter=4, wordWrap='CJK'),
        'stat': ParagraphStyle('stat', fontName='BriefSans', fontSize=10.5, leading=14, textColor=accent, alignment=TA_CENTER),
        'cell': ParagraphStyle('cell', fontName='BriefSans', fontSize=10, leading=13, textColor=ink),
    }
    def p(value, style='body'):
        return Paragraph(value, styles[style])
    def esc(value):
        return escape(text(value), quote=True)
    def claim(label, value):
        if not substantive(value): return None
        detail = value.get('detail') or ', '.join(filter(None,[text(value.get('title') or value.get('role') or value.get('school')),text(value.get('organization') or value.get('degree'))]))
        cites = ' '.join('[' + esc(v) + ']' for v in claim_source_ids(value))
        return p('<b>' + label + ':</b> ' + esc(detail) + (' <font color="#536171">' + cites + '</font>' if cites else ''))
    event = data['event']; report = coverage_report(data)
    story = [p(esc(event['title']), 'title'),p(esc(event['date']) + ' | ' + esc(event['location']) + ' | Hosted by ' + esc(event['host']), 'small')]
    if event.get('purpose'): story.append(p(esc(event['purpose'])))
    if data.get('fixture_notice'): story.append(p(esc(data['fixture_notice']), 'small'))
    intake = data['video_intake']; note = 'Video intake: ' + text(intake.get('validation_state')).replace('_',' ')
    if intake.get('limitation'): note += '. ' + text(intake['limitation'])
    story.append(p(esc(note), 'small'))
    if data.get('priority_section'):
        story.append(p('Who to meet first', 'h2'))
        for item in data['priority_section']:
            story.append(p('<b>' + esc(item.get('name')) + ':</b> ' + esc(item.get('reason'))))
    story.append(p('Coverage', 'h2'))
    cells = [p('<b>' + str(report[k]) + '</b><br/>' + label,'stat') for k,label in [('full_name_roster','full-name roster'),('research_records','research records'),('confirmed_or_probable','confirmed or probable'),('verified_portraits','verified portraits')]]
    stats=Table([cells], colWidths=[133]*4)
    stats.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,-1),colors.HexColor('#e9f5f4')),('BOX',(0,0),(-1,-1),0.4,colors.HexColor('#d7dde5')),('TOPPADDING',(0,0),(-1,-1),10),('BOTTOMPADDING',(0,0),(-1,-1),10)]))
    story.append(stats)
    resolution=event.get('resolution_note') or data.get('resolution_note')
    if resolution: story.extend([Spacer(1,7),p(esc(resolution),'small')])
    for person_index, person in enumerate(data['people']):
        portrait = person.get('portrait') or {}; portrait_state = portrait.get('state')
        portrait_obj = p('No verified<br/>public portrait', 'small')
        if portrait_state == 'withheld_ambiguous': portrait_obj=p('Portrait withheld:<br/>identity unresolved','small')
        if portrait_state == 'verified_public':
            try:
                raw = assets[person_index]
                image=Image(io.BytesIO(raw)); scale=min(76/image.imageWidth,76/image.imageHeight)
                image.drawWidth=image.imageWidth*scale; image.drawHeight=image.imageHeight*scale; portrait_obj=image
            except Exception:
                portrait_obj=p('Verified portrait<br/>unavailable in print','small')
        badges = [badge_label(text(b.get('type'))) for b in person.get('badges',[])]
        badges += [text(f.get('label') or f.get('config_id')).replace('_',' ') + ' (' + text(f.get('relationship_type')).replace('_',' ') + (', '+text(f.get('timeframe') or f.get('current_status')) if f.get('timeframe') or f.get('current_status') else '') + ')' for f in person.get('shared_affiliation_flags',[])]
        headline=[p(esc(person['name']),'name'),p(esc(text(person.get('identity_status')).replace('_',' ')) + ' identity | transcription confidence ' + visual_confidence_display(person),'small')]
        if badges: headline.append(p('<b>' + esc(' | '.join(badges)) + '</b>','small'))
        header=Table([[portrait_obj,headline]],colWidths=[92,440]);header.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'TOP'),('LEFTPADDING',(0,0),(-1,-1),0),('RIGHTPADDING',(0,0),(0,0),14),('BOTTOMPADDING',(0,0),(-1,-1),10)]))
        block=([p('People', 'h2')] if person_index == 0 else []) + [HRFlowable(width='100%',thickness=1,color=colors.HexColor('#c7d7db')),Spacer(1,10),header]
        claims=person.get('claims') or {}
        current=claim('Current role',claims.get('current_role') or {})
        block.append(current or p('Current role not responsibly established.','small'))
        edu=claim('Education',claims.get('education') or {})
        if edu:block.append(edu)
        for item in claims.get('historical_roles') or []:
            if substantive(item):block.append(claim('Historical career',item))
        for item in claims.get('notable_background') or []:
            if substantive(item):block.append(claim('Professional background',item))
        rationale=person.get('identity_rationale') or person.get('ambiguity_note')
        if rationale:block.append(p('<b>Identity note:</b> ' + esc(rationale),'small'))
        if claims.get('recent_signals') or person.get('conversation_hooks'):
            block.append(p('Recent signals &amp; conversation hooks', 'h2'))
        for signal in claims.get('recent_signals') or []:
            block.append(claim('Signal', signal_display(signal)))
        if person.get('research_method_note'):
            block.append(p('<b>Research method:</b> ' + esc(person['research_method_note']), 'small'))
        for hook in person.get('conversation_hooks') or []:block.append(p('<b>Ask:</b> ' + esc(hook)))
        if person.get('evidence'):
            block.append(p('<b>Sources</b>','small'))
            for source in person['evidence']:
                block.append(p('<link href="' + esc(source['url']) + '" color="#075e9f">[' + esc(source['id']) + '] ' + esc(source['title']) + '</link> | retrieved ' + esc(source['retrieved_at']),'source'))
        else:block.append(p('No person-level facts claimed.','small'))
        block.append(Spacer(1,13));story.append(KeepTogether(block))
    story.append(p('Full roster research ledger','h2'))
    rows=[[p('<b>'+v+'</b>','cell') for v in ['Person','Read conf.','Identity','Attempts','Portrait']]]
    for person in data['people']:
        rows.append([p(esc(person['name']),'cell'),p(visual_confidence_display(person),'cell'),p(esc(text(person.get('identity_status')).replace('_',' ')),'cell'),p(str(len(person.get('research_attempts',[]))),'cell'),p(esc(text((person.get('portrait') or {}).get('state')).replace('_',' ')),'cell')])
    table=Table(rows,colWidths=[132,85,98,65,152],repeatRows=1,hAlign='LEFT')
    table.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'TOP'),('BACKGROUND',(0,0),(-1,0),colors.HexColor('#e9f5f4')),('LINEBELOW',(0,0),(-1,-1),0.3,colors.HexColor('#d7dde5')),('TOPPADDING',(0,0),(-1,-1),7),('BOTTOMPADDING',(0,0),(-1,-1),7)]))
    story.append(table)
    def footer(canvas, doc):
        canvas.saveState();canvas.setFont('BriefSans',9);canvas.setFillColor(muted)
        canvas.drawString(40,25,'Event brief | Sources and confidence preserved');canvas.drawRightString(572,25,str(doc.page));canvas.restoreState()
    doc=SimpleDocTemplate(str(output),pagesize=letter,leftMargin=40,rightMargin=40,topMargin=36,bottomMargin=43,title=text(event['title']),author='Event Brief')
    doc.build(story,onFirstPage=footer,onLaterPages=footer)
