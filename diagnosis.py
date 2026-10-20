# diagnosis.py — Gemini AI 스티커 진단
from __future__ import annotations

import json
import random
import re
import time
from typing import Any

from google import genai
from google.genai import types
from google.genai.errors import APIError, ServerError


DIAGNOSIS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "summary": {"type": "string", "description": "정확히 한 문장인 핵심 총평. 80~140자."},
        "detail": {"type": "string", "description": "summary를 반복하지 않는 3~5문장의 구체적인 상세 설명."},
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "severity": {"type": "string", "enum": ["high", "medium", "low"]},
                    "area": {"type": "string"},
                    "what": {"type": "string"},
                    "why": {"type": "string"},
                    "how": {"type": "string"},
                    "market_basis": {"type": "string"},
                    "bbox": {"type": "array", "items": {"type": "integer"}, "description": "[ymin, xmin, ymax, xmax], each 0~1000. 특정 위치를 확실히 지정할 수 없으면 []"},
                },
                "required": ["severity", "area", "what", "why", "how", "market_basis", "bbox"],
            },
            "description": "실제로 개선할 가치가 있는 문제만 최대 4개.",
        },
        "strengths": {
            "type": "array",
            "items": {"type": "string"},
            "description": "이미지에서 실제로 확인되는 구체적인 장점 2~4개.",
        },
        "market_note": {"type": "string", "description": "시장 분석과 연결되는 핵심 참고사항. 없으면 빈 문자열."},
        "custom_criteria_results": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "criterion": {"type": "string"},
                    "status": {"type": "string", "enum": ["양호", "주의", "개선 필요", "판단 어려움"]},
                    "result": {"type": "string"},
                    "evidence": {"type": "string"},
                },
                "required": ["criterion", "status", "result", "evidence"],
            },
            "description": "사용자가 추가한 검사 기준을 각각 하나씩 평가한 결과.",
        },
    },
    "required": ["summary", "detail", "findings", "strengths", "market_note", "custom_criteria_results"],
}

SYSTEM_PROMPT = """당신은 스티커 콘텐츠를 검토하는 AI 진단 도구입니다.
공식적으로 공개된 OGQ 제작 가이드와 사용자가 선택한 검사 기준을 바탕으로 분석하세요.

중요:
- OGQ의 비공개 내부 심사 매뉴얼을 알고 있다고 주장하지 마세요.
- 심사 통과 확률을 예측하지 마세요.
- 이미지에서 실제로 확인할 수 없는 사실은 지어내지 마세요.
- 문제는 가능한 경우 실제 이미지 안의 위치를 bbox로 표시하세요.
- bbox 좌표는 Gemini 공식 형식인 0~1000 정규화 좌표 [ymin, xmin, ymax, xmax] 순서입니다.
- 문제 위치를 특정하기 어렵다면 bbox는 []로 두세요.
- 전체 이미지를 bbox로 지정하는 것은 해당 문제가 실제로 이미지 전체에 걸친 경우에만 허용합니다.
- 시장 근거를 사용할 때는 전달된 시장 분석 결과에 명시된 사실을 우선 사용하세요.
- 공개 웹 검색 결과는 보조 참고 자료일 뿐이며, 법적 표절/저작권 침해 여부를 판정하는 근거로 사용하지 마세요.
- 사용자 태그나 시장 메타데이터만으로 이미지의 실제 모습을 단정하지 마세요.
- 한 줄 총평은 정확히 한 문장만 작성하세요.
- detail은 summary를 반복하지 말고 이미지에서 확인되는 근거를 중심으로 3~5문장으로 설명하세요.
- 사용자가 추가한 커스텀 검사 기준은 다른 기준과 섞지 말고, 반드시 각 기준별로 별도 평가 결과를 만들어 주세요.
- custom_criteria_results의 criterion은 사용자가 입력한 기준 문장을 최대한 그대로 유지하세요.
"""

TRANSIENT_CODES = {408, 429, 500, 502, 503, 504}
MODEL_CANDIDATES = ["gemini-3.8-flash", "gemini-3.7-flash", "gemini-3.6-flash", "gemini-3.5-flash-lite"]


def _clean_text(value: Any) -> str:
    return " ".join(str(value or "").replace("\r", " ").replace("\n", " ").split())


def _one_line_summary(value: Any) -> str:
    text = _clean_text(value)
    if not text:
        return "이미지의 주요 특징과 선택한 검사 기준을 종합해 개선 우선순위를 확인할 필요가 있습니다."
    parts = re.split(r"(?<=[.!?다요함])\s+", text)
    summary = parts[0].strip()
    if len(summary) > 150:
        summary = summary[:147].rstrip(" ,.;") + "…"
    return summary


