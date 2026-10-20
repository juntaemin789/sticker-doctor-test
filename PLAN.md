# OGQ 스티커 닥터 — 프로젝트 계획 및 진행 상황

> 새 Claude 세션 시작 시: 이 파일을 먼저 읽으면 프로젝트 전체 맥락을 파악할 수 있음.

## 프로젝트 개요
- **대회**: 제4회 NAVER OGQ마켓 AI Competition (주최: 전국마이스터고교장협의회, 후원: NAVER OGQ마켓)
- **지원 마감**: 2026.07.31 — 제출물: 온라인 신청서 + GitHub 레포 + 실제 접속 가능한 프로덕트 URL + 3분 피치 영상(유튜브)
- **트랙**: AI × 창작자 경제
- **팀**: OO팀 (팀 정보는 직접 기입)
- **개발 방식**: Claude(AI)와 페어로 개발. AI 사용 내역은 README에 명시 필수(대회 규정, 가점 요소). 커밋은 본인 계정으로 직접. 본선에 라이브 코딩 챌린지 있으므로 코드를 이해하며 진행.

## 프로덕트 정의
**OGQ 스티커 닥터** — 스티커가 안 팔리는 이유를 진단하고 심사 통과와 판매를 돕는 AI 도구.
OGQ에 자동 태깅 AI가 이미 있으므로 "태그 생성"이 아니라 **심사 통과 + 판매 최적화 진단**에 집중 (차별화 포인트).

기능 3단계:
1. ✅ **심사 스펙 자동 검사** — OGQ 공식 기준(메인 240x240 1개 / 스티커 740x640 24개 / 탭 96x74 1개, 각 1MB 이하, RGB, 투명 배경, 여백 최소화) 자동 판정 — **완료**
2. ✅ **AI 진단** — Claude API(claude-haiku-4-5, 비전)로 심사 리스크·가독성·오탈자·개선점 진단 (`diagnosis.py`) — **완료 (7/13)**
3. ⬜ **시장 비교 리포트** — OGQ 오픈 API(스티커 검색)로 유사·인기 스티커 비교, 차별화 조언 — **다음 작업**

기능 2 메모: API 키는 로컬 `.streamlit/secrets.toml` + Streamlit Cloud의 Settings > Secrets 두 곳에 필요. 진단 결과는 st.session_state에 캐시(같은 파일 중복 호출 방지 = 비용 절약).

## 기술 스택 및 인프라
- Python + Streamlit + Pillow (개발자는 코딩 첫 경험 — 설명은 기초부터)
- 레포: 인수자가 본인 GitHub 계정에 새로 생성 (Public 권장)
- 배포: Streamlit Community Cloud (share.streamlit.io)에서 본인 레포 연결해 새로 배포 — main에 푸시하면 자동 배포
- 커밋 도구: GitHub Desktop / 로컬 실행: `source venv/bin/activate` 후 `streamlit run app.py`
- API 키 등 비밀 정보는 .env / .streamlit/secrets.toml (gitignore 처리됨)

## 파일 구조
- `app.py` — Streamlit UI
- `checker.py` — 스펙 검사 로직 (분류·용량·컬러모드·투명배경·여백)
- `requirements.txt` — streamlit, pillow

## 다음 세션 시작 시 첫 할 일 (인수자 기준)
1. HANDOFF.md 순서대로 로컬 세팅 → 본인 GitHub 레포 생성·커밋 → Streamlit Cloud 배포 + Secrets에 본인 API 키 등록 → 배포판에서 AI 진단 작동 확인
2. 기능 3 착수: developers.ogq.me 가입 → 테스트 키 발급 → 스티커 검색 API 연동

## 남은 일정 (지원 마감 7/31 기준)
- ~7/18: 기능 2 (Claude API 진단) — API 키 발급 + 사용량 제한 설정 포함
- ~7/22: 기능 3 (OGQ API 연동: https://developers.ogq.me 가입, 테스트 키 일 1,000건)
- ~7/25: UI 다듬기 + README (대회 템플릿: 문제정의/아키텍처/사용 스택/실행방법/AI 사용 내역/라이선스) + 오픈소스 라이선스(MIT, 가점)
- ~7/28: 3분 피치 영상(팀 소개 20s/문제 40s/데모 90s/향후 계획 30s) + 신청서
- 7/29~31: 버퍼 + 제출

## 심사 기준 메모 (100점)
기술 완성도 30 / 창의성 25 / 임팩트 20 / 실행력 15 / 발표력 10 + 가점(오픈소스 공개, 다국어 지원) + 윤리 P/F(개인정보·저작권·AI 생성물 표기·미성년자 안전)

## 참고 링크
- OGQ 스티커 제작 가이드(공식 스펙 출처): https://creators.ogq.me/guides/contents/sticker
- OGQ 오픈 API 문서: https://developers.ogq.me/project/api_doc


## 현재 구현 확장 (VER2 기반)
- OGQ 시장 비교: 사용자가 입력한 느낌/태그를 검색어로 OGQ Sticker Search API에 전달하고, 결과의 제목/설명 등 확인 가능한 메타데이터를 Gemini가 비교 분석
- 검사 기준 커스텀: OGQ 공개 제작 가이드 프리셋 + 사용자 체크리스트 선택 + 사용자 정의 기준 1개 추가
- 위치 기반 AI 진단: Gemini가 `bbox`를 0~1000 정규화 좌표로 반환하면 앱이 이미지 위에 빨간 타원으로 표시
- AI 진단 결과를 `어디가 / 왜 / 어떻게` 형식으로 표시
- OGQ 내부 비공개 심사 매뉴얼을 구현했다고 주장하지 않음
- 일반 사용자용 기능 5개와 초보 창작자용 기능 5개는 아이디어 단계로 유지하며 현재 구현하지 않음
