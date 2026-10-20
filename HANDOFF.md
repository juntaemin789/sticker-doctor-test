# 인수인계 가이드 — OGQ 스티커 닥터

이 폴더는 "제4회 NAVER OGQ마켓 AI Competition" 출품용 프로젝트의 코드 전달본입니다.
API 키·개인정보는 제거되어 있으므로, 아래 순서대로 세팅하면 이어서 개발할 수 있습니다.

## 1. 이 프로젝트가 뭔가요?
- **OGQ 스티커 닥터**: 스티커를 OGQ마켓에 올리기 전에 심사 거절 사유를 미리 잡아내고, 판매력 개선점을 알려주는 AI 진단 웹앱
- 전체 기획·진행 상황·남은 일정은 **PLAN.md** 참고 (이 파일부터 읽으세요)

## 2. 처음 세팅 (Mac 기준, 최초 1회)
터미널을 열고 이 폴더로 이동한 뒤:

```bash
cd 이_폴더_경로
python3 -m venv venv          # 프로젝트 전용 파이썬 환경 생성
source venv/bin/activate      # 환경 켜기 (줄 앞에 (venv) 뜨면 성공)
pip install -r requirements.txt
```

## 3. API 키 준비 (필수)
AI 진단 기능은 Anthropic(Claude) API를 사용합니다. **본인 키가 필요합니다.**

1. https://console.anthropic.com 에서 계정 생성 (18세 미만이면 보호자와 함께)
2. Billing에서 크레딧 충전($5면 충분) + 월 사용 한도 설정 권장
3. API Keys → Create Key → 생성된 키를 "Copy 버튼"으로 전체 복사
4. `.streamlit/secrets.toml.example`을 복사해 같은 자리에 `secrets.toml`로 저장하고 키 붙여넣기

⚠️ secrets.toml과 API 키는 절대 GitHub·채팅에 올리지 마세요 (.gitignore가 막아주지만 주의).

## 4. 실행
```bash
source venv/bin/activate
streamlit run app.py
```
브라우저가 열리면: 이미지 업로드 → 스펙 검사 결과 확인 → "AI 심층 진단 받기" 버튼.
끌 때는 터미널에서 control + C.

## 5. 파일 구조
| 파일 | 역할 |
|---|---|
| `app.py` | 화면(UI). Streamlit 코드 |
| `checker.py` | 기능 1: OGQ 공식 스펙 검사 (크기·용량·컬러모드·투명배경·여백) |
| `diagnosis.py` | 기능 2: Claude API로 AI 진단 (심사 리스크·가독성·오탈자·개선안) |
| `requirements.txt` | 필요한 라이브러리 목록 |
| `PLAN.md` | 기획·진행 상황·일정 (필독) |

## 6. 다음 할 일 (PLAN.md에도 있음)
1. **기능 3**: OGQ 오픈 API 연동 — https://developers.ogq.me 가입 → 테스트 키(일 1,000건 무료) → 스티커 검색 API로 유사·인기 스티커 비교 리포트
2. UI 다듬기 → README(대회 템플릿) → 3분 피치 영상 → 신청서 (마감 2026.07.31)

## 7. Claude(AI)와 이어서 개발하는 법
이 프로젝트는 Claude와 페어 프로그래밍으로 개발되었습니다 (대회 규정상 허용, README에 명시 예정).
Claude 데스크톱 앱(Cowork)에서 이 폴더를 연결하고 이렇게 말하면 됩니다:

> "PLAN.md랑 HANDOFF.md 읽고 이어서 개발하자. 다음은 기능 3이야."

## 8. 주의사항
- 대회 규정: GitHub 커밋 히스토리 검증 + 본선 라이브 코딩이 있으므로, **코드를 이해하면서** 진행하고 커밋은 본인 계정으로 직접 할 것
- 팀 구성 변경(팀원 추가 등)은 신청서 제출 전에 확정하면 됨 (팀당 1~4명)
