"""OGQ 대회용 Market API 연동 모듈.

현재 기준 API 계약은 사용자가 제공한 정상 작동 예제
`ogq_official_asset_explorer.html`을 따릅니다.

- Base URL: https://4th-ai-ogq.competition.ogq.me
- 검색: GET /v1/assets
- 상세: GET /v1/assets/{assetId}
- 인증 헤더: X-OGQ-API-KEY
- 검색 필터: query / type / ordering / page / pageSize
- 태그: 상세 응답의 asset.tags

주의:
- API 키를 코드에 넣지 않습니다. Streamlit Secrets에서 전달받습니다.
- 다운로드 엔드포인트는 이 모듈에서 사용하지 않습니다.
"""
from __future__ import annotations

from collections.abc import Iterable
from typing import Any

import requests

DEFAULT_BASE_URL = "https://4th-ai-ogq.competition.ogq.me"
DEFAULT_PAGE_SIZE = 8
MAX_PAGE_SIZE = 100
DEFAULT_ORDERING = "POPULAR"
DEFAULT_ASSET_TYPE = "STICKER"


class OGQAPIError(RuntimeError):
    """OGQ API 요청 또는 응답 처리 실패."""


def _clean_base_url(base_url: str | None) -> str:
    """API 기본 주소를 정리한다.

    실수로 swagger-ui/index.html이나 /v1/assets를 넣어도
    검색 함수가 잘못된 URL을 만들지 않도록 방어적으로 정리한다.
    """
    base = (base_url or DEFAULT_BASE_URL).strip().rstrip("/")

    bad_suffixes = (
        "/swagger-ui/index.html",
        "/v1/assets",
        "/v1/stickers",
    )
    for suffix in bad_suffixes:
        if base.endswith(suffix):
            base = base[: -len(suffix)].rstrip("/")
            break

    if not base:
        base = DEFAULT_BASE_URL

    return base


def _request_json(
    *,
    api_key: str,
    url: str,
    params: dict[str, Any] | None = None,
    timeout: int = 12,
) -> dict[str, Any]:
    """OGQ API를 호출하고 JSON 객체를 반환한다."""
    api_key = (api_key or "").strip()
    if not api_key:
        raise OGQAPIError("OGQ API 키가 설정되지 않았습니다.")

    headers = {
        "X-OGQ-API-KEY": api_key,
        "Accept": "application/json",
    }

    try:
        response = requests.get(
            url,
            params=params or {},
            headers=headers,
            timeout=timeout,
        )
    except requests.RequestException as exc:
        raise OGQAPIError(f"OGQ API 요청에 실패했습니다: {exc}") from exc

    if not response.ok:
        # 응답 본문을 버리지 않고 표시해 401/403/404 원인을 쉽게 확인할 수 있게 한다.
        try:
            body = response.json()
        except ValueError:
            body = response.text.strip()

        if isinstance(body, dict):
            code = body.get("code") or body.get("errorCode")
            message = body.get("message") or body.get("error") or body.get("detail")
            detail = f"code={code}, message={message}" if (code or message) else str(body)
        else:
            detail = body or response.reason

        raise OGQAPIError(
            f"OGQ API {response.status_code} 오류: {detail}"
        )

    try:
        data = response.json()
    except ValueError as exc:
        raise OGQAPIError("OGQ API 응답을 JSON으로 읽지 못했습니다.") from exc

    if not isinstance(data, dict):
        raise OGQAPIError("OGQ API 응답 형식이 예상과 다릅니다.")

    return data


def search_assets(
    api_key: str,
    query: str = "",
    *,
    page: int = 0,
    page_size: int = DEFAULT_PAGE_SIZE,
    ordering: str = DEFAULT_ORDERING,
    asset_type: str = DEFAULT_ASSET_TYPE,
    base_url: str = DEFAULT_BASE_URL,
    timeout: int = 12,
) -> dict[str, Any]:
    """OGQ 대회 API에서 자산을 검색한다.

    정상 작동 예제의 요청 형태:
        GET /v1/assets
        X-OGQ-API-KEY: <API KEY>
        ?query=...&type=STICKER&ordering=POPULAR&page=0&pageSize=8
    """
    base = _clean_base_url(base_url)
    url = f"{base}/v1/assets"

    try:
        safe_page = max(0, int(page))
    except (TypeError, ValueError):
        safe_page = 0

    try:
        safe_page_size = max(1, min(int(page_size), MAX_PAGE_SIZE))
    except (TypeError, ValueError):
        safe_page_size = DEFAULT_PAGE_SIZE

    params: dict[str, Any] = {
        "page": safe_page,
        "pageSize": safe_page_size,
        "ordering": (ordering or DEFAULT_ORDERING).strip() or DEFAULT_ORDERING,
        "type": (asset_type or DEFAULT_ASSET_TYPE).strip() or DEFAULT_ASSET_TYPE,
    }

    cleaned_query = " ".join(str(query or "").split())
    if cleaned_query:
        params["query"] = cleaned_query

    return _request_json(
        api_key=api_key,
        url=url,
        params=params,
        timeout=timeout,
    )


