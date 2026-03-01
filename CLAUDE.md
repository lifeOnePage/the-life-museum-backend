# TLM Backend (tlm_be_py)

FastAPI + SQLAlchemy(asyncpg) + Cloudflare R2 기반의 The Life Museum 백엔드.

---

## 디렉토리 구조

```
app/
├── api/v1/          # 라우터 (record.py, library.py, auth.py, users.py, scraper.py)
├── models/          # SQLAlchemy ORM 모델
├── schemas/         # Pydantic 요청/응답 스키마
├── services/        # 비즈니스 로직 (record, storage, openai, replicate, ...)
├── core/            # security, exceptions
├── config.py        # 환경변수 (pydantic-settings)
├── database.py      # AsyncSession 팩토리
└── main.py          # FastAPI 앱 진입점
```

---

## 인증 방식

`app/api/deps.py`의 `get_current_user` 의존성은 두 가지 방법을 모두 지원한다.

| 방법 | 헤더 | 비고 |
|------|------|------|
| 개발 우회 | `X-Dev-Key: <DEV_AUTH_KEY>` | DB 첫 번째 유저를 리턴 |
| 프로덕션 | `Authorization: Bearer <JWT>` | access 타입 토큰 검증 |

프론트엔드는 현재 대부분의 요청에 `X-Dev-Key: tlm2026` 사용.

---

## 환경변수 (`.env`)

```
DATABASE_URL
SECRET_KEY
GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET
KAKAO_CLIENT_ID / KAKAO_CLIENT_SECRET
RESEND_API_KEY
OPENAI_API_KEY
REPLICATE_API_TOKEN       # Replicate AI 영상 생성
R2_ACCOUNT_ID / R2_ACCESS_KEY_ID / R2_SECRET_ACCESS_KEY
R2_BUCKET_NAME / R2_PUBLIC_URL
DEV_AUTH_KEY              # X-Dev-Key 우회용 (개발 환경)
```

---

## 주요 서비스

### `services/storage.py` — R2StorageService

```python
url = await storage.upload_file(file_bytes, content_type, extension)
# → f"{R2_PUBLIC_URL}/covers/{uuid}.{extension}"
```

R2 저장 경로 규칙: `covers/{uuid}.{ext}`
- 이미지 업로드: `.jpg`, `.png` 등
- AI 생성 영상: `.mp4`
- `getMediaType` (프론트)은 확장자로 타입을 감지하므로 경로 규칙 유지 필수

### `services/openai.py` — OpenAIService

`generate_story(prompt, album_title, album_subtitle)` → str

### `services/replicate.py` — ReplicateService

Replicate REST API를 `httpx.AsyncClient`로 직접 호출 (SDK 불필요).

```python
video_bytes = await replicate.generate_video(prompt, reference_image_url)
```

| 항목 | 값 |
|------|----|
| 모델 | `minimax/video-01` |
| 인풋 | `prompt` (필수), `first_frame_image` (선택, URL) |
| 폴링 | 2초 간격 × 최대 90회 (3분) |
| 타임아웃 | `TimeoutError` raise → 엔드포인트에서 500 반환 |
| 부분 실패 | `asyncio.gather(return_exceptions=True)` — 1개 이상 성공 시 OK |

---

## API 엔드포인트 — Record (`/api/v1/record`)

| 메서드 | 경로 | 설명 |
|--------|------|------|
| POST | `/` | 앨범 생성 |
| GET | `/{id}` | 앨범 상세 (미디어 스크래핑 포함) |
| PATCH | `/{id}` | 앨범 메타 수정 |
| DELETE | `/{id}` | 앨범 삭제 |
| GET | `/{id}/lifestory` | 라이프스토리 조회 |
| POST | `/{id}/lifestory/create` | AI 스토리 생성 (OpenAI) |
| PUT | `/{id}/lifestory` | 라이프스토리 저장 |
| PUT | `/{id}/timeline` | 타임라인 저장 |
| POST | `/{id}/cover/temp` | 파일 업로드 → R2 → DB 저장 |
| POST | `/{id}/cover/generate` | **AI 영상 생성** (Replicate, 3개 병렬) |
| PUT | `/{id}/cover/url` | **기존 R2 URL을 cover로 DB 저장** |

### `POST /{id}/cover/generate`

- Content-Type: `multipart/form-data`
- 필드: `prompt` (string), `reference_image` (file, 선택)
- 참고 이미지가 있으면 R2에 먼저 업로드 후 URL을 Replicate에 전달
- `asyncio.gather` 3개 병렬 생성 후 성공한 URL만 반환

```json
{ "ok": true, "data": { "videos": ["https://...mp4", "https://...mp4"] } }
```

### `PUT /{id}/cover/url`

```json
// Request body
{ "url": "https://pub-xxx.r2.dev/covers/uuid.mp4" }
// Response
{ "ok": true, "data": { "url": "https://..." } }
```

---

## 스키마 요약 (`schemas/record.py`)

| 클래스 | 용도 |
|--------|------|
| `CoverImageResponse` | `{ url }` — cover 저장 결과 |
| `CoverGenerateResponse` | `{ videos: list[str] }` — AI 생성 URL 목록 |
| `CoverUrlRequest` | `{ url: str }` — URL 직접 저장 요청 |

---

## 주의사항

- `services/replicate.py`는 동기 boto3(R2)와 달리 완전 비동기(`httpx.AsyncClient`)
- 3개 병렬 생성은 각 요청이 최대 3분이므로 FastAPI 타임아웃 설정 확인 필요
- Replicate `output`은 모델에 따라 `list[str]` 또는 `str`일 수 있음 — 두 케이스 모두 처리됨
