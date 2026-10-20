"""사용자 계정 + 사용자별 진단 기록 + 리뷰 저장소 (Supabase 버전).

기존 SQLite 버전(user_store.py)과 함수 이름·인자·반환 형태가 같아서
app.py는 수정하지 않고 이 파일로 바꿔 끼우기만 하면 됩니다.

- 비밀번호는 평문 저장 없이 PBKDF2-HMAC-SHA256 해시 + 솔트로 저장합니다.
- 로그인 세션 토큰은 해시만 DB에 저장합니다 (원본은 브라우저 쿠키에만 존재).
- Supabase에는 service_role 키로 서버에서만 접근합니다. 이 키는 절대
  GitHub·브라우저에 노출하지 마세요 (Streamlit secrets 에만 저장).
"""
from __future__ import annotations

import hashlib
import os
import secrets
from datetime import date, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from supabase import Client, create_client

try:  # postgrest 오류 코드 확인용 (supabase 패키지에 포함)
    from postgrest.exceptions import APIError
except Exception:  # pragma: no cover
    APIError = Exception  # type: ignore[assignment,misc]

KST = ZoneInfo("Asia/Seoul")
SESSION_MAX_AGE = timedelta(days=30)
MIN_SIGNUP_AGE = 14  # 만 14세 미만은 가입 불가 (개인정보 보호법: 보호자 동의 필요)
_PBKDF2_ROUNDS = 310_000

_client: Client | None = None
_user_id_cache: dict[str, int] = {}


