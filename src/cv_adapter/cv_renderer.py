"""
CV Renderer — generates a compact, ATS-friendly PDF from plain text CV.
Max 2 pages, tight spacing, clean Helvetica font.
"""
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_CENTER
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, HRFlowable
from reportlab.lib import colors
from reportlab.pdfbase import pdfmetrics

OUTPUT_DIR = Path(__file__).parent.parent.parent / "output" / "cvs"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# ── Colors ────────────────────────────────────────────────────────────────────
BLUE = colors.HexColor("#1a5f8a")
GRAY = colors.HexColor("#555555")
BLACK = colors.black

# ── Styles ────────────────────────────────────────────────────────────────────
S_NAME = ParagraphStyle(
    "name",
    fontName="Helvetica-Bold",
    fontSize=16,
    textColor=BLUE,
    alignment=TA_CENTER,
    spaceAfter=1,
    spaceBefore=0,
    leading=18,
)
S_CONTACT = ParagraphStyle(
    "contact",
    fontName="Helvetica",
    fontSize=9,
    textColor=GRAY,
    alignment=TA_CENTER,
    spaceAfter=4,
    spaceBefore=0,
    leading=11,
)
S_SECTION = ParagraphStyle(
    "section",
    fontName="Helvetica-Bold",
    fontSize=10,
    textColor=BLUE,
    alignment=TA_LEFT,
    spaceBefore=6,
    spaceAfter=1,
    leading=12,
)
S_JOB_TITLE = ParagraphStyle(
    "job_title",
    fontName="Helvetica-Bold",
    fontSize=9,
    textColor=BLACK,
    alignment=TA_LEFT,
    spaceBefore=4,
    spaceAfter=0,
    leading=11,
)
S_BULLET = ParagraphStyle(
    "bullet",
    fontName="Helvetica",
    fontSize=9,
    textColor=BLACK,
    alignment=TA_LEFT,
    leftIndent=10,
    firstLineIndent=-6,
    spaceBefore=0,
    spaceAfter=1,
    leading=11,
)
S_NORMAL = ParagraphStyle(
    "normal",
    fontName="Helvetica",
    fontSize=9,
    textColor=BLACK,
    alignment=TA_LEFT,
    spaceBefore=0,
    spaceAfter=1,
    leading=11,
)
S_SKILLS_KEY = ParagraphStyle(
    "skills_key",
    fontName="Helvetica",
    fontSize=9,
    textColor=BLACK,
    alignment=TA_LEFT,
    spaceBefore=0,
    spaceAfter=1,
    leading=11,
)

HR = HRFlowable(
    width="100%",
    thickness=0.5,
    color=BLUE,
    spaceAfter=3,
    spaceBefore=0,
)


def _safe(text: str) -> str:
    """Escape HTML special chars for ReportLab Paragraph."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _is_section_header(line: str) -> bool:
    stripped = line.strip()
    return (
        stripped.isupper()
        and len(stripped) > 2
        and not stripped.startswith("-")
        and not all(c == "-" for c in stripped)
    )


def _is_divider(line: str) -> bool:
    return all(c in "-─=" for c in line.strip()) and len(line.strip()) > 3


def _is_bullet(line: str) -> bool:
    return line.strip().startswith("- ")


def _is_job_title(line: str, idx: int, lines: list[str]) -> bool:
    """Heuristic: short line with | separator or follows a section."""
    s = line.strip()
    return "|" in s and len(s) < 120 and not s.startswith("-")


def render_to_pdf(cv_text: str, job_title: str, company: str, candidate_name: str = "JGrueso") -> Path:
    safe_company = "".join(c for c in company if c.isalnum() or c in " _-")[:30].strip()
    safe_title = "".join(c for c in job_title if c.isalnum() or c in " _-")[:30].strip()
    safe_name = "".join(c for c in candidate_name if c.isalnum() or c in " _-")[:20].strip().replace(" ", "")
    filename = f"CV_{safe_name}_{safe_company}_{safe_title}.pdf".replace(" ", "_")
    filepath = OUTPUT_DIR / filename

    doc = SimpleDocTemplate(
        str(filepath),
        pagesize=A4,
        topMargin=12 * mm,
        bottomMargin=12 * mm,
        leftMargin=16 * mm,
        rightMargin=16 * mm,
    )

    story = []
    lines = [l.rstrip() for l in cv_text.split("\n")]

    i = 0
    is_first = True          # candidate name
    is_second = False        # contact line
    in_header_zone = True    # first few lines = name + contact

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # Skip empty lines (we control spacing via styles)
        if not stripped:
            i += 1
            continue

        # Skip raw divider lines (-----) — we draw our own HR after section headers
        if _is_divider(stripped):
            i += 1
            continue

        # Candidate name — first non-empty line
        if is_first:
            story.append(Paragraph(_safe(stripped), S_NAME))
            is_first = False
            is_second = True
            i += 1
            continue

        # Contact info — second non-empty line (or lines with @ / +57 / linkedin)
        if is_second or (in_header_zone and any(x in stripped for x in ["@", "+57", "linkedin", "linkedin.com", "|"]) and i < 6):
            story.append(Paragraph(_safe(stripped), S_CONTACT))
            is_second = False
            i += 1
            continue

        # Past the header zone after first section header
        if _is_section_header(stripped):
            in_header_zone = False
            story.append(Spacer(1, 2))
            story.append(Paragraph(_safe(stripped), S_SECTION))
            i += 1
            continue

        # Bullet point
        if _is_bullet(line):
            text = _safe(stripped[2:])
            story.append(Paragraph(f"• {text}", S_BULLET))
            i += 1
            continue

        # Job title / company line with pipe separator
        if _is_job_title(line, i, lines):
            story.append(Paragraph(_safe(stripped), S_JOB_TITLE))
            i += 1
            continue

        # Skills line (Category: value, value)
        if ":" in stripped and len(stripped) < 150:
            parts = stripped.split(":", 1)
            key = _safe(parts[0].strip())
            val = _safe(parts[1].strip()) if len(parts) > 1 else ""
            story.append(Paragraph(f"<b>{key}:</b> {val}", S_SKILLS_KEY))
            i += 1
            continue

        # Default: normal paragraph
        story.append(Paragraph(_safe(stripped), S_NORMAL))
        i += 1

    doc.build(story)
    return filepath
