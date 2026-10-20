# report_utils.py — PDF 리포트 생성 + 재검사 히스토리 저장/조회
# app.py에서 import해서 사용한다.

import io
import json
import os
from datetime import datetime

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
)
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

# reportlab 기본 폰트(Helvetica)는 한글 글리프가 없고,
# CID 폰트(HYGothic-Medium 등)는 폰트를 PDF에 "임베드"하지 않고 뷰어에 이미 깔려있는
# 한글 폰트팩을 빌려쓰는 방식이라 그 폰트팩이 없는 환경(대부분의 뷰어)에서는 텍스트가 아예 안 보인다.
# 그래서 실제 한글 트루타입 폰트 파일을 프로젝트에 포함시켜 PDF 안에 통째로 임베드한다.
_FONT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts")
FONT_BODY = "NanumGothic"
FONT_HEADING = "NanumGothic-Bold"

pdfmetrics.registerFont(TTFont(FONT_BODY, os.path.join(_FONT_DIR, "NanumGothic-Regular.ttf")))
pdfmetrics.registerFont(TTFont(FONT_HEADING, os.path.join(_FONT_DIR, "NanumGothic-Bold.ttf")))

HISTORY_PATH = "diagnosis_history.json"


# ---------- 재검사 히스토리 ----------