def get_asset_detail(
    api_key: str,
    asset_id: str,
    *,
    base_url: str = DEFAULT_BASE_URL,
    timeout: int = 12,
) -> dict[str, Any]:
    """OGQ 자산 상세 정보를 가져온다.

    상세 응답의 `asset.tags`를 통해 태그를 읽을 수 있다.
    """
    asset_id = str(asset_id or "").strip()
    if not asset_id:
        raise OGQAPIError("assetId가 없어 상세 정보를 요청할 수 없습니다.")

    base = _clean_base_url(base_url)
    url = f"{base}/v1/assets/{asset_id}"

    return _request_json(
        api_key=api_key,
        url=url,
        timeout=timeout,
    )


def _creator_name(asset: dict[str, Any]) -> str:
    creator = asset.get("creator")
    if isinstance(creator, dict):
        return str(
            creator.get("nickname")
            or creator.get("name")
            or "알 수 없음"
        )
    return "알 수 없음"


def _extract_tags(detail_payload: dict[str, Any]) -> list[str]:
    """상세 응답에서 태그 목록을 안전하게 추출한다."""
    asset = detail_payload.get("asset")
    if not isinstance(asset, dict):
        asset = detail_payload

    tags = asset.get("tags", [])
    if not isinstance(tags, list):
        return []

    result: list[str] = []
    for tag in tags:
        if isinstance(tag, dict):
            value = tag.get("name") or tag.get("tag") or tag.get("value")
        else:
            value = tag
        if value is not None:
            text_value = str(value).strip().lstrip("#")
            if text_value and text_value not in result:
                result.append(text_value)
    return result


def parse_asset_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """검색 응답의 `elements`를 Sticker Doctor용 공통 구조로 변환한다."""
    elements = payload.get("elements", [])
    if not isinstance(elements, list):
        return []

    parsed: list[dict[str, Any]] = []

    for asset in elements:
        if not isinstance(asset, dict):
            continue

        asset_type = str(asset.get("type") or "").upper()
        if asset_type and asset_type != DEFAULT_ASSET_TYPE:
            continue

        parsed.append(
            {
                "content_id": str(asset.get("assetId") or ""),
                "asset_id": str(asset.get("assetId") or ""),
                "title": str(asset.get("title") or "제목 없음"),
                "description": str(asset.get("description") or ""),
                "main_image_url": str(asset.get("thumbnailUrl") or asset.get("imageUrl") or ""),
                "thumbnail_url": str(asset.get("thumbnailUrl") or ""),
                "tab_image_url": "",
                "animated": bool(asset.get("animated", False)),
                "creator_name": _creator_name(asset),
                "creator": asset.get("creator") if isinstance(asset.get("creator"), dict) else {},
                "published_at": str(asset.get("publishedAt") or ""),
                "matched_keyword": "",
                "tags": [],
                "images": [],
                "raw": asset,
            }
        )

    return parsed


# 기존 통합본과의 호환성을 위해 이름을 유지한다.
def parse_sticker_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return parse_asset_items(payload)


def search_stickers(
    api_key: str,
    keyword: str = "",
    page: int = 0,
    page_size: int = DEFAULT_PAGE_SIZE,
    user_id: str | None = None,
    base_url: str = DEFAULT_BASE_URL,
    timeout: int = 12,
) -> dict[str, Any]:
    """기존 코드 호환용 래퍼.

    주의: `user_id`는 대회용 /v1/assets API 요청에는 사용하지 않는다.
    """
    del user_id
    return search_assets(
        api_key,
        query=keyword,
        page=page,
        page_size=page_size,
        base_url=base_url,
        timeout=timeout,
    )


