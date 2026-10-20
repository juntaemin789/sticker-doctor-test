"""Sticker Doctor 검사 기준 프리셋과 사용자 커스텀 기준."""
from __future__ import annotations

DEFAULT_CRITERIA = [
    ("파일 규격", "OGQ 공개 제작 가이드의 해상도/파일 설정을 확인합니다."),
    ("파일 용량", "각 이미지가 공개 가이드의 용량 기준을 만족하는지 확인합니다."),
    ("컬러 모드", "RGB 계열 여부를 확인합니다."),
    ("투명 배경", "스티커 배경이 투명한지 확인합니다."),
    ("여백", "불필요한 여백이 과도하지 않은지 확인합니다."),
    ("가독성", "작은 화면에서 글씨와 표현이 이해되기 쉬운지 확인합니다."),
    ("다크모드", "어두운 배경에서도 캐릭터와 글씨가 잘 보이는지 확인합니다."),
    ("오탈자", "스티커 안의 문구에서 오탈자를 확인합니다."),
    ("콘텐츠 적합성", "커뮤니케이션에 도움이 되는지, 부적합한 표현이 없는지 확인합니다."),
    ("중복·유사성", "시장에 이미 존재하는 콘텐츠와 지나치게 유사한 요소가 있는지 참고용으로 확인합니다."),
]

PLATFORM_PRESETS = {
    "OGQ 공개 가이드": [name for name, _ in DEFAULT_CRITERIA],
    "기본 파일 검사만": ["파일 규격", "파일 용량", "컬러 모드", "투명 배경", "여백"],
    "AI 품질 검사 중심": ["가독성", "다크모드", "오탈자", "콘텐츠 적합성", "중복·유사성"],
}


def criteria_descriptions() -> dict[str, str]:
    return dict(DEFAULT_CRITERIA)


def build_selected_criteria(
    preset: str,
    custom_selected: list[str],
    custom_rules: list[str] | None = None,
) -> list[str]:
    if preset == "내가 직접 선택":
        selected = list(custom_selected)
    else:
        selected = list(PLATFORM_PRESETS.get(preset, PLATFORM_PRESETS["OGQ 공개 가이드"]))

    for rule in custom_rules or []:
        rule = str(rule).strip()
        if rule and rule not in selected:
            selected.append(rule)
    return selected
