import os
import io
import base64
import re
from PIL import Image as PILImage, ImageDraw
from fastapi import FastAPI, Request, UploadFile, File
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from groq import Groq
from dotenv import load_dotenv
from pypdf import PdfReader
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, ListFlowable, ListItem, Image as RLImage, Table, TableStyle, KeepTogether, HRFlowable
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

load_dotenv()

app = FastAPI()

client = Groq(api_key=os.environ.get("GROQ_API_KEY"))

SYSTEM_PROMPT = """You are a professional CV writer and resume assistant. Your job is to interview the candidate for missing facts, gather their full background, then rewrite it into concise, polished resume content suitable for hiring managers and applicant tracking systems.

Collect information in this order when possible: full name, email, phone, LinkedIn (optional), GitHub (optional), location, PROFESSIONAL SUMMARY, TECHNICAL SKILLS, PROFESSIONAL EXPERIENCE, CERTIFICATIONS & TRAINING, KEY PROJECTS & ACHIEVEMENTS, EDUCATION, and any additional sections the user wants to include.

Contact rules:
- Always output contact info in the order: email, phone, LinkedIn, GitHub, location (location should appear last).
- If the user has not provided LinkedIn or GitHub, do not force it; continue with the remaining sections.
- Normalize GitHub to a username-based URL and LinkedIn to a personal profile URL when possible.

Writing rules:
- Act as an experienced, professional CV writer. When producing the `PROFESSIONAL SUMMARY`, write 4-6 concise lines (or 3-5 short sentences) tailored to the candidate's experience, emphasizing impact, scope, and results; prefer measurable outcomes when the user supplies metrics.
- For `TECHNICAL SKILLS`, prefer a short list of core skills/technologies (comma-separated) that match the candidate's experience.
- For each role in `PROFESSIONAL EXPERIENCE`, produce bullets that start with strong action verbs, are result-oriented, and list 1-3 clear achievements or responsibilities. Do not invent metrics — if none provided, keep statements factual and impact-oriented.
- For `CERTIFICATIONS & TRAINING` and `KEY PROJECTS & ACHIEVEMENTS`, collect lists (plain items) and label them exactly as shown above.

Completeness rules:
- If any required field is missing, ask a focused follow-up question requesting only the missing information.
- For each job, request at least 1-2 achievements; if the user supplies multiple roles at once, iterate through them and request missing achievements individually.

Formatting and output rules:
- Never repeat prior assistant messages or full conversation history as content — only reference facts extracted from the user.
- Keep conversational text out of the JSON block; supply a human-friendly reply first, then append exactly one JSON block.
- When adding additional sections, normalize titles: map variations to `CERTIFICATIONS & TRAINING` or `KEY PROJECTS & ACHIEVEMENTS` when appropriate; otherwise output the section title uppercased.

After every response, append exactly one JSON block at the end with the candidate data (use this exact marker format):
###RESUME_DATA###
{"name":"","email":"","phone":"","location":"","linkedin":"","github":"","summary":"","skills":[],"experience":[],"certifications":[],"projects":[],"education":[],"additional_sections":[]}
###END###

Data specifics:
- `experience` items must be objects: {"title":"","company":"","dates":"","achievements":["",""]}.
- `education` must be a list of plain strings.
- `skills`, `certifications`, and `projects` should be lists of plain strings.
- `additional_sections` is optional and should be a list of objects with `section` (title) and `items` (list of strings).
- LinkedIn and GitHub values in the JSON may be usernames or full URLs; prefer normalized full URLs if you can derive them.

Behavior rules:
- Merge any newly provided information into previously collected fields; do not drop existing data unless the user explicitly asks to remove or replace it.
- Keep the human-readable part of your reply concise and focused on the next action or clarification needed.

"""

