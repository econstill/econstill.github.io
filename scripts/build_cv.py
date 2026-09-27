"""Build the academic CV from index.html (requires reportlab and lxml)."""

from datetime import date
from html import escape
from pathlib import Path
import os
import re

from lxml import html
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, KeepTogether


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "output/pdf/Sijie-Wang-CV.pdf"
PAGE_WIDTH, PAGE_HEIGHT = A4
LINK_COLOR = "#164F77"


def clean(text):
    return re.sub(r"\s+", " ", text).translate(str.maketrans({
        "\u2013": "-", "\u2014": "-", "\u2011": "-",
        "\u201c": '"', "\u201d": '"', "\u2019": "'",
    }))


def inline(element):
    """Translate only supported inline markup, retaining academic hyperlinks."""
    result = escape(clean(element.text or ""))
    for child in element:
        content = inline(child)
        if child.tag == "a":
            href = escape(child.get("href", ""), quote=True)
            result += f'<a href="{href}" color="{LINK_COLOR}">{content}</a>'
        elif child.tag in ("strong", "em"):
            tag = "b" if child.tag == "strong" else "i"
            result += f"<{tag}>{content}</{tag}>"
        else:
            result += content
        result += escape(clean(child.tail or ""))
    return result.strip()


def link(label, url):
    return f'<a href="{escape(url, quote=True)}" color="{LINK_COLOR}">{escape(label)}</a>'


def build():
    font_dir = Path(os.environ.get("CV_FONT_DIR", "/System/Library/Fonts/Supplemental"))
    for name, suffix in (("Times-Roman", ""), ("Times-Bold", " Bold"),
                         ("Times-Italic", " Italic"), ("Times-BoldItalic", " Bold Italic")):
        font = font_dir / f"Times New Roman{suffix}.ttf"
        if font.exists():
            pdfmetrics.registerFont(TTFont(name, str(font)))
    pdfmetrics.registerFontFamily("Times-Roman", normal="Times-Roman", bold="Times-Bold",
                                  italic="Times-Italic", boldItalic="Times-BoldItalic")
    page = html.parse(str(ROOT / "index.html"))
    sections = {s.find("h2").text: s for s in page.xpath("//main/section")}
    body = ParagraphStyle("body", fontName="Times-Roman", fontSize=10.5,
                          leading=13.3, textColor=colors.HexColor("#171717"), spaceAfter=5)
    heading = ParagraphStyle("section", parent=body, fontName="Times-Bold",
                             fontSize=12, leading=15, spaceBefore=10, spaceAfter=5,
                             keepWithNext=True)
    title = ParagraphStyle("name", parent=body, fontName="Times-Bold",
                           fontSize=24, leading=28, alignment=TA_CENTER, spaceAfter=3)
    contact = ParagraphStyle("contact", parent=body, fontSize=10,
                             leading=13, alignment=TA_CENTER, spaceAfter=3)
    note = ParagraphStyle("note", parent=body, fontName="Times-Italic",
                          fontSize=9, leading=11, spaceAfter=6)
    paper = ParagraphStyle("paper", parent=body, leftIndent=13,
                           firstLineIndent=-13, spaceAfter=6)
    story = [Paragraph("Sijie Wang (Still)", title),
             Paragraph("Curriculum Vitae", contact),
             Paragraph("School of Economics and Management, Beijing Jiaotong University", contact),
             Paragraph("Beijing, China", contact)]
    email = page.xpath('//header//a[starts-with(@href,"mailto:")]')[0].get("href")
    website = page.xpath('//link[@rel="canonical"]')[0].get("href")
    scholar = page.xpath('//header//a[contains(@href,"scholar.google.com")]')[0].get("href")
    story += [Paragraph(" &nbsp; | &nbsp; ".join([
        link(email.removeprefix("mailto:"), email),
        link(website.removeprefix("https://").rstrip("/"), website),
        link("Google Scholar", scholar),
    ]), contact), Spacer(1, 3)]

    story.append(Paragraph("Education", heading))
    advisor = sections["About"].xpath('.//a[contains(@href,"scholar.google.com")]')[0]
    for i, item in enumerate(sections["Education"].xpath("./ul/li")):
        text = inline(item)
        if i == 0:
            text = text.replace("Ph.D. in Applied Economics", "Ph.D. student in Applied Economics")
            text += "<br/>Advisor: " + link(clean(advisor.text_content()).strip(), advisor.get("href")) + "."
        story.append(Paragraph(text, body))

    story.append(Paragraph("Research Interests", heading))
    interests = [clean(x.text_content()).strip() for x in sections["Research Interests"].xpath("./ul/li")]
    story.append(Paragraph(escape("; ".join(interests)) + ".", body))

    for name in ("Publications", "Working Papers", "Work in Progress"):
        story.append(Paragraph(name, heading))
        if name == "Publications":
            story.append(Paragraph(inline(sections[name].xpath('./p[@class="authorship-note"]')[0]), note))
        for number, item in enumerate(sections[name].xpath("./ol/li"), 1):
            story.append(KeepTogether([Paragraph(f"{number}. &nbsp; {inline(item)}", paper)]))

    story.append(Paragraph("Academic Service", heading))
    seminar = sections["Seminar"].find("p")
    text = inline(seminar).replace("I co-organize the", "Co-organizer of the")
    story.append(Paragraph(text, body))

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont("Times-Roman", 8.5)
        canvas.setFillColor(colors.HexColor("#555555"))
        canvas.drawString(46, 25, "Updated " + date.today().strftime("%B %d, %Y"))
        canvas.drawRightString(PAGE_WIDTH - 46, 25, str(doc.page))
        canvas.restoreState()

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(str(OUTPUT), pagesize=A4, leftMargin=46, rightMargin=46,
                            topMargin=35, bottomMargin=40, title="Sijie Wang - Curriculum Vitae",
                            author="Sijie Wang", subject="Academic curriculum vitae")
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    print(OUTPUT)


if __name__ == "__main__":
    build()
