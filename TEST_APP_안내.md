# Supabase 테스트 앱 (제출 저장소와 별개로 쓰세요)

이 폴더 전체를 **새 GitHub 저장소**에 올리고 Streamlit에서 새 앱으로 배포하면 됩니다.
폰트(fonts), 쿠키 부품, supabase 부품이 모두 들어 있어서 앞에서 본 두 오류가 나지 않습니다.

## Streamlit Secrets에 넣을 것
SUPABASE_URL = "https://내프로젝트.supabase.co"
SUPABASE_SERVICE_KEY = "내비밀키"
GEMINI_API_KEY = "기존 앱과 같은 값"
OGQ_API_KEY = "기존 앱과 같은 값"
OGQ_API_BASE_URL = "https://4th-ai-ogq.competition.ogq.me"
OGQ_USER_ID = "sticker-doctor"

## 확인
회원가입 -> 로그인 -> 진단 1회 -> Supabase Table Editor(users, auth_sessions, diagnosis_records)에 줄이 생기는지 봅니다.