def is_valid_style_reference(text):
    if not text or not isinstance(text, str):
        return False
    invalid_patterns = [r"%PDF", r"endstream", r"endobj", r"\bstream\b", r"FlateDecode", r"xref", r"<<", r">>"]
    lowered = text.lower()
    if any(re.search(pattern, text, re.IGNORECASE) for pattern in invalid_patterns):
        return False
    control_chars = sum(1 for ch in text if ord(ch) < 32 and ch not in ['\n', '\r', '\t'])
    if control_chars > max(1, len(text) // 30):
        return False
    return True


def sanitize_style_reference(text):
    if not is_valid_style_reference(text):
        return None
    cleaned = ''.join(ch for ch in text if ord(ch) >= 32 or ch in ['\n', '\r', '\t'])
    return ' '.join(cleaned.split())[:2000].strip()


@app.post("/api/extract-pdf-style")
async def extract_pdf_style(file: UploadFile = File(...)):
    if not file.filename.lower().endswith('.pdf'):
        return JSONResponse({"error": "Uploaded file is not a PDF."}, status_code=400)

    body = await file.read()
    try:
        reader = PdfReader(io.BytesIO(body))
        text_parts = []
        for page in reader.pages:
            page_text = page.extract_text() or ''
            text_parts.append(page_text)

        text = ' '.join(text_parts)
        text = re.sub(r'[\x00-\x1F\x7F-\x9F]+', ' ', text).strip()
        if not text:
            raise ValueError('No text extracted')
        return JSONResponse({"text": text})
    except Exception as e:
        print(f"PDF extraction failed: {e}")
        return JSONResponse({"error": "Could not extract text from the PDF."}, status_code=400)


@app.post("/api/chat")
async def chat(request: Request):
    body = await request.json()
    messages = body.get("messages", [])
    style_reference = sanitize_style_reference(body.get("style_reference"))
    if style_reference:
        messages.insert(1, {"role": "system", "content": f"Style reference:\n{style_reference}"})

    groq_messages = [{"role": "system", "content": SYSTEM_PROMPT}] + messages

    try:
        completion = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=groq_messages,
            max_tokens=1200,
            temperature=0.7,
        )
        reply = completion.choices[0].message.content
        return JSONResponse({"reply": reply})
    except Exception as e:
        print(f"Groq call failed: {e}")
        return JSONResponse({"error": "Something went wrong"}, status_code=500)


# ---------- SHARED HELPERS (used by every template) ----------