# ── 연결 ────────────────────────────────────────────────────
def _get_secret(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        try:
            import streamlit as st

            value = str(st.secrets.get(name, "") or "")
        except Exception:
            value = ""
    return value.strip()


def _db() -> Client:
    global _client
    if _client is None:
        url = _get_secret("SUPABASE_URL")
        key = _get_secret("SUPABASE_SERVICE_KEY")
        if not url or not key:
            raise RuntimeError(
                "SUPABASE_URL / SUPABASE_SERVICE_KEY 가 설정되지 않았습니다. "
                ".streamlit/secrets.toml (또는 Streamlit Cloud > Settings > Secrets)에 넣어주세요."
            )
        _client = create_client(url, key)
    return _client


def init_db() -> None:
    """테이블은 supabase_schema.sql 로 미리 만들어 둡니다. 여기서는 연결만 확인합니다."""
    _db().table("users").select("id").limit(1).execute()


# ── 유틸 ────────────────────────────────────────────────────
def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _to_kst_text(value: str | None) -> str:
    """DB의 timestamptz → 기존 화면과 같은 '2026-10-07T19:22:29' 형태(KST)."""
    if not value:
        return ""
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return str(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(KST).replace(tzinfo=None).isoformat(timespec="seconds")


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _hash_password(password: str, salt: bytes | None = None) -> tuple[str, str]:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _PBKDF2_ROUNDS)
    return salt.hex(), digest.hex()


# ── 계정 ────────────────────────────────────────────────────
def _age_on(birth: date, today: date) -> int:
    return today.year - birth.year - ((today.month, today.day) < (birth.month, birth.day))


def create_user(username: str, password: str, birth_date: date | None = None) -> tuple[bool, str]:
    username = username.strip()
    if len(username) < 2 or len(username) > 30:
        return False, "아이디는 2~30자로 입력해주세요."
    if len(password) < 6:
        return False, "비밀번호는 6자 이상으로 입력해주세요."

    # 생년월일은 서버에서도 다시 검사한다 (화면 검사만 믿지 않기)
    if birth_date is not None:
        today = datetime.now(KST).date()
        if birth_date > today:
            return False, "생년월일이 미래 날짜입니다. 다시 선택해주세요."
        if _age_on(birth_date, today) < MIN_SIGNUP_AGE:
            return False, f"만 {MIN_SIGNUP_AGE}세 미만은 가입할 수 없습니다."

    salt, password_hash = _hash_password(password)
    try:
        _db().table("users").insert(
            {
                "username": username,
                "password_hash": password_hash,
                "password_salt": salt,
                "birth_date": birth_date.isoformat() if birth_date else None,
            }
        ).execute()
        return True, "회원가입이 완료됐습니다."
    except APIError as e:
        if getattr(e, "code", "") == "23505":  # unique_violation
            return False, "이미 사용 중인 아이디입니다."
        return False, "회원가입 중 오류가 발생했습니다. 잠시 후 다시 시도해주세요."


def verify_user(username: str, password: str) -> bool:
    username = username.strip()
    res = (
        _db()
        .table("users")
        .select("password_hash,password_salt")
        .eq("username", username)
        .limit(1)
        .execute()
    )
    if not res.data:
        return False
    row = res.data[0]
    try:
        _, candidate = _hash_password(password, bytes.fromhex(row["password_salt"]))
    except Exception:
        return False
    return secrets.compare_digest(candidate, row["password_hash"])


def get_user_id(username: str) -> int | None:
    username = username.strip()
    if username in _user_id_cache:
        return _user_id_cache[username]
    res = _db().table("users").select("id").eq("username", username).limit(1).execute()
    if not res.data:
        return None
    _user_id_cache[username] = int(res.data[0]["id"])
    return _user_id_cache[username]


# ── 로그인 세션 ─────────────────────────────────────────────
def create_login_session(username: str) -> str | None:
    """로그인 성공 시 브라우저 쿠키에 저장할 무작위 토큰을 만든다."""
    user_id = get_user_id(username)
    if user_id is None:
        return None
    raw_token = secrets.token_urlsafe(48)
    _db().table("auth_sessions").insert(
        {"user_id": user_id, "token_hash": _sha256(raw_token)}
    ).execute()
    return raw_token


def get_username_by_session(session_token: str) -> str | None:
    """브라우저 세션 토큰으로 사용자를 복원한다. (30일 지나면 만료)"""
    token = str(session_token or "").strip()
    if not token:
        return None
    token_hash = _sha256(token)
    res = (
        _db()
        .table("auth_sessions")
        .select("created_at,users(username)")
        .eq("token_hash", token_hash)
        .limit(1)
        .execute()
    )
    if not res.data:
        return None
    row = res.data[0]
    try:
        created = datetime.fromisoformat(str(row["created_at"]).replace("Z", "+00:00"))
        if datetime.now(timezone.utc) - created > SESSION_MAX_AGE:
            _db().table("auth_sessions").delete().eq("token_hash", token_hash).execute()
            return None
    except ValueError:
        pass
    user = row.get("users") or {}
    username = user.get("username")
    if not username:
        return None
    _db().table("auth_sessions").update({"last_seen_at": _now_iso()}).eq(
        "token_hash", token_hash
    ).execute()
    return str(username)


def delete_login_session(session_token: str | None) -> None:
    token = str(session_token or "").strip()
    if not token:
        return
    _db().table("auth_sessions").delete().eq("token_hash", _sha256(token)).execute()


# ── 진단 기록 ───────────────────────────────────────────────
def save_diagnosis_record(
    username: str,
    *,
    score: float,
    pass_count: int,
    warn_count: int,
    fail_count: int,
    checklist_done: int,
    checklist_total: int,
    file_count: int,
    market_keywords: list[str] | None = None,
    diagnosis_payload: dict[str, Any] | None = None,
) -> int | None:
    user_id = get_user_id(username)
    if user_id is None:
        return None
    res = (
        _db()
        .table("diagnosis_records")
        .insert(
            {
                "user_id": user_id,
                "score": round(float(score), 1),
                "pass_count": int(pass_count),
                "warn_count": int(warn_count),
                "fail_count": int(fail_count),
                "checklist_done": int(checklist_done),
                "checklist_total": int(checklist_total),
                "file_count": int(file_count),
                "market_keywords": market_keywords or [],
                "diagnosis_json": diagnosis_payload or {},
            }
        )
        .execute()
    )
    return int(res.data[0]["id"]) if res.data else None


def load_user_diagnosis_history(username: str, limit: int = 50) -> list[dict[str, Any]]:
    user_id = get_user_id(username)
    if user_id is None:
        return []
    limit = max(1, min(int(limit), 100))
    res = (
        _db()
        .table("diagnosis_records")
        .select(
            "id,created_at,score,pass_count,warn_count,fail_count,"
            "checklist_done,checklist_total,file_count,market_keywords,diagnosis_json"
        )
        .eq("user_id", user_id)
        .order("id", desc=False)
        .limit(limit)
        .execute()
    )
    return [
        {
            "id": r["id"],
            "timestamp": _to_kst_text(r["created_at"]),
            "score": r["score"],
            "pass": r["pass_count"],
            "warn": r["warn_count"],
            "fail": r["fail_count"],
            "checklist": f"{r['checklist_done']}/{r['checklist_total']}",
            "file_count": r["file_count"],
            "market_keywords": r.get("market_keywords") or [],
            "diagnosis": r.get("diagnosis_json") or {},
        }
        for r in (res.data or [])
    ]


# ── 리뷰 ────────────────────────────────────────────────────
def save_review(
    username: str,
    diagnosis_record_id: int,
    *,
    overall_rating: int,
    usefulness_rating: int,
    accuracy_rating: int,
    issue_tags: list[str] | None = None,
    comment: str = "",
    visibility: str = "public",
) -> int | None:
    user_id = get_user_id(username)
    if user_id is None:
        return None

    payload = {
        "overall_rating": max(1, min(5, int(overall_rating))),
        "usefulness_rating": max(1, min(5, int(usefulness_rating))),
        "accuracy_rating": max(1, min(5, int(accuracy_rating))),
        "issue_tags": issue_tags or [],
        "comment": str(comment or "").strip()[:3000],
        "visibility": visibility if visibility in {"public", "developer"} else "public",
        "created_at": _now_iso(),
    }
    record_id = int(diagnosis_record_id)

    # 본인의 진단 기록에만 리뷰할 수 있도록 먼저 소유권 확인
    owned = (
        _db()
        .table("diagnosis_records")
        .select("id")
        .eq("id", record_id)
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    if not owned.data:
        return None

    # 한 진단에 한 리뷰만 남기고, 다시 작성하면 업데이트한다.
    res = (
        _db()
        .table("reviews")
        .upsert(
            {**payload, "diagnosis_record_id": record_id, "user_id": user_id},
            on_conflict="diagnosis_record_id,user_id",
        )
        .execute()
    )
    return int(res.data[0]["id"]) if res.data else None


def _review_row_to_dict(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "record_id": row["diagnosis_record_id"],
        "username": (row.get("users") or {}).get("username", "사용자"),
        "timestamp": _to_kst_text(row["created_at"]),
        "overall_rating": row["overall_rating"],
        "usefulness_rating": row["usefulness_rating"],
        "accuracy_rating": row["accuracy_rating"],
        "issue_tags": row.get("issue_tags") or [],
        "comment": row["comment"],
        "visibility": row["visibility"],
    }


def _review_query():
    return _db().table("reviews").select("*,users(username)")


def load_reviews_for_record(diagnosis_record_id: int, include_developer_only: bool = True) -> list[dict[str, Any]]:
    q = _review_query().eq("diagnosis_record_id", int(diagnosis_record_id))
    if not include_developer_only:
        q = q.eq("visibility", "public")
    res = q.order("id", desc=True).execute()
    return [_review_row_to_dict(r) for r in (res.data or [])]


def load_public_reviews(limit: int = 30) -> list[dict[str, Any]]:
    res = (
        _review_query()
        .eq("visibility", "public")
        .order("id", desc=True)
        .limit(max(1, min(int(limit), 100)))
        .execute()
    )
    return [_review_row_to_dict(r) for r in (res.data or [])]


def load_all_reviews(limit: int = 100) -> list[dict[str, Any]]:
    res = _review_query().order("id", desc=True).limit(max(1, min(int(limit), 200))).execute()
    return [_review_row_to_dict(r) for r in (res.data or [])]
