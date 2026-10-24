"""Build editable Word and print PDF from the same reviewed Chinese Markdown.

Use the materials environment (python-docx/reportlab), not the simulation runtime.
The PDF has embedded Chinese glyphs; DOCX uses Word-native headings and tables.
"""

import argparse
import re
from html import escape
from pathlib import Path

from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    Image,
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Table,
    TableStyle,
)

ROOT = Path(__file__).resolve().parents[2]
WIDTH = 468


def plain(text):
    text = re.sub(r"\[([^]]+)\]\([^)]+\)", r"\1", text)
    return text.replace("**", "").replace("`", "")


def blocks(text):
    """Parse only the document's authored Markdown subset, preserving page breaks."""
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        i += 1
        if not line:
            continue
        if line == "<!-- pagebreak -->":
            yield "break", ""
        elif line.startswith("```"):
            code = []
            while i < len(lines) and not lines[i].startswith("```"):
                code.append(lines[i])
                i += 1
            i += 1
            yield "code", "\n".join(code)
        elif line.startswith("|"):
            rows = [line]
            while i < len(lines) and lines[i].strip().startswith("|"):
                rows.append(lines[i].strip())
                i += 1
            yield (
                "table",
                [
                    [plain(c.strip()) for c in row.strip("|").split("|")]
                    for row in rows
                    if not re.match(r"^\|[\s:|\-]+\|$", row)
                ],
            )
        elif line.startswith("!["):
            match = re.match(r"!\[([^]]*)\]\(([^)]+)\)", line)
            if match:
                yield "image", (match[1], match[2])
        elif line.startswith("#"):
            yield "h" + str(len(line) - len(line.lstrip("#"))), plain(line.lstrip("# "))
        else:
            paragraph = [line]
            while (
                i < len(lines)
                and lines[i].strip()
                and not lines[i].startswith(("#", "|", "```", "![", "<!--"))
            ):
                paragraph.append(lines[i].strip())
                i += 1
            yield "p", plain(" ".join(paragraph))


def set_font(style, size, color="202C38"):
    style.font.name = "Calibri"
    style.font.size = Pt(size)
    style.font.color.rgb = RGBColor.from_string(color)
    style.element.get_or_add_rPr().rFonts.set(qn("w:eastAsia"), "宋体")


def table_geometry(table, widths):
    """DXA geometry is explicit in the grid, table and every cell."""
    table.autofit = False
    props = table._tbl.tblPr
    width = props.find(qn("w:tblW"))
    width.set(qn("w:type"), "dxa")
    width.set(qn("w:w"), "9360")
    indent = OxmlElement("w:tblInd")
    indent.set(qn("w:w"), "120")
    indent.set(qn("w:type"), "dxa")
    props.append(indent)
    margins = OxmlElement("w:tblCellMar")
    for name, value in [("top", 80), ("bottom", 80), ("start", 120), ("end", 120)]:
        node = OxmlElement("w:" + name)
        node.set(qn("w:w"), str(value))
        node.set(qn("w:type"), "dxa")
        margins.append(node)
    props.append(margins)
    for col, twips in zip(table._tbl.tblGrid.gridCol_lst, widths, strict=True):
        col.set(qn("w:w"), str(twips))
    for row in table.rows:
        for cell, twips in zip(row.cells, widths, strict=True):
            cell._tc.get_or_add_tcPr().find(qn("w:tcW")).set(qn("w:w"), str(twips))