def load_history():
    """저장된 재검사 히스토리를 불러온다. 없으면 빈 리스트."""
    if not os.path.exists(HISTORY_PATH):
        return []
    try:
        with open(HISTORY_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return []


def save_history_entry(score, pass_count, warn_count, fail_count, checklist_done, checklist_total):
    """이번 검사 결과를 히스토리에 한 줄 추가한다."""
    history = load_history()
    history.append({
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "score": round(score, 1),
        "pass": pass_count,
        "warn": warn_count,
        "fail": fail_count,
        "checklist": f"{checklist_done}/{checklist_total}",
    })
    with open(HISTORY_PATH, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)
    return history


# ---------- 우선순위 Todo 리스트 ----------

def build_priority_todo(all_file_results):
    """
    all_file_results: [{"name": str, "results": [(grade, item, msg), ...]}, ...]
    실패(fail) 항목을 최우선으로, 그다음 경고(warn) 항목을 영향받은 파일 수(빈도) 내림차순으로 정렬해
    "무엇부터 고칠지" 우선순위 리스트를 만든다.
    """
    grade_weight = {"fail": 0, "warn": 1, "pass": 2}
    agg = {}  # (grade, item) -> {"count": int, "msgs": set, "files": [str]}

    for file_result in all_file_results:
        for grade, item, msg in file_result["results"]:
            if grade == "pass":
                continue
            key = (grade, item)
            if key not in agg:
                agg[key] = {"count": 0, "msg": msg, "files": []}
            agg[key]["count"] += 1
            agg[key]["files"].append(file_result["name"])

    todo = [
        {
            "grade": grade,
            "item": item,
            "msg": data["msg"],
            "affected_count": data["count"],
            "affected_files": data["files"],
        }
        for (grade, item), data in agg.items()
    ]
    todo.sort(key=lambda t: (grade_weight.get(t["grade"], 9), -t["affected_count"]))
    return todo


# ---------- 심사 통과 확률 스코어 ----------

def compute_score(all_file_results, checklist_done, checklist_total):
    """
    자동 검사(pass/warn/fail)와 수동 규정 체크리스트를 합산해 0~100 점수로 환산한다.
    fail=0점, warn=0.5점, pass=1점으로 가중 후, 체크리스트 완료율과 평균낸다.
    """
    total_checks = 0
    earned = 0.0
    for file_result in all_file_results:
        for grade, _, _ in file_result["results"]:
            total_checks += 1
            if grade == "pass":
                earned += 1.0
            elif grade == "warn":
                earned += 0.5

    auto_score = (earned / total_checks * 100) if total_checks else 100.0
    checklist_score = (checklist_done / checklist_total * 100) if checklist_total else 100.0
    return (auto_score * 0.7) + (checklist_score * 0.3)


# ---------- 간단 마크다운 → PDF 문단 변환 ----------

def _markdown_to_flowables(md_text, body_style, sub_heading_style):
    """diagnosis.py가 돌려주는 마크다운(### 제목, **굵게**)을 PDF 문단으로 변환한다."""
    import re
    flowables = []
    for raw_line in md_text.split("\n"):
        line = raw_line.strip()
        if not line:
            flowables.append(Spacer(1, 4))
            continue
        # XML 특수문자 이스케이프 (reportlab Paragraph는 미니 XML 파서를 씀)
        esc = line.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        if esc.startswith("### "):
            flowables.append(Spacer(1, 6))
            flowables.append(Paragraph(f"<b>{esc[4:]}</b>", sub_heading_style))
            continue
        esc = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", esc)  # **굵게** -> <b>굵게</b>
        flowables.append(Paragraph(esc, body_style))
    return flowables


# ---------- PDF 리포트 ----------

def build_pdf_report(all_file_results, todo_list, score, checklist_status, diagnosis_texts=None):
    """진단 결과를 요약한 PDF를 만들어 바이트로 반환한다. st.download_button에 바로 사용 가능.

    diagnosis_texts: {파일명: AI 진단 마크다운 텍스트} — 없으면(None/빈 dict) 해당 섹션은 안내 문구만 표시.
    """
    diagnosis_texts = diagnosis_texts or {}
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, topMargin=40, bottomMargin=40)
    styles = getSampleStyleSheet()

    # 기본 스타일들도 한글 폰트로 교체 (안 바꾸면 Helvetica라 한글이 깨진다)
    styles["Normal"].fontName = FONT_BODY

    title_style = ParagraphStyle(
        "TitleMint", parent=styles["Title"], textColor=colors.HexColor("#0F9B8E"),
        fontName=FONT_HEADING,
    )
    heading_style = ParagraphStyle(
        "HeadingMint", parent=styles["Heading2"], textColor=colors.HexColor("#0B3B36"),
        fontName=FONT_HEADING,
    )
    cell_style = ParagraphStyle("CellBody", parent=styles["Normal"], fontName=FONT_BODY, fontSize=8, leading=11)

    story = []
    story.append(Paragraph("OGQ 스티커 닥터 — 진단 리포트", title_style))
    story.append(Paragraph(datetime.now().strftime("%Y-%m-%d %H:%M 생성"), styles["Normal"]))
    story.append(Spacer(1, 16))

    story.append(Paragraph(f"심사 통과 확률 스코어: {score:.1f}점 / 100점", heading_style))
    story.append(Spacer(1, 12))

    # 우선순위 Todo 테이블
    story.append(Paragraph("개선 우선순위 Todo", heading_style))
    if todo_list:
        # 표 안의 긴 텍스트("내용" 열)는 Paragraph로 감싸야 폭에 맞춰 줄바꿈되고 폰트도 적용된다.
        table_data = [["우선순위", "구분", "항목", "영향받은 파일 수", "내용"]]
        for i, t in enumerate(todo_list, start=1):
            grade_label = "실패" if t["grade"] == "fail" else "주의"
            table_data.append([
                str(i), grade_label, Paragraph(t["item"], cell_style),
                str(t["affected_count"]), Paragraph(t["msg"], cell_style),
            ])
        tbl = Table(table_data, colWidths=[35, 35, 80, 60, 220])
        tbl.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EEFBF9")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#0B3B36")),
            ("FONTNAME", (0, 0), (-1, -1), FONT_BODY),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#BFEFE9")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]))
        story.append(tbl)
    else:
        story.append(Paragraph("고칠 항목이 없습니다. 모든 검사를 통과했어요.", styles["Normal"]))
    story.append(Spacer(1, 16))

    # AI 심층 진단 결과 (파일별)
    story.append(Paragraph("AI 심층 진단 결과", heading_style))
    sub_heading_style = ParagraphStyle(
        "SubHeadingMint", parent=styles["Normal"], fontName=FONT_HEADING,
        fontSize=10, textColor=colors.HexColor("#0F9B8E"),
    )
    file_name_style = ParagraphStyle(
        "FileNameMint", parent=styles["Normal"], fontName=FONT_HEADING,
        fontSize=11, textColor=colors.HexColor("#0B3B36"), spaceBefore=10,
    )
    if diagnosis_texts:
        for file_name, text in diagnosis_texts.items():
            story.append(Paragraph(f"■ {file_name}", file_name_style))
            story.extend(_markdown_to_flowables(text, styles["Normal"], sub_heading_style))
            story.append(Spacer(1, 8))
    else:
        story.append(Paragraph(
            "AI 심층 진단을 아직 실행하지 않았어요. '전체 AI 진단 받기'를 먼저 눌러주세요.",
            styles["Normal"],
        ))
    story.append(Spacer(1, 16))

    # 규정 위반 체크리스트
    story.append(Paragraph("규정 위반 셀프 체크리스트", heading_style))
    for label, checked in checklist_status.items():
        mark = "완료" if checked else "미완료"
        story.append(Paragraph(f"[{mark}] {label}", styles["Normal"]))

    doc.build(story)
    buffer.seek(0)
    return buffer.getvalue()
