"""
Gmail OAuth2 Refresh Token 발급 스크립트 (1회 실행)

사전 준비:
  1. Google Cloud Console → 해당 프로젝트 → API 및 서비스 → 사용자 인증 정보
  2. OAuth 2.0 클라이언트 ID의 "승인된 리디렉션 URI"에 아래 주소 추가:
       http://localhost:8080/
  3. .env 파일의 GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET 값 확인

실행:
  python scripts/get_gmail_refresh_token.py
"""

import sys
import urllib.parse
import urllib.request
import json
import http.server
import threading
import webbrowser

# ── 설정 ──────────────────────────────────────────────────────────────────────
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import os

CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
REDIRECT_URI = "http://localhost:8080/"
SCOPES = "https://www.googleapis.com/auth/gmail.send"

if not CLIENT_ID:
    print("Google Cloud Console > API 및 서비스 > 사용자 인증 정보 > OAuth 2.0 클라이언트 ID")
    CLIENT_ID = input("GOOGLE_CLIENT_ID 를 입력하세요: ").strip()
if not CLIENT_SECRET:
    CLIENT_SECRET = input("GOOGLE_CLIENT_SECRET 를 입력하세요: ").strip()

if not CLIENT_ID or not CLIENT_SECRET:
    print("ERROR: Client ID와 Secret이 필요합니다.")
    sys.exit(1)

# ── Step 1. 인증 URL 생성 및 브라우저 열기 ────────────────────────────────────
auth_url = (
    "https://accounts.google.com/o/oauth2/v2/auth?"
    + urllib.parse.urlencode({
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "scope": SCOPES,
        "access_type": "offline",
        "prompt": "consent",           # 반드시 consent: refresh_token 포함 보장
    })
)

print("\n브라우저가 열립니다. metamemories.seoul@gmail.com 계정으로 로그인 후 승인하세요.")
print(f"\n자동으로 열리지 않으면 아래 URL을 직접 열어주세요:\n{auth_url}\n")

# ── Step 2. 로컬 서버로 redirect_uri 수신 ─────────────────────────────────────
auth_code = None

class _Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        global auth_code
        params = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        auth_code = params.get("code", [None])[0]
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"<h2>Done! Go back to the terminal.</h2>")

    def log_message(self, *args):
        pass  # 서버 로그 숨김

server = http.server.HTTPServer(("localhost", 8080), _Handler)
thread = threading.Thread(target=server.handle_request)
thread.start()

webbrowser.open(auth_url)
thread.join(timeout=120)

if not auth_code:
    print("ERROR: 인증 코드를 받지 못했습니다. 120초 내에 승인해 주세요.")
    sys.exit(1)

# ── Step 3. code → refresh_token 교환 ─────────────────────────────────────────
data = urllib.parse.urlencode({
    "code": auth_code,
    "client_id": CLIENT_ID,
    "client_secret": CLIENT_SECRET,
    "redirect_uri": REDIRECT_URI,
    "grant_type": "authorization_code",
}).encode()

req = urllib.request.Request(
    "https://oauth2.googleapis.com/token",
    data=data,
    headers={"Content-Type": "application/x-www-form-urlencoded"},
)

with urllib.request.urlopen(req) as resp:
    token_data = json.loads(resp.read())

refresh_token = token_data.get("refresh_token")
if not refresh_token:
    print("ERROR: refresh_token이 응답에 없습니다.")
    print("       Google Cloud Console에서 'prompt=consent'를 확인하세요.")
    sys.exit(1)

# ── 완료 ──────────────────────────────────────────────────────────────────────
print("\n" + "=" * 60)
print("GMAIL_REFRESH_TOKEN 발급 완료!")
print("=" * 60)
print(f"\n{refresh_token}\n")
print("위 값을 Railway 환경변수 GMAIL_REFRESH_TOKEN 에 추가하세요.")
print("=" * 60)