def get_photo_flowable(data, size=0.85):
    """Returns a reportlab Image flowable if a photo was uploaded, else None."""
    if not data.get('photo'):
        return None
    try:
        header, encoded = data['photo'].split(',', 1)
        img_bytes = base64.b64decode(encoded)
        img = PILImage.open(io.BytesIO(img_bytes)).convert('RGBA')
        min_dim = min(img.size)
        desired_dim = int(size * inch * 2)
        needs_circle = min_dim >= desired_dim

        if needs_circle:
            img = img.crop(((img.width - min_dim) // 2, (img.height - min_dim) // 2,
                            (img.width + min_dim) // 2, (img.height + min_dim) // 2))
            img = img.resize((desired_dim, desired_dim), PILImage.Resampling.LANCZOS)

            mask = PILImage.new('L', (desired_dim, desired_dim), 0)
            draw = ImageDraw.Draw(mask)
            draw.ellipse((0, 0, desired_dim, desired_dim), fill=255)

            circular = PILImage.new('RGBA', (desired_dim, desired_dim), (255, 255, 255, 0))
            circular.paste(img, (0, 0), mask)

            img_buffer = io.BytesIO()
            circular.save(img_buffer, format='PNG')
            img_buffer.seek(0)
            return RLImage(img_buffer, width=size * inch, height=size * inch)

        img = img.crop(((img.width - min_dim) // 2, (img.height - min_dim) // 2,
                        (img.width + min_dim) // 2, (img.height + min_dim) // 2))
        img = img.resize((desired_dim, desired_dim), PILImage.Resampling.LANCZOS)

        img_buffer = io.BytesIO()
        img.save(img_buffer, format='PNG')
        img_buffer.seek(0)
        return RLImage(img_buffer, width=size * inch, height=size * inch)
    except Exception as e:
        print(f"Photo embed failed, skipping: {e}")
        return None

def build_contact_line(data, link_color="#2563EB"):
    parts = []
    if data.get('email'):
        parts.append(f'<link href="mailto:{data["email"]}" color="{link_color}">{data["email"]}</link>')
    if data.get('phone'):
        phone_clean = re.sub(r'\s+', '', data['phone'])
        parts.append(f'<link href="tel:{phone_clean}" color="{link_color}">{data["phone"]}</link>')
    if data.get('linkedin'):
        li_value = normalize_linkedin(data['linkedin'])
        parts.append(f'<link href="{li_value}" color="{link_color}">LinkedIn</link>')
    if data.get('github'):
        gh_value = normalize_github(data['github'])
        parts.append(f'<link href="{gh_value}" color="{link_color}">GitHub</link>')
    if data.get('location'):
        parts.append(data['location'])
    return ' | '.join(parts)


def normalize_linkedin(value):
    cleaned = value.strip()
    cleaned = re.sub(r'^(https?://)?(www\.)?', '', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'^linkedin[:\s\/\\]+', '', cleaned, flags=re.IGNORECASE)
    if cleaned.lower().startswith('linkedin.com'):
        return f'https://{cleaned}'
    return f'https://linkedin.com/in/{cleaned}'


def normalize_github(value):
    cleaned = value.strip()
    cleaned = re.sub(r'^(https?://)?(www\.)?', '', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'^github[:\s\/\\]+', '', cleaned, flags=re.IGNORECASE)
    if cleaned.lower().startswith('github.com'):
        return f'https://{cleaned}'
    return f'https://github.com/{cleaned}'

def clean_education(edu):
    """Handles either plain strings or unexpected dict objects from the model."""
    if isinstance(edu, dict):
        return ', '.join(str(v) for v in edu.values() if v)
    return str(edu)


def section_heading_text(title):
    if not title:
        return None
    normalized = title.strip().lower()
    if 'certif' in normalized or 'training' in normalized:
        return 'CERTIFICATIONS & TRAINING'
    if 'project' in normalized or 'achievement' in normalized:
        return 'KEY PROJECTS & ACHIEVEMENTS'
    return title.strip().upper()


def normalize_item_list(items):
    if isinstance(items, str):
        return [items.strip()] if items.strip() else []
    if isinstance(items, dict):
        text = ', '.join(str(v).strip() for v in items.values() if v)
        return [text] if text else []
    if isinstance(items, list):
        normalized = []
        for item in items:
            if isinstance(item, dict):
                text = ', '.join(str(v).strip() for v in item.values() if v)
                if text:
                    normalized.append(text)
            else:
                text = str(item).strip()
                if text:
                    normalized.append(text)
        return normalized
    return []


def append_heading(elements, title, heading_style):
    elements.append(Paragraph(title, heading_style))
    elements.append(HRFlowable(width='100%', thickness=2, lineCap='square', color=heading_style.textColor, spaceBefore=2, spaceAfter=10, hAlign='LEFT'))


def render_section(elements, section, heading_style, body_style):
    heading = section_heading_text(section.get('section') or section.get('title') or '')
    if not heading:
        return
    items = section.get('items') or section.get('content') or []
    items = normalize_item_list(items)
    if not items:
        return
    append_heading(elements, heading, heading_style)
    list_items = [ListItem(Paragraph(item, body_style)) for item in items]
    elements.append(ListFlowable(list_items, bulletType='bullet', leftIndent=14))


def _collect_additional_section_items(data, headings):
    items = []
    for section in data.get('additional_sections', []):
        heading = section_heading_text(section.get('section') or section.get('title') or '')
        if heading in headings:
            items.extend(normalize_item_list(section.get('items') or section.get('content') or []))
    return items


def render_certifications_projects(elements, data, heading_style, body_style):
    cert_items = normalize_item_list(data.get('certifications'))
    cert_items.extend(_collect_additional_section_items(data, {'CERTIFICATIONS & TRAINING'}))
    cert_items = [item for item in cert_items if item]
    if cert_items:
        append_heading(elements, 'CERTIFICATIONS & TRAINING', heading_style)
        list_items = [ListItem(Paragraph(item, body_style)) for item in cert_items]
        elements.append(ListFlowable(list_items, bulletType='bullet', leftIndent=14))

    proj_items = normalize_item_list(data.get('projects'))
    proj_items.extend(_collect_additional_section_items(data, {'KEY PROJECTS & ACHIEVEMENTS'}))
    proj_items = [item for item in proj_items if item]
    if proj_items:
        append_heading(elements, 'KEY PROJECTS & ACHIEVEMENTS', heading_style)
        list_items = [ListItem(Paragraph(item, body_style)) for item in proj_items]
        elements.append(ListFlowable(list_items, bulletType='bullet', leftIndent=14))


def sort_additional_sections(sections):
    if not sections:
        return []
    priority = {
        'CERTIFICATIONS & TRAINING': 0,
        'KEY PROJECTS & ACHIEVEMENTS': 1,
    }
    def section_key(section):
        heading = section_heading_text(section.get('section') or section.get('title') or '')
        return (priority.get(heading, 10), heading)
    return sorted(sections, key=section_key)


def infer_template_from_style_reference(style_reference, default='classic'):
    if not style_reference:
        return default
    normalized = style_reference.lower()
    if 'sidebar' in normalized:
        return 'sidebar'
    if any(term in normalized for term in ['minimal', 'clean', 'modern']):
        return 'minimal'
    if any(term in normalized for term in ['bold', 'dark', 'contrast']):
        return 'bold'
    if any(term in normalized for term in ['compact', 'condensed', 'tight']):
        return 'compact'
    return default


# ---------- TEMPLATE: CLASSIC (single column, traditional) ----------

def build_classic(data, buffer):
    doc = SimpleDocTemplate(buffer, pagesize=letter, topMargin=0.6*inch, bottomMargin=0.6*inch)
    styles = getSampleStyleSheet()

    name_style = ParagraphStyle('Name', parent=styles['Title'], fontName='Helvetica-Bold', fontSize=22, spaceAfter=4, alignment=TA_LEFT)
    name_center_style = ParagraphStyle('NameCenter', parent=name_style, alignment=TA_CENTER)
    contact_style = ParagraphStyle('Contact', parent=styles['Normal'], fontName='Helvetica', textColor=colors.grey, spaceAfter=4, alignment=TA_LEFT)
    contact_center_style = ParagraphStyle('ContactCenter', parent=contact_style, alignment=TA_CENTER)
    heading_style = ParagraphStyle(
        'Heading',
        parent=styles['Heading2'],
        fontName='Helvetica-Bold',
        fontSize=11,
        spaceBefore=16,
        spaceAfter=6,
        textColor=colors.HexColor('#0B2447'),
        alignment=TA_LEFT,
        # underline handled via HRFlowable for full-width rule
    )
    body_style = ParagraphStyle('Body', parent=styles['Normal'], fontName='Helvetica', fontSize=10, leading=14)
    meta_style = ParagraphStyle('Meta', parent=styles['Normal'], fontName='Helvetica-Oblique', fontSize=9, textColor=colors.grey, spaceAfter=4)

    elements = []
    photo = get_photo_flowable(data)

    if photo:
        name_para = Paragraph(data.get('name', ''), name_style)
        contact_para = Paragraph(build_contact_line(data), contact_style)
        header_table = Table([[ [name_para, Spacer(1, 4), contact_para], photo ]], colWidths=[None, 0.95*inch])
        header_table.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('ALIGN', (0, 0), (0, 0), 'LEFT'),
            ('ALIGN', (1, 0), (1, 0), 'RIGHT'),
            ('LEFTPADDING', (0, 0), (0, 0), 0),
            ('RIGHTPADDING', (0, 0), (0, 0), 12),
            ('LEFTPADDING', (1, 0), (1, 0), 0),
            ('RIGHTPADDING', (1, 0), (1, 0), 0),
        ]))
        elements.append(header_table)
    else:
        elements.append(Paragraph(data.get('name', ''), name_center_style))
        elements.append(Spacer(1, 4))
        elements.append(Paragraph(build_contact_line(data), contact_center_style))

    elements.append(Spacer(1, 20))

    if data.get('summary'):
        elements.append(Paragraph('PROFESSIONAL SUMMARY', heading_style))
        elements.append(Paragraph(data['summary'], body_style))

    if data.get('skills'):
        elements.append(Paragraph('TECHNICAL SKILLS', heading_style))
        elements.append(Paragraph(', '.join(data['skills']), body_style))

    if data.get('experience'):
        elements.append(Paragraph('PROFESSIONAL EXPERIENCE', heading_style))
        for exp in data['experience']:
            elements.append(Paragraph(f"<b>{exp.get('title', '')} — {exp.get('company', '')}</b>", body_style))
            elements.append(Paragraph(exp.get('dates', ''), meta_style))
            achievements = exp.get('achievements', [])
            if achievements:
                items = [ListItem(Paragraph(a, body_style)) for a in achievements]
                elements.append(ListFlowable(items, bulletType='bullet', leftIndent=14))
            elements.append(Spacer(1, 10))

    render_certifications_projects(elements, data, heading_style, body_style)

    if data.get('education'):
        elements.append(Paragraph('EDUCATION', heading_style))
        for edu in data['education']:
            elements.append(Paragraph(clean_education(edu), body_style))

    if data.get('additional_sections'):
        extra_sections = [section for section in data['additional_sections'] if section_heading_text(section.get('section') or section.get('title') or '') not in ('CERTIFICATIONS & TRAINING', 'KEY PROJECTS & ACHIEVEMENTS')]
        for section in sort_additional_sections(extra_sections):
            render_section(elements, section, heading_style, body_style)

    doc.build(elements)


def build_minimal(data, buffer):
    doc = SimpleDocTemplate(buffer, pagesize=letter, topMargin=0.6*inch, bottomMargin=0.6*inch)
    styles = getSampleStyleSheet()

    name_style = ParagraphStyle('Name', parent=styles['Title'], fontName='Helvetica-Bold', fontSize=22, spaceAfter=4, alignment=TA_LEFT)
    name_center_style = ParagraphStyle('NameCenter', parent=name_style, alignment=TA_CENTER)
    contact_style = ParagraphStyle('Contact', parent=styles['Normal'], fontName='Helvetica', textColor=colors.grey, spaceAfter=8, fontSize=9, alignment=TA_LEFT)
    contact_center_style = ParagraphStyle('ContactCenter', parent=contact_style, alignment=TA_CENTER)
    heading_style = ParagraphStyle(
        'Heading',
        parent=styles['Heading2'],
        fontName='Helvetica-Bold',
        fontSize=10,
        spaceBefore=14,
        spaceAfter=4,
        textColor=colors.HexColor('#0B2447'),
        alignment=TA_LEFT,
        # underline handled via HRFlowable for full-width rule
    )
    body_style = ParagraphStyle('Body', parent=styles['Normal'], fontName='Helvetica', fontSize=9, leading=12)
    meta_style = ParagraphStyle('Meta', parent=styles['Normal'], fontName='Helvetica-Oblique', fontSize=8, textColor=colors.grey, spaceAfter=4)

    elements = []
    photo = get_photo_flowable(data)

    if photo:
        name_para = Paragraph(data.get('name', ''), name_style)
        contact_para = Paragraph(build_contact_line(data), contact_style)
        header_table = Table([[ [name_para, Spacer(1, 4), contact_para], photo ]], colWidths=[None, 0.95*inch])
        header_table.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('ALIGN', (0, 0), (0, 0), 'LEFT'),
            ('ALIGN', (1, 0), (1, 0), 'RIGHT'),
            ('LEFTPADDING', (0, 0), (0, 0), 0),
            ('RIGHTPADDING', (0, 0), (0, 0), 12),
            ('LEFTPADDING', (1, 0), (1, 0), 0),
            ('RIGHTPADDING', (1, 0), (1, 0), 0),
        ]))
        elements.append(header_table)
    else:
        elements.append(Paragraph(data.get('name', ''), name_center_style))
        elements.append(Spacer(1, 4))
        elements.append(Paragraph(build_contact_line(data), contact_center_style))

    elements.append(Spacer(1, 18))

    if data.get('summary'):
        elements.append(Paragraph('PROFESSIONAL SUMMARY', heading_style))
        elements.append(Paragraph(data['summary'], body_style))

    if data.get('skills'):
        elements.append(Paragraph('TECHNICAL SKILLS', heading_style))
        elements.append(Paragraph(', '.join(data['skills']), body_style))

    if data.get('experience'):
        elements.append(Paragraph('PROFESSIONAL EXPERIENCE', heading_style))
        for exp in data['experience']:
            elements.append(Paragraph(f"<b>{exp.get('title', '')} — {exp.get('company', '')}</b>", body_style))
            elements.append(Paragraph(exp.get('dates', ''), meta_style))
            if exp.get('achievements'):
                items = [ListItem(Paragraph(a, body_style)) for a in exp['achievements']]
                elements.append(ListFlowable(items, bulletType='bullet', leftIndent=14))
            elements.append(Spacer(1, 8))

    render_certifications_projects(elements, data, heading_style, body_style)

    if data.get('education'):
        elements.append(Paragraph('EDUCATION', heading_style))
        for edu in data['education']:
            elements.append(Paragraph(clean_education(edu), body_style))

    if data.get('additional_sections'):
        extra_sections = [section for section in data['additional_sections'] if section_heading_text(section.get('section') or section.get('title') or '') not in ('CERTIFICATIONS & TRAINING', 'KEY PROJECTS & ACHIEVEMENTS')]
        for section in sort_additional_sections(extra_sections):
            render_section(elements, section, heading_style, body_style)

    doc.build(elements)


