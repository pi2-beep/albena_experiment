from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    KeepTogether,
    PageTemplate,
    Paragraph,
    PageBreak,
    Spacer,
    Table,
    TableStyle,
)
from xml.sax.saxutils import escape


ROOT = Path(__file__).resolve().parent
FONT_DIR = ROOT / "fonts"
PDF_DIR = ROOT / "data" / "pdfs"


def _font_path(filename: str) -> Path:
    local = FONT_DIR / filename
    if local.exists():
        return local
    system_candidates = [
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    ]
    if "Bold" in filename:
        system_candidates = [Path(str(path).replace(".ttf", "-Bold.ttf")) for path in system_candidates]
    for candidate in system_candidates:
        if candidate.exists():
            return candidate
    raise FileNotFoundError(f"Липсва PDF шрифтът {filename}")


def _register_fonts() -> None:
    if "DejaVu" not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont("DejaVu", str(_font_path("DejaVuSans.ttf"))))
        pdfmetrics.registerFont(TTFont("DejaVu-Bold", str(_font_path("DejaVuSans-Bold.ttf"))))


def _text(value: Any, fallback: str = "—") -> str:
    if value is None or value == "":
        return fallback
    if isinstance(value, bool):
        return "Да" if value else "Не"
    return str(value)


def _option(value: str) -> str:
    return {
        "A": "Вариант A — запазване на режима",
        "B": "Вариант B — постепенно намаляване",
        "C": "Вариант C — еднакви такси",
        "yes": "Да",
        "no": "Не",
    }.get(value, _text(value))