def _normalise_bbox(bbox: Any) -> list[int]:
    if not isinstance(bbox, list) or len(bbox) != 4:
        return []
    try:
        values = [max(0, min(1000, int(float(v)))) for v in bbox]
        if values[2] <= values[0] or values[3] <= values[1]:
            return []
        area_ratio = ((values[2] - values[0]) * (values[3] - values[1])) / 1_000_000
        if area_ratio > 0.97:
            return []
        return values
    except (TypeError, ValueError):
        return []


def _json_from_response(text: str) -> dict[str, Any]:
    text = (text or "").strip()
    if not text:
        return {}
    try:
        value = json.loads(text)
        return value if isinstance(value, dict) else {}
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return {}
    try:
        value = json.loads(match.group(0))
        return value if isinstance(value, dict) else {}
    except json.JSONDecodeError:
        return {}


def _generate_content_with_retry(client, contents, config, model_name: str, attempts: int = 2):
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            return client.models.generate_content(model=model_name, contents=contents, config=config)
        except (ServerError, APIError) as exc:
            last_error = exc
            code = getattr(exc, "code", None) or getattr(exc, "status_code", None)
            message = str(exc)
            transient = code in TRANSIENT_CODES or any(str(c) in message for c in TRANSIENT_CODES)
            if not transient or attempt >= attempts - 1:
                raise
            delay = min(8.0, 1.5 * (2**attempt)) + random.uniform(0, 0.5)
            time.sleep(delay)
    raise last_error or RuntimeError("Gemini 요청에 실패했습니다.")