def build_bold(data, buffer):
    doc = SimpleDocTemplate(buffer, pagesize=letter, topMargin=0.6*inch, bottomMargin=0.6*inch)
    styles = getSampleStyleSheet()

    name_style = ParagraphStyle('Name', parent=styles['Title'], fontName='Helvetica-Bold', fontSize=24, spaceAfter=4, textColor=colors.HexColor('#0B2447'), alignment=TA_LEFT)
    name_center_style = ParagraphStyle('NameCenter', parent=name_style, alignment=TA_CENTER)
    contact_style = ParagraphStyle('Contact', parent=styles['Normal'], fontName='Helvetica', textColor=colors.HexColor('#5B6B77'), spaceAfter=8, alignment=TA_LEFT)
    contact_center_style = ParagraphStyle('ContactCenter', parent=contact_style, alignment=TA_CENTER)
    heading_style = ParagraphStyle(
        'Heading',
        parent=styles['Heading2'],
        fontName='Helvetica-Bold',
        fontSize=12,
        spaceBefore=16,
        spaceAfter=6,
        textColor=colors.HexColor('#0B2447'),
        alignment=TA_LEFT,
        # underline handled via HRFlowable for full-width rule
    )
    body_style = ParagraphStyle('Body', parent=styles['Normal'], fontName='Helvetica', fontSize=10, leading=14)
    meta_style = ParagraphStyle('Meta', parent=styles['Normal'], fontName='Helvetica-Oblique', fontSize=9, textColor=colors.grey, spaceAfter=4)

    elements = []
    photo = get_photo_flowable(data)

    if photo:
        name_para = Paragraph(data.get('name', ''), name_style)
        contact_para = Paragraph(build_contact_line(data), contact_style)
        header_table = Table([[ [name_para, Spacer(1, 4), contact_para], photo ]], colWidths=[None, 0.95*inch])
        header_table.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('ALIGN', (0, 0), (0, 0), 'LEFT'),
            ('LEFTPADDING', (0, 0), (0, 0), 0),
            ('RIGHTPADDING', (0, 0), (0, 0), 12),
            ('LEFTPADDING', (1, 0), (1, 0), 0),
            ('RIGHTPADDING', (1, 0), (1, 0), 0),
        ]))
        elements.append(header_table)
    else:
        elements.append(Paragraph(data.get('name', ''), name_center_style))
        elements.append(Spacer(1, 4))
        elements.append(Paragraph(build_contact_line(data), contact_center_style))

    elements.append(Spacer(1, 20))

    if data.get('summary'):
        elements.append(Paragraph('PROFESSIONAL SUMMARY', heading_style))
        elements.append(Paragraph(data['summary'], body_style))

    if data.get('skills'):
        elements.append(Paragraph('TECHNICAL SKILLS', heading_style))
        elements.append(Paragraph(', '.join(data['skills']), body_style))

    if data.get('experience'):
        elements.append(Paragraph('PROFESSIONAL EXPERIENCE', heading_style))
        for exp in data['experience']:
            elements.append(Paragraph(f"<b>{exp.get('title', '')} — {exp.get('company', '')}</b>", body_style))
            elements.append(Paragraph(exp.get('dates', ''), meta_style))
            if exp.get('achievements'):
                items = [ListItem(Paragraph(a, body_style)) for a in exp['achievements']]
                elements.append(ListFlowable(items, bulletType='bullet', leftIndent=14))
            elements.append(Spacer(1, 10))

    render_certifications_projects(elements, data, heading_style, body_style)

    if data.get('education'):
        elements.append(Paragraph('EDUCATION', heading_style))
        for edu in data['education']:
            elements.append(Paragraph(clean_education(edu), body_style))

    if data.get('additional_sections'):
        extra_sections = [section for section in data['additional_sections'] if section_heading_text(section.get('section') or section.get('title') or '') not in ('CERTIFICATIONS & TRAINING', 'KEY PROJECTS & ACHIEVEMENTS')]
        for section in sort_additional_sections(extra_sections):
            render_section(elements, section, heading_style, body_style)

    doc.build(elements)