def build_pdf(data: dict[str, Any], output_path: Path) -> None:
    _register_fonts()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    palette = {
        "ink": colors.HexColor("#17233B"),
        "muted": colors.HexColor("#5B667A"),
        "navy": colors.HexColor("#173B63"),
        "teal": colors.HexColor("#1A7A78"),
        "pale": colors.HexColor("#EAF4F3"),
        "line": colors.HexColor("#D5DDE8"),
    }
    styles = getSampleStyleSheet()
    body = ParagraphStyle(
        "BodyBG",
        parent=styles["BodyText"],
        fontName="DejaVu",
        fontSize=9.2,
        leading=13.2,
        textColor=palette["ink"],
        spaceAfter=4,
    )
    small = ParagraphStyle("SmallBG", parent=body, fontSize=7.7, leading=10.5, textColor=palette["muted"])
    title = ParagraphStyle(
        "TitleBG",
        parent=body,
        fontName="DejaVu-Bold",
        fontSize=20,
        leading=25,
        alignment=TA_CENTER,
        textColor=palette["navy"],
        spaceAfter=6,
    )
    subtitle = ParagraphStyle("SubtitleBG", parent=body, alignment=TA_CENTER, textColor=palette["muted"], spaceAfter=14)
    heading = ParagraphStyle(
        "HeadingBG",
        parent=body,
        fontName="DejaVu-Bold",
        fontSize=13,
        leading=17,
        textColor=palette["navy"],
        spaceBefore=8,
        spaceAfter=7,
    )
    subheading = ParagraphStyle(
        "SubheadingBG",
        parent=body,
        fontName="DejaVu-Bold",
        fontSize=10.2,
        leading=14,
        textColor=palette["teal"],
        spaceBefore=5,
        spaceAfter=4,
    )

    def p(value: Any, style: ParagraphStyle = body) -> Paragraph:
        return Paragraph(escape(_text(value)).replace("\n", "<br/>"), style)

    def rows(items: list[tuple[str, Any]]) -> Table:
        table_data = [[p(label, small), p(value)] for label, value in items]
        table = Table(table_data, colWidths=[55 * mm, 122 * mm], repeatRows=0, hAlign="LEFT")
        table.setStyle(
            TableStyle(
                [
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#F5F7FA")),
                    ("BOX", (0, 0), (-1, -1), 0.5, palette["line"]),
                    ("INNERGRID", (0, 0), (-1, -1), 0.35, palette["line"]),
                    ("LEFTPADDING", (0, 0), (-1, -1), 7),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                    ("TOPPADDING", (0, 0), (-1, -1), 6),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ]
            )
        )
        return table

    def page_footer(canvas, doc):
        canvas.saveState()
        canvas.setFont("DejaVu", 7.5)
        canvas.setFillColor(palette["muted"])
        canvas.drawString(17 * mm, 11 * mm, "Анонимизиран запис — Експеримент Албена")
        canvas.drawRightString(193 * mm, 11 * mm, f"Страница {doc.page}")
        canvas.restoreState()

    frame = Frame(16 * mm, 18 * mm, 178 * mm, 260 * mm, leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
    doc = BaseDocTemplate(
        str(output_path),
        pagesize=A4,
        leftMargin=16 * mm,
        rightMargin=16 * mm,
        topMargin=19 * mm,
        bottomMargin=19 * mm,
        title="Резултати от експеримент с ИИ",
        author="Експеримент Албена",
    )
    doc.addPageTemplates(PageTemplate(id="main", frames=[frame], onPage=page_footer))

    baseline = data.get("baseline", {})
    interactions = data.get("interactions", [])
    after = data.get("after_ai", {})
    experience = data.get("experience", {})
    consent = data.get("consent", {})
    story = [
        Spacer(1, 9 * mm),
        Paragraph("Резултати от експеримента", title),
        Paragraph("ИИ и формирането на преценка при публични политики", subtitle),
        rows(
            [
                ("Код на участника", data.get("participant_code")),
                ("Дата на съгласие", consent.get("date")),
                ("Начало на сесията", data.get("created_at")),
                ("Краен срок", data.get("deadline_at")),
                ("Завършване", data.get("completed_at") or datetime.now().isoformat(timespec="seconds")),
                ("Изтекъл лимит от 45 минути", data.get("time_limit_reached", False)),
            ]
        ),
        Spacer(1, 8 * mm),
        Paragraph("Информирано съгласие", heading),
        rows(
            [
                ("Прочетена информация", consent.get("read_info")),
                ("Доброволно участие", consent.get("voluntary")),
                ("Запис и анонимизиран анализ", consent.get("recording")),
                ("Без чувствителна информация", consent.get("no_sensitive")),
                ("Съгласие за участие", consent.get("participate")),
            ]
        ),
        PageBreak(),
        Paragraph("Фаза 1 — Самостоятелна преценка", heading),
        rows(
            [
                ("Препоръчан вариант", _option(baseline.get("preferred"))),
                ("Точки за A", baseline.get("points_a")),
                ("Точки за B", baseline.get("points_b")),
                ("Точки за C", baseline.get("points_c")),
                ("Общо точки", sum(int(baseline.get(k) or 0) for k in ("points_a", "points_b", "points_c"))),
                ("Увереност", f"{_text(baseline.get('confidence'))} / 100"),
                ("Най-важно съображение", baseline.get("rationale")),
            ]
        ),
        Paragraph("Фаза 2 — Работа с ИИ", heading),
    ]

    for index, interaction in enumerate(interactions[:5], start=1):
        prompt = interaction.get("prompt", "")
        response = interaction.get("response", "")
        if not prompt and not response:
            continue
        requirement = "задължително" if index <= 3 else "незадължително"
        story.append(
            KeepTogether(
                [
                    Paragraph(f"Взаимодействие {index} ({requirement})", subheading),
                    rows([("Prompt към ИИ", prompt), ("Отговор на ИИ", response)]),
                ]
            )
        )

    story.extend(
        [
            Paragraph("Пълен transcript", subheading),
            p(data.get("full_transcript")),
            PageBreak(),
            Paragraph("Преценка след работата с ИИ", heading),
            rows(
                [
                    ("Препоръчан вариант", _option(after.get("preferred"))),
                    ("Точки за A", after.get("points_a")),
                    ("Точки за B", after.get("points_b")),
                    ("Точки за C", after.get("points_c")),
                    ("Общо точки", sum(int(after.get(k) or 0) for k in ("points_a", "points_b", "points_c"))),
                    ("Увереност", f"{_text(after.get('confidence'))} / 100"),
                    ("Най-важно съображение", after.get("rationale")),
                    ("Възприемано влияние на ИИ", f"{_text(after.get('influence'))} / 100"),
                ]
            ),
            Paragraph("Оценка на анализа с ИИ (1–7)", subheading),
            rows(
                [
                    ("По-добро разбиране", after.get("understand")),
                    ("Сравнение на алтернативите", after.get("compare")),
                    ("Нови аргументи", after.get("new_arguments")),
                    ("Финална препоръка", after.get("recommendation_help")),
                    ("Основан на доказателства", after.get("evidence_based")),
                    ("Надежден", after.get("reliable")),
                    ("Убедителен", after.get("persuasive")),
                    ("Балансиран", after.get("balanced")),
                ]
            ),
            Paragraph("Проверка и окончателно решение", subheading),
            rows(
                [
                    ("Желание за проверка на доказателствата", _option(after.get("verify_evidence"))),
                    ("Окончателна препоръка", _option(after.get("final_preferred"))),
                    ("Окончателна увереност", f"{_text(after.get('final_confidence'))} / 100"),
                ]
            ),
            PageBreak(),
            Paragraph("Опит с генеративен ИИ", heading),
            rows(
                [
                    ("Честота на употреба", experience.get("frequency")),
                    ("Подготовка/редактиране на текст", _option(experience.get("text_work"))),
                    ("Анализ на информация", _option(experience.get("analysis"))),
                    ("Формулиране на варианти", _option(experience.get("options"))),
                    ("Сравнение на варианти", _option(experience.get("comparison"))),
                    ("Подготовка на препоръки", _option(experience.get("recommendations"))),
                    ("Работа основно с ИИ или данни", _option(experience.get("ai_data"))),
                    ("Възрастова група", experience.get("age_group")),
                ]
            ),
            Spacer(1, 8 * mm),
            p("Документът съдържа данните, предоставени от участника. Не се записват име, имейл или други преки идентификатори.", small),
        ]
    )
    doc.build(story)


def pdf_path_for(session_id: str) -> Path:
    safe = "".join(ch for ch in session_id if ch.isalnum() or ch in "-_")
    return PDF_DIR / f"result-{safe}.pdf"