def search_by_keywords(
    api_key: str,
    keywords: Iterable[str],
    *,
    max_keywords: int = 5,
    per_keyword: int = DEFAULT_PAGE_SIZE,
    max_results: int = 12,
    max_detail_requests: int = 8,
    base_url: str = DEFAULT_BASE_URL,
    user_id: str | None = None,
    include_details: bool = True,
) -> list[dict[str, Any]]:
    """여러 키워드를 검색해 중복을 제거한다.

    검색 결과를 합친 뒤 상위 `max_detail_requests`개만 상세조회한다.
    상세조회에서 태그/이미지 목록을 가져오므로 API 호출량을 제한할 수 있다.

    `user_id`는 이전 코드와의 호환성을 위해 인자로 남겨두지만 실제 요청에는 사용하지 않는다.
    """
    del user_id

    normalized: list[str] = []
    seen_keywords: set[str] = set()

    for raw in keywords:
        keyword = " ".join(str(raw or "").strip().split())
        if not keyword:
            continue
        key = keyword.casefold()
        if key in seen_keywords:
            continue
        seen_keywords.add(key)
        normalized.append(keyword)
        if len(normalized) >= max(1, int(max_keywords)):
            break

    if not normalized:
        normalized = [""]

    merged: dict[str, dict[str, Any]] = {}

    for keyword in normalized:
        payload = search_assets(
            api_key,
            query=keyword,
            page=0,
            page_size=per_keyword,
            ordering=DEFAULT_ORDERING,
            asset_type=DEFAULT_ASSET_TYPE,
            base_url=base_url,
        )

        for item in parse_asset_items(payload):
            item["matched_keyword"] = keyword
            key = item.get("asset_id") or item.get("content_id")
            if not key:
                key = f"{item.get('title', '')}::{item.get('main_image_url', '')}"
            if key not in merged:
                merged[key] = item
            else:
                # 여러 검색어에 동시에 걸린 콘텐츠는 검색어를 누적해 AI가 참고할 수 있게 한다.
                existing = merged[key]
                previous = str(existing.get("matched_keyword") or "").strip()
                if keyword and keyword not in previous.split(", "):
                    existing["matched_keyword"] = ", ".join(
                        [v for v in (previous, keyword) if v]
                    )

    results = list(merged.values())
    if max_results > 0:
        results = results[: int(max_results)]

    if include_details:
        detail_limit = max(0, int(max_detail_requests))
        for item in results[:detail_limit]:
            asset_id = item.get("asset_id") or item.get("content_id")
            if not asset_id:
                continue

            try:
                detail = get_asset_detail(
                    api_key,
                    asset_id,
                    base_url=base_url,
                )
            except OGQAPIError:
                # 상세조회 실패 하나 때문에 검색 결과 전체를 죽이지 않는다.
                item["detail_error"] = True
                continue

            asset = detail.get("asset")
            if isinstance(asset, dict):
                item["title"] = str(asset.get("title") or item.get("title") or "제목 없음")
                item["description"] = str(asset.get("description") or item.get("description") or "")
                item["published_at"] = str(asset.get("publishedAt") or item.get("published_at") or "")
                item["creator_name"] = _creator_name(asset)
                item["tags"] = _extract_tags(detail)
                item["animated"] = bool(asset.get("animated", item.get("animated", False)))

            images = detail.get("images")
            if isinstance(images, list):
                item["images"] = images

            item["detail"] = detail

    return results


def search_market_with_tags(
    api_key: str,
    user_tags: Iterable[str],
    feelings: str = "",
    *,
    max_keywords: int = 5,
    per_keyword: int = DEFAULT_PAGE_SIZE,
    max_results: int = 12,
    max_detail_requests: int = 8,
    base_url: str = DEFAULT_BASE_URL,
) -> list[dict[str, Any]]:
    """느낌 + 태그를 합쳐 시장 스티커를 검색하는 편의 함수."""
    keywords: list[str] = []

    for part in str(feelings or "").replace("\n", ",").split(","):
        value = " ".join(part.strip().split())
        if value:
            keywords.append(value)

    for tag in user_tags:
        value = str(tag or "").strip().lstrip("#")
        if value:
            keywords.append(value)

    return search_by_keywords(
        api_key,
        keywords,
        max_keywords=max_keywords,
        per_keyword=per_keyword,
        max_results=max_results,
        max_detail_requests=max_detail_requests,
        base_url=base_url,
        include_details=True,
    )


__all__ = [
    "DEFAULT_BASE_URL",
    "OGQAPIError",
    "search_assets",
    "search_stickers",
    "get_asset_detail",
    "parse_asset_items",
    "parse_sticker_items",
    "search_by_keywords",
    "search_market_with_tags",
]