def build(markdown, output):
    items = list(blocks(markdown.read_text()))
    doc = Document()
    section = doc.sections[0]
    section.page_width, section.page_height = Inches(8.5), Inches(11)
    section.top_margin = section.bottom_margin = Inches(1)
    section.left_margin = section.right_margin = Inches(1)
    section.header_distance = section.footer_distance = Inches(0.492)
    # standard_business_brief; named overrides: Chinese glyph font, title 20pt,
    # compact 9pt table text and 8.5pt code for a readable two-page course brief.
    for name, size in [("Normal", 11), ("Title", 20), ("Subtitle", 10)]:
        style = doc.styles[name]
        set_font(style, size)
        style.paragraph_format.space_before = Pt(0)
        style.paragraph_format.space_after = Pt(6)
        style.paragraph_format.line_spacing = 1.1
    for level, size, before, after, color in [
        (1, 16, 16, 8, "2E74B5"),
        (2, 13, 12, 6, "2E74B5"),
        (3, 12, 8, 4, "1F4D78"),
    ]:
        style = doc.styles[f"Heading {level}"]
        set_font(style, size, color)
        style.paragraph_format.space_before = Pt(before)
        style.paragraph_format.space_after = Pt(after)
        style.paragraph_format.line_spacing = 1.1
    header = section.header.paragraphs[0]
    header.text = "多电梯智能群控系统  /  课程项目"
    header.style = doc.styles["Subtitle"]
    footer = section.footer.paragraphs[0]
    footer.alignment = 2
    footer.add_run("第 ")
    field = OxmlElement("w:fldSimple")
    field.set(qn("w:instr"), "PAGE")
    footer._p.append(field)
    footer.add_run(" 页")

    font = "Chinese"
    font_path = Path("/System/Library/Fonts/STHeiti Light.ttc")
    if font_path.exists():
        pdfmetrics.registerFont(TTFont(font, str(font_path), subfontIndex=0))
    else:
        font = "STSong-Light"
        pdfmetrics.registerFont(UnicodeCIDFont(font))
    styles = {
        "p": ParagraphStyle(
            "Body", fontName=font, fontSize=11, leading=12.1, spaceAfter=6, wordWrap="CJK"
        ),
        "h1": ParagraphStyle(
            "Title", fontName=font, fontSize=20, leading=26, spaceAfter=10, wordWrap="CJK"
        ),
        "h2": ParagraphStyle(
            "H1",
            fontName=font,
            fontSize=16,
            leading=19,
            spaceBefore=16,
            spaceAfter=8,
            textColor=colors.HexColor("#2E74B5"),
            wordWrap="CJK",
            keepWithNext=True,
        ),
        "h3": ParagraphStyle(
            "H2",
            fontName=font,
            fontSize=13,
            leading=16,
            spaceBefore=12,
            spaceAfter=6,
            textColor=colors.HexColor("#2E74B5"),
            wordWrap="CJK",
            keepWithNext=True,
        ),
        "table": ParagraphStyle("Cell", fontName=font, fontSize=9, leading=11, wordWrap="CJK"),
        "code": ParagraphStyle(
            "Code", fontName=font, fontSize=8.5, leading=11, spaceAfter=6, wordWrap="CJK"
        ),
    }
    story = []
    for kind, value in items:
        if kind == "break":
            doc.add_page_break()
            story.append(PageBreak())
        elif kind == "table":
            columns = len(value[0])
            widths = (
                ([1100, 4100, 4160] if value[0][0] == "编号" else [2300, 3530, 3530])
                if columns == 3
                else [9360 // columns] * columns
            )
            widths[-1] = 9360 - sum(widths[:-1])
            table = doc.add_table(rows=len(value), cols=columns)
            table.style = "Table Grid"
            table_geometry(table, widths)
            repeat = OxmlElement("w:tblHeader")
            table.rows[0]._tr.get_or_add_trPr().append(repeat)
            for i, row in enumerate(value):
                for j, text in enumerate(row):
                    cell = table.cell(i, j)
                    cell.text = text
                    for paragraph in cell.paragraphs:
                        paragraph.paragraph_format.space_after = Pt(3)
                        for run in paragraph.runs:
                            run.font.size = Pt(9)
                            run.bold = i == 0
                    if i == 0:
                        fill = OxmlElement("w:shd")
                        fill.set(qn("w:fill"), "F2F4F7")
                        cell._tc.get_or_add_tcPr().append(fill)
            data = [[Paragraph(escape(c), styles["table"]) for c in row] for row in value]
            table_pdf = Table(data, colWidths=[v / 20 for v in widths], repeatRows=1, hAlign="LEFT")
            table_pdf.setStyle(
                TableStyle(
                    [
                        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#C9D1D9")),
                        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F2F4F7")),
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                        ("LEFTPADDING", (0, 0), (-1, -1), 6),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                        ("TOPPADDING", (0, 0), (-1, -1), 4),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                    ]
                )
            )
            story.append(KeepTogether([table_pdf]))
        elif kind == "image":
            caption, target = value
            image = (markdown.parent / target).resolve()
            from PIL import Image as PILImage

            with PILImage.open(image) as im:
                width, height = im.size
            scale = min(WIDTH / width, 360 / height)
            doc.add_picture(str(image), width=Inches(width * scale / 72))
            doc.paragraphs[-1].paragraph_format.keep_with_next = True
            doc.add_paragraph(caption, "Caption")
            story.append(
                KeepTogether(
                    [
                        Image(str(image), width * scale, height * scale),
                        Paragraph(escape(caption), styles["table"]),
                    ]
                )
            )
        else:
            style = (
                "Title"
                if kind == "h1"
                else f"Heading {int(kind[1:]) - 1}"
                if kind.startswith("h")
                else "Normal"
            )
            paragraph = doc.add_paragraph(value, style)
            if kind == "code":
                paragraph.paragraph_format.keep_together = True
                for run in paragraph.runs:
                    run.font.size = Pt(8.5)
            if value.endswith("："):
                paragraph.paragraph_format.keep_with_next = True
            text = escape(value).replace("\n", "<br/>")
            rendered = Paragraph(text, styles.get(kind, styles["p"]))
            if value.endswith("："):
                rendered.keepWithNext = True
            if kind == "code":
                lead = story.pop() if story and isinstance(story[-1], Paragraph) else None
                story.append(KeepTogether([lead, rendered] if lead else [rendered]))
            else:
                story.append(rendered)
    output.parent.mkdir(parents=True, exist_ok=True)
    doc.core_properties.author = "课程项目小组"
    doc.core_properties.title = items[0][1]
    doc.save(output.with_suffix(".docx"))

    def furniture(canvas, document):
        canvas.setFont(font, 8)
        canvas.setFillColor(colors.HexColor("#697586"))
        canvas.drawString(72, 760, "多电梯智能群控系统  /  课程项目")
        canvas.drawRightString(540, 38, f"第 {document.page} 页")

    pdf = SimpleDocTemplate(
        str(output.with_suffix(".pdf")),
        pagesize=(612, 792),
        rightMargin=72,
        leftMargin=72,
        topMargin=72,
        bottomMargin=72,
        title=items[0][1],
        author="课程项目小组",
    )
    pdf.build(story, onFirstPage=furniture, onLaterPages=furniture)
    print(output)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("markdown", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    build(args.markdown, args.output)
