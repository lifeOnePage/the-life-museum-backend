"""외부 링크 임베드 가능 여부 검사.

편집 화면의 추모 앨범 "사용자 지정 탭"이 링크를 '페이지 안에서 보기'(iframe)로 열 수
있는지 미리 알려주기 위한 엔드포인트. 브라우저는 X-Frame-Options / CSP 차단을
스크립트로 감지할 수 없어 서버가 응답 헤더를 대신 읽는다.

판정 규칙 (헤더만 보고 본문은 버린다):
- CSP `frame-ancestors` 가 있으면 우선: 'none' → 차단, '*'/https:/우리 도메인 포함 → 허용,
  그 외 → 차단
- 없으면 X-Frame-Options: DENY / SAMEORIGIN / ALLOW-FROM → 차단
- 둘 다 없으면 허용
- 접속 실패·4xx/5xx 는 판단 불가(None) — 프론트는 새 창 열기를 권한다
"""

from __future__ import annotations

import asyncio
import ipaddress
import logging
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Depends, Query, Request

from app.api.deps import get_current_user
from app.config import settings
from app.core.exceptions import BadRequestException
from app.models.user import User
from app.schemas.common import ApiResponse, success_response

router = APIRouter()
logger = logging.getLogger(__name__)

_TIMEOUT = httpx.Timeout(8.0, connect=4.0)
_MAX_REDIRECTS = 5
_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0 Safari/537.36 TheLifeMuseum-LinkCheck/1.0"
)


def normalize_url(raw: str) -> str:
    """프로토콜이 없으면 https:// 를 붙인다 (프론트 저장 규칙과 동일)."""
    url = (raw or "").strip()
    if not url:
        return ""
    if "://" not in url:
        url = "https://" + url
    return url


def _our_hosts() -> set[str]:
    hosts = set()
    for origin in settings.CORS_ORIGINS:
        host = urlparse(origin).hostname
        if host:
            hosts.add(host.lower())
    return hosts


def _source_matches_host(source: str, host: str) -> bool:
    """CSP host-source(예: https://*.example.com, example.com) 가 host 를 허용하는지."""
    s = source.strip().lower()
    if s in ("*", "https:", "http:"):
        return True
    if "://" in s:
        s = s.split("://", 1)[1]
    s = s.split("/", 1)[0].split(":", 1)[0]
    if s.startswith("*."):
        return host == s[2:] or host.endswith("." + s[2:])
    return host == s


def analyze_frame_headers(headers: httpx.Headers | dict, final_url: str) -> tuple[bool, str | None]:
    """(embeddable, reason). 헤더 기준으로 우리 도메인(CORS_ORIGINS)이 프레임할 수 있는지."""
    get = headers.get if hasattr(headers, "get") else dict(headers).get
    csp = (get("content-security-policy") or "").strip()
    xfo = (get("x-frame-options") or "").strip().lower()
    ours = _our_hosts()
    final_host = (urlparse(final_url).hostname or "").lower()

    # frame-ancestors 가 있으면 XFO 보다 우선. (CSP 헤더가 여러 개면 httpx가 ", " 로 잇는다 →
    # 콤마도 지시어 구분자로 취급. host-source 에는 콤마가 올 수 없다)
    for directive in csp.replace(",", ";").split(";"):
        parts = directive.strip().split()
        if parts and parts[0].lower() == "frame-ancestors":
            sources = parts[1:]
            if not sources or any(s.strip("'").lower() == "none" for s in sources):
                return False, "csp frame-ancestors 'none'"
            for s in sources:
                token = s.strip("'").lower()
                if token == "self":
                    if final_host in ours:
                        return True, None
                    continue
                if any(_source_matches_host(s, h) for h in ours):
                    return True, None
            return False, f"csp frame-ancestors {' '.join(sources)}"

    if xfo:
        if xfo.startswith("sameorigin") and final_host in ours:
            return True, None
        return False, f"x-frame-options: {xfo.upper()}"

    return True, None


async def _is_public_host(host: str) -> bool:
    """사설/루프백/링크로컬 주소로 해석되는 호스트는 거부 (SSRF 가드)."""
    try:
        infos = await asyncio.get_running_loop().getaddrinfo(host, None)
    except OSError:
        return False
    addrs = {info[4][0] for info in infos}
    if not addrs:
        return False
    for addr in addrs:
        try:
            ip = ipaddress.ip_address(addr)
        except ValueError:
            return False
        if not ip.is_global:
            return False
    return True


@router.get("/embed-check", response_model=ApiResponse)
async def embed_check(
    request: Request,
    url: str = Query(..., max_length=2048, description="검사할 외부 링크 (프로토콜 생략 가능)"),
    current_user: User = Depends(get_current_user),
):
    target = normalize_url(url)
    parsed = urlparse(target)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise BadRequestException("올바른 링크 주소가 아닙니다")

    if not await _is_public_host(parsed.hostname):
        return success_response(
            data={"embeddable": None, "reason": "unreachable_host", "finalUrl": target}
        )

    client: httpx.AsyncClient = request.app.state.http_client
    # 리다이렉트는 직접 따라가며 hop 마다 호스트를 다시 검사한다 — 공개 URL이 사설/내부
    # 주소로 302 하는 SSRF 우회를 막기 위해 (공유 클라이언트의 follow_redirects 는 쓰지 않음)
    current = target
    try:
        for _hop in range(_MAX_REDIRECTS + 1):
            resp = await client.send(
                client.build_request(
                    "GET",
                    current,
                    headers={"User-Agent": _UA, "Accept": "text/html,*/*;q=0.8"},
                    timeout=_TIMEOUT,
                ),
                stream=True,
                follow_redirects=False,
            )
            try:
                status = resp.status_code
                headers = resp.headers
                final_url = str(resp.url)
                location = resp.headers.get("location")
            finally:
                await resp.aclose()

            if status in (301, 302, 303, 307, 308) and location:
                next_url = str(httpx.URL(current).join(location))
                next_parsed = urlparse(next_url)
                if next_parsed.scheme not in ("http", "https") or not next_parsed.hostname:
                    return success_response(
                        data={"embeddable": None, "reason": "unreachable_host", "finalUrl": current}
                    )
                if not await _is_public_host(next_parsed.hostname):
                    return success_response(
                        data={"embeddable": None, "reason": "unreachable_host", "finalUrl": current}
                    )
                current = next_url
                continue
            break
        else:
            return success_response(
                data={"embeddable": None, "reason": "too_many_redirects", "finalUrl": current}
            )
    except httpx.HTTPError as e:
        logger.info("embed_check fetch failed for %s: %s", target[:120], e)
        return success_response(
            data={"embeddable": None, "reason": "fetch_failed", "finalUrl": target}
        )

    if status >= 400:
        return success_response(
            data={
                "embeddable": None,
                "reason": f"http_{status}",
                "finalUrl": final_url,
                "status": status,
            }
        )

    embeddable, reason = analyze_frame_headers(headers, final_url)
    return success_response(
        data={
            "embeddable": embeddable,
            "reason": reason,
            "finalUrl": final_url,
            "status": status,
        }
    )