def diagnose_detailed(
    file_bytes: bytes,
    media_type: str,
    api_key: str,
    selected_criteria: list[str] | None = None,
    market_context: str = "",
    custom_criteria: list[str] | None = None,
) -> dict[str, Any]:
    client = genai.Client(api_key=api_key)
    selected = list(selected_criteria or [])
    custom = list(custom_criteria or [])
    standard = [item for item in selected if item not in custom]

    user_prompt = f"""
이 이미지를 아래 검사 기준으로 진단하세요.

[표준/기본 검사 기준]
{json.dumps(standard, ensure_ascii=False)}

[사용자 지정 검사 기준]
{json.dumps(custom, ensure_ascii=False)}

[시장 비교 결과]
{market_context or "시장 비교를 실행하지 않았습니다."}

반드시 다음을 지키세요.
- summary는 정확히 한 문장.
- detail은 3~5문장.
- findings는 실제 개선 가치가 있는 문제만 최대 4개.
- 각 finding은 어디가/왜/어떻게가 서로 구체적으로 연결되어야 함.
- 시장 분석 자료가 실제로 해당 문제와 연결될 때만 market_basis를 채움.
- 커스텀 기준이 있다면 custom_criteria_results에서 기준별로 하나씩 평가.
- custom_criteria_results에서 각 기준의 result는 '그래서 현재 이미지가 어떤 상태인가'를 한두 문장으로 구체적으로 설명.
- evidence에는 이미지에서 확인 가능한 근거 또는 선택한 기준에 맞는 관찰을 작성.
- 커스텀 기준을 평가할 수 없는 경우 '판단 어려움'으로 표시하고 억지로 결론을 만들지 말 것.
- bbox는 특정 가능한 경우에만 작성하며 [ymin, xmin, ymax, xmax] 순서를 지킵니다.
- bbox는 문제와 직접 관련된 최소한의 영역을 잡고, 이미지 전체를 감싸는 상자는 피하세요.
- 글씨 문제라면 해당 글씨 줄/단어 영역, 캐릭터 문제라면 해당 캐릭터 부위를 중심으로 잡으세요.
"""

    contents = [
        types.Part.from_bytes(data=file_bytes, mime_type=media_type),
        user_prompt,
    ]

    last_error: Exception | None = None
    for model_name in MODEL_CANDIDATES:
        try:
            response = _generate_content_with_retry(
                client,
                contents,
                types.GenerateContentConfig(
                    system_instruction=SYSTEM_PROMPT,
                    response_mime_type="application/json",
                    response_schema=DIAGNOSIS_SCHEMA,
                    max_output_tokens=1800,
                    temperature=0.2,
                ),
                model_name=model_name,
                attempts=2,
            )
            raw_text = response.text or ""
            data = _json_from_response(raw_text)
            if not data:
                raise RuntimeError(f"{model_name}의 구조화된 응답을 읽지 못했습니다.")
            break
        except (ServerError, APIError, RuntimeError) as exc:
            last_error = exc
            continue
    else:
        raise RuntimeError(f"Gemini 진단에 실패했습니다. 모델들을 순차적으로 시도했지만 응답을 받지 못했습니다: {last_error}")

    findings: list[dict[str, Any]] = []
    for item in (data.get("findings") or [])[:4]:
        if not isinstance(item, dict):
            continue
        findings.append(
            {
                "severity": item.get("severity", "low"),
                "area": _clean_text(item.get("area") or "검토 항목"),
                "what": _clean_text(item.get("what")),
                "why": _clean_text(item.get("why")),
                "how": _clean_text(item.get("how")),
                "market_basis": _clean_text(item.get("market_basis")),
                "bbox": _normalise_bbox(item.get("bbox")),
            }
        )

    strengths: list[str] = []
    for value in (data.get("strengths") or [])[:4]:
        cleaned = _clean_text(value)
        if cleaned and cleaned not in strengths:
            strengths.append(cleaned)

    custom_results: list[dict[str, str]] = []
    raw_custom = data.get("custom_criteria_results")
    if isinstance(raw_custom, list):
        for item in raw_custom:
            if not isinstance(item, dict):
                continue
            criterion = _clean_text(item.get("criterion"))
            status = _clean_text(item.get("status")) or "판단 어려움"
            if status not in {"양호", "주의", "개선 필요", "판단 어려움"}:
                status = "판단 어려움"
            result = _clean_text(item.get("result"))
            evidence = _clean_text(item.get("evidence"))
            if criterion:
                custom_results.append({"criterion": criterion, "status": status, "result": result, "evidence": evidence})

    # 누락된 사용자 기준이 있으면 UI에서 '평가 누락'으로 분명히 알 수 있게 채운다.
    existing = {item["criterion"] for item in custom_results}
    for criterion in custom:
        if criterion not in existing:
            custom_results.append(
                {
                    "criterion": criterion,
                    "status": "판단 어려움",
                    "result": "이번 AI 응답에서 이 사용자 지정 기준에 대한 개별 평가가 반환되지 않았습니다.",
                    "evidence": "응답 누락",
                }
            )

    detail = _clean_text(data.get("detail"))
    if len(detail) < 30:
        detail = "이미지에서 확인되는 시각적 특성과 선택한 검사 기준을 함께 고려했습니다. 발견된 문제는 실제 수정 단계에서 우선순위를 정해 반영하는 것이 좋습니다."

    return {
        "summary": _one_line_summary(data.get("summary")),
        "detail": detail,
        "findings": findings,
        "strengths": strengths,
        "market_note": _clean_text(data.get("market_note")),
        "custom_criteria_results": custom_results,
        "raw_text": response.text or "",
        "model_used": model_name,
    }


def render_diagnosis_markdown(diagnosis: dict[str, Any]) -> str:
    lines = [f"### 한 줄 총평\n{diagnosis.get('summary', '')}"]
    detail = diagnosis.get("detail")
    if detail:
        lines.append(f"\n### 상세 분석\n{detail}")

    findings = diagnosis.get("findings", [])
    lines.append("\n### 발견된 문제")
    if not findings:
        lines.append("주요 개선 필요 항목이 발견되지 않았습니다.")
    else:
        for idx, f in enumerate(findings, 1):
            lines.append(
                f"{idx}. **{f.get('area', '검토 항목')} ({f.get('severity', 'low')})**\n"
                f"   - **어디가:** {f.get('what', '')}\n"
                f"   - **왜:** {f.get('why', '')}\n"
                f"   - **어떻게:** {f.get('how', '')}"
            )
            if f.get("market_basis"):
                lines.append(f"   - **시장 근거:** {f['market_basis']}")

    lines.append("\n### 장점")
    strengths = diagnosis.get("strengths", [])
    if strengths:
        lines.extend([f"- {s}" for s in strengths])
    else:
        lines.append("- 이미지에서 확인 가능한 별도의 장점을 찾지 못했습니다.")

    if diagnosis.get("market_note"):
        lines.append(f"\n### 시장 비교 참고\n{diagnosis['market_note']}")
    return "\n".join(lines)


def diagnose(file_bytes, media_type, api_key):
    detailed = diagnose_detailed(file_bytes, media_type, api_key)
    return render_diagnosis_markdown(detailed)