def build_compact(data, buffer):
    doc = SimpleDocTemplate(buffer, pagesize=letter, topMargin=0.5*inch, bottomMargin=0.5*inch)
    styles = getSampleStyleSheet()

    name_style = ParagraphStyle('Name', parent=styles['Title'], fontName='Helvetica-Bold', fontSize=20, spaceAfter=2, alignment=TA_LEFT)
    name_center_style = ParagraphStyle('NameCenter', parent=name_style, alignment=TA_CENTER)
    contact_style = ParagraphStyle('Contact', parent=styles['Normal'], fontName='Helvetica', textColor=colors.grey, spaceAfter=6, fontSize=9, alignment=TA_LEFT)
    contact_center_style = ParagraphStyle('ContactCenter', parent=contact_style, alignment=TA_CENTER)
    heading_style = ParagraphStyle(
        'Heading',
        parent=styles['Heading2'],
        fontName='Helvetica-Bold',
        fontSize=9,
        spaceBefore=12,
        spaceAfter=4,
        textColor=colors.HexColor('#0B2447'),
        alignment=TA_LEFT,
        # underline handled via HRFlowable for full-width rule
    )
    body_style = ParagraphStyle('Body', parent=styles['Normal'], fontName='Helvetica', fontSize=9, leading=11)
    meta_style = ParagraphStyle('Meta', parent=styles['Normal'], fontName='Helvetica-Oblique', fontSize=8, textColor=colors.grey, spaceAfter=4)

    elements = []
    photo = get_photo_flowable(data)

    if photo:
        name_para = Paragraph(data.get('name', ''), name_style)
        contact_para = Paragraph(build_contact_line(data), contact_style)
        header_table = Table([[ [name_para, Spacer(1, 4), contact_para], photo ]], colWidths=[None, 0.85*inch])
        header_table.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('ALIGN', (0, 0), (0, 0), 'LEFT'),
            ('ALIGN', (1, 0), (1, 0), 'RIGHT'),
            ('LEFTPADDING', (0, 0), (0, 0), 0),
            ('RIGHTPADDING', (0, 0), (0, 0), 12),
            ('LEFTPADDING', (1, 0), (1, 0), 0),
            ('RIGHTPADDING', (1, 0), (1, 0), 0),
        ]))
        elements.append(header_table)
    else:
        elements.append(Paragraph(data.get('name', ''), name_center_style))
        elements.append(Spacer(1, 4))
        elements.append(Paragraph(build_contact_line(data), contact_center_style))

    elements.append(Spacer(1, 12))

    if data.get('summary'):
        elements.append(Paragraph('PROFESSIONAL SUMMARY', heading_style))
        elements.append(Paragraph(data['summary'], body_style))

    if data.get('skills'):
        elements.append(Paragraph('TECHNICAL SKILLS', heading_style))
        elements.append(Paragraph(', '.join(data['skills']), body_style))

    if data.get('experience'):
        elements.append(Paragraph('PROFESSIONAL EXPERIENCE', heading_style))
        for exp in data['experience']:
            elements.append(Paragraph(f"<b>{exp.get('title', '')} — {exp.get('company', '')}</b>", body_style))
            elements.append(Paragraph(exp.get('dates', ''), meta_style))
            if exp.get('achievements'):
                items = [ListItem(Paragraph(a, body_style)) for a in exp['achievements']]
                elements.append(ListFlowable(items, bulletType='bullet', leftIndent=12))
            elements.append(Spacer(1, 8))

    render_certifications_projects(elements, data, heading_style, body_style)

    if data.get('education'):
        elements.append(Paragraph('EDUCATION', heading_style))
        for edu in data['education']:
            elements.append(Paragraph(clean_education(edu), body_style))

    if data.get('additional_sections'):
        extra_sections = [section for section in data['additional_sections'] if section_heading_text(section.get('section') or section.get('title') or '') not in ('CERTIFICATIONS & TRAINING', 'KEY PROJECTS & ACHIEVEMENTS')]
        for section in sort_additional_sections(extra_sections):
            render_section(elements, section, heading_style, body_style)

    doc.build(elements)


def build_sidebar(data, buffer):
    doc = SimpleDocTemplate(buffer, pagesize=letter, topMargin=0.5*inch, bottomMargin=0.5*inch, leftMargin=0.5*inch, rightMargin=0.5*inch)
    styles = getSampleStyleSheet()

    left_heading = ParagraphStyle('LeftHeading', parent=styles['Heading2'], fontSize=10, textColor=colors.white, backColor=colors.HexColor('#111827'), leftIndent=4, rightIndent=4, spaceBefore=4, spaceAfter=4)
    left_body = ParagraphStyle('LeftBody', parent=styles['Normal'], fontSize=9, leading=12, textColor=colors.white)
    heading_style = ParagraphStyle(
        'Heading',
        parent=styles['Heading2'],
        fontSize=11,
        spaceBefore=12,
        spaceAfter=6,
        textColor=colors.HexColor('#0B2447'),
        # underline handled via HRFlowable for full-width rule
    )
    body_style = ParagraphStyle('Body', parent=styles['Normal'], fontSize=10, leading=13)
    meta_style = ParagraphStyle('Meta', parent=styles['Normal'], fontSize=9, textColor=colors.grey, spaceAfter=4)

    left_content = []
    photo = get_photo_flowable(data, size=0.75)
    if photo:
        left_content.extend([photo, Spacer(1, 10)])
    left_content.extend([Paragraph('CONTACT', left_heading), Paragraph(build_contact_line(data), left_body)])

    right_content = []
    if data.get('summary'):
        right_content.append(Paragraph('PROFESSIONAL SUMMARY', heading_style))
        right_content.append(Paragraph(data['summary'], body_style))
    if data.get('skills'):
        right_content.append(Paragraph('TECHNICAL SKILLS', heading_style))
        right_content.append(Paragraph(', '.join(data['skills']), body_style))
    if data.get('experience'):
        right_content.append(Paragraph('PROFESSIONAL EXPERIENCE', heading_style))
        for exp in data['experience']:
            right_content.append(Paragraph(f"<b>{exp.get('title', '')} — {exp.get('company', '')}</b>", body_style))
            right_content.append(Paragraph(exp.get('dates', ''), meta_style))
            if exp.get('achievements'):
                items = [ListItem(Paragraph(a, body_style)) for a in exp['achievements']]
                right_content.append(ListFlowable(items, bulletType='bullet', leftIndent=14))
            right_content.append(Spacer(1, 8))
    render_certifications_projects(right_content, data, heading_style, body_style)
    if data.get('additional_sections'):
        extra_sections = [section for section in data['additional_sections'] if section_heading_text(section.get('section') or section.get('title') or '') not in ('CERTIFICATIONS & TRAINING', 'KEY PROJECTS & ACHIEVEMENTS')]
        for section in sort_additional_sections(extra_sections):
            render_section(right_content, section, heading_style, body_style)
    if data.get('education'):
        right_content.append(Paragraph('EDUCATION', heading_style))
        for edu in data['education']:
            right_content.append(Paragraph(clean_education(edu), body_style))

    table = Table(
        [[KeepTogether(left_content), KeepTogether(right_content)]],
        colWidths=[2.2*inch, None]
    )
    table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 10),
        ('RIGHTPADDING', (0, 0), (-1, -1), 10),
        ('TOPPADDING', (0, 0), (-1, -1), 10),
    ]))

    doc.build([table])


# ---------- ROUTE ----------

TEMPLATE_BUILDERS = {
    'classic': build_classic,
    'sidebar': build_sidebar,
    'minimal': build_minimal,
    'bold': build_bold,
    'compact': build_compact,
}

@app.post("/api/generate-pdf")
async def generate_pdf(request: Request):
    data = await request.json()
    template = data.get('template', 'classic')
    style_reference = data.get('style_reference')
    if style_reference and template == 'classic':
        template = infer_template_from_style_reference(style_reference, template)
    build_fn = TEMPLATE_BUILDERS.get(template, build_classic)

    buffer = io.BytesIO()
    build_fn(data, buffer)
    buffer.seek(0)

    filename = f"{data.get('name', 'resume').replace(' ', '_')}_Resume.pdf"
    return StreamingResponse(
        buffer, media_type='application/pdf',
        headers={'Content-Disposition': f'attachment; filename="{filename}"'}
    )


import os as _os
_public_dir = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))), "public")
if _os.path.isdir(_public_dir):
    app.mount("/", StaticFiles(directory=_public_dir, html=True), name="static")