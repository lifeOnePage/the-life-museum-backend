import logging
import re
import uuid

from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile, File

logger = logging.getLogger(__name__)
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.api.deps import get_current_user
from app.models.user import User
from app.schemas.common import ApiResponse, success_response
from app.schemas.record import (
    RecordCreate,
    RecordUpdate,
    RecordResponse,
    RecordDetailResponse,
    RecordListItem,
    CoverImageInfo,
    LifestorySummary,
    TimelineSummary,
    EventItem,
    QaItem,
    LifestoryDetailResponse,
    CreateStorylinesRequest,
    CreateStorylinesResponse,
    SaveLifestoryRequest,
    SaveTimelineRequest,
    TimelineResponse,
    CoverImageResponse,
    CoverGenerateImageResponse,
    CoverUrlRequest,
    ShareRecordRequest,
)
from app.services.record import RecordService
from app.services.openai import OpenAIService
from app.services.storage import R2StorageService
from app.core.exceptions import ForbiddenException, NotFoundException

router = APIRouter()


@router.post("", response_model=ApiResponse)
async def create_record(
    body: RecordCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = RecordService(db)
    record = await service.create_record(
        user_id=current_user.id,
        title=body.title,
        subtitle=body.subTitle,
        google_photo_url=body.googlePhotoUrl,
        icloud_url=body.icloudUrl,
        mybox_url=body.myboxUrl,
    )
    data = RecordResponse(
        id=record.id,
        title=record.title,
        subtitle=record.subtitle,
        googlePhotoUrl=record.google_photo_url,
        icloudUrl=record.icloud_url,
        myboxUrl=record.mybox_url,
        color=record.color,
        bgColor=record.bg_color,
        keyColor=record.key_color,
        theme=record.theme,
        createdAt=record.created_at,
        updatedAt=record.updated_at,
    )
    return success_response(data=data, code=201, message="Record created")


@router.patch("/{record_id}", response_model=ApiResponse)
async def update_record(
    record_id: uuid.UUID,
    body: RecordUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = RecordService(db)
    record = await service.get_record_by_id(record_id)
    if not record:
        raise NotFoundException("Record not found")

    # 소유자만 수정 가능
    # association 테이블 우선 확인, 없으면 creator_id로 폴백 (테이블 도입 이전 레코드 호환)
    assoc = await service.get_user_association(current_user.id, record_id)
    is_owner = (assoc is not None and assoc.role == "owner") or (
        record.creator_id == current_user.id
    )
    if not is_owner:
        raise ForbiddenException("Only the owner can edit this record")

    # body에서 None이 아닌 필드만 추출하여 업데이트
    field_mapping = {
        "title": "title",
        "subTitle": "subtitle",
        "googlePhotoUrl": "google_photo_url",
        "icloudUrl": "icloud_url",
        "myboxUrl": "mybox_url",
        "color": "color",
        "bgColor": "bg_color",
        "keyColor": "key_color",
        "theme": "theme",
    }
    update_data = {}
    for schema_field, model_field in field_mapping.items():
        value = getattr(body, schema_field, None)
        if value is not None:
            update_data[model_field] = value

    record = await service.update_record(record, update_data)

    data = RecordResponse(
        id=record.id,
        title=record.title,
        subtitle=record.subtitle,
        googlePhotoUrl=record.google_photo_url,
        icloudUrl=record.icloud_url,
        myboxUrl=record.mybox_url,
        color=record.color,
        bgColor=record.bg_color,
        keyColor=record.key_color,
        theme=record.theme,
        createdAt=record.created_at,
        updatedAt=record.updated_at,
    )
    return success_response(data=data)


@router.delete("/{record_id}", response_model=ApiResponse)
async def delete_record(
    record_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = RecordService(db)
    # 권한 확인 및 삭제는 서비스에서 처리 (소유자가 아니면 ForbiddenException)
    await service.delete_record(current_user.id, record_id)
    return success_response(data=None, message="Record deleted")


@router.get("/{record_id}", response_model=ApiResponse)
async def get_record(
    record_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    service = RecordService(db)
    record = await service.get_record_by_id(record_id)
    if not record:
        raise NotFoundException("Record not found")

    # 스크래핑으로 mediaList 구성
    media_list = await service.scrape_media_list(record)

    cover_image = None
    if record.cover_image:
        cover_image = CoverImageInfo(url=record.cover_image.url)

    lifestory = None
    if record.lifestory:
        lifestory = LifestorySummary(
            mood=record.lifestory.mood,
            content=record.lifestory.content,
        )

    timeline = None
    if record.timeline and record.timeline.events:
        timeline = TimelineSummary(
            events=[
                EventItem(
                    title=e.title,
                    timestamp=e.timestamp,
                    description=e.description,
                )
                for e in record.timeline.events
            ]
        )

    data = RecordDetailResponse(
        id=record.id,
        title=record.title,
        subtitle=record.subtitle,
        googlePhotoUrl=record.google_photo_url,
        icloudUrl=record.icloud_url,
        myboxUrl=record.mybox_url,
        color=record.color,
        bgColor=record.bg_color,
        keyColor=record.key_color,
        theme=record.theme,
        coverGenCount=record.cover_gen_count,
        mediaList=media_list,
        coverImage=cover_image,
        lifestory=lifestory,
        timeline=timeline,
        createdAt=record.created_at,
        updatedAt=record.updated_at,
    )
    return success_response(data=data)


@router.get("/{record_id}/lifestory", response_model=ApiResponse)
async def get_lifestory_details(
    record_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    service = RecordService(db)
    lifestory = await service.get_lifestory(record_id)
    if not lifestory:
        raise NotFoundException("Lifestory not found")

    data = LifestoryDetailResponse(
        mood=lifestory.mood,
        qaList=[
            QaItem(question=qa.question, answer=qa.answer)
            for qa in lifestory.qas
        ],
        result=lifestory.content,
    )
    return success_response(data=data)


@router.post("/{record_id}/lifestory/create", response_model=ApiResponse)
async def create_storylines(
    record_id: uuid.UUID,
    body: CreateStorylinesRequest,
    current_user: User = Depends(get_current_user),
):
    if not body.prompt or not body.prompt.strip():
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="내용을 입력해주세요")

    openai_service = OpenAIService()
    result = await openai_service.generate_story(
        prompt=body.prompt,
        album_title=body.albumTitle,
        album_subtitle=body.albumSubtitle,
    )

    data = CreateStorylinesResponse(result=result)
    return success_response(data=data)


@router.put("/{record_id}/lifestory", response_model=ApiResponse)
async def save_lifestory(
    record_id: uuid.UUID,
    body: SaveLifestoryRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = RecordService(db)

    # record 존재 확인
    record = await service.get_record_by_id(record_id)
    if not record:
        raise NotFoundException("Record not found")

    qa_dicts = [qa.model_dump() for qa in body.qaList]
    lifestory = await service.save_lifestory(
        record_id=record_id,
        qa_list=qa_dicts,
        mood=body.mood,
        result_text=body.result,
    )

    data = LifestoryDetailResponse(
        mood=lifestory.mood,
        qaList=[
            QaItem(question=qa.question, answer=qa.answer)
            for qa in lifestory.qas
        ],
        result=lifestory.content,
    )
    return success_response(data=data)


@router.put("/{record_id}/timeline", response_model=ApiResponse)
async def save_timeline(
    record_id: uuid.UUID,
    body: SaveTimelineRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = RecordService(db)

    record = await service.get_record_by_id(record_id)
    if not record:
        raise NotFoundException("Record not found")

    events_data = [e.model_dump() for e in body.events]
    timeline = await service.save_timeline(record_id, events_data)

    data = TimelineResponse(
        events=[
            EventItem(
                title=e.title,
                timestamp=e.timestamp,
                description=e.description,
            )
            for e in timeline.events
        ]
    )
    return success_response(data=data)


@router.post("/{record_id}/cover/temp", response_model=ApiResponse)
async def save_cover_img_temp(
    record_id: uuid.UUID,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = RecordService(db)

    record = await service.get_record_by_id(record_id)
    if not record:
        raise NotFoundException("Record not found")

    # R2에 업로드
    content = await file.read()
    extension = file.filename.rsplit(".", 1)[-1] if file.filename and "." in file.filename else "jpg"
    content_type = file.content_type or "image/jpeg"

    storage = R2StorageService()
    url = await storage.upload_file(content, content_type, extension)

    # DB에 저장
    cover = await service.save_cover_image(record_id, url)

    data = CoverImageResponse(url=cover.url)
    return success_response(data=data, code=201, message="Cover image uploaded")


COVER_STYLE_PROMPTS: dict[str, dict] = {
    "minimal": {
        "prompt": (
            "Square vinyl album sleeve. Premium hand-drawn illustration. Minimal modern.\n\n"
            "STEP 1 — READ THE REFERENCE:\n"
            "Identify exactly what the reference image contains: the subject, how many figures or elements "
            "are present, their arrangement, the spatial setting, the viewpoint and framing. "
            "This reading is mandatory. The output must contain that subject.\n\n"
            "STEP 2 — PRESERVE THE SUBJECT:\n"
            "Whatever is identified in Step 1 must appear in the output without substitution. "
            "A person becomes a drawn person. A scene becomes a drawn scene. An object becomes a drawn object. "
            "Nothing is replaced. Nothing new is added.\n\n"
            "STEP 3 — APPLY DRAWING MEDIUM:\n"
            "The target texture is clean, modern, and graphic — not soft, atmospheric, or charcoal-like.\n"
            "Use pencil or ink pen with deliberate, controlled mark-making:\n\n"
            "· Primary rendering tool: fine graphite pencil (HB–2B range) with precise hatching lines, "
            "OR black ink pen with cross-hatching. Lines are confident and intentional — not smeared, not blended.\n"
            "· Shadow and form: built through hatching density and line direction, not tonal smudging. "
            "Shadows are readable as collections of lines, not as soft gray washes.\n"
            "· Edges: crisp and defined at focal points (face, primary subject). "
            "Edges become looser and more gestural only where the subject fades into negative space.\n"
            "· Hair and texture: rendered with fast, directional line strokes — energetic but controlled. "
            "The direction of each stroke is visible.\n"
            "· Background: pure, clean paper white. No tone wash, no gray field, "
            "no atmospheric rendering behind the subject.\n\n"
            "DO NOT USE: charcoal smudging, blended tonal gradients, heavy atmospheric haze, smoky mid-tones, "
            "or any technique that obscures individual marks. Every mark must remain visible as a mark.\n\n"
            "STEP 4 — COMPOSE FOR THE SLEEVE:\n"
            "Maintain the compositional core from the reference image. "
            "Leave a minimum of 25% of the frame as open, unrendered paper-white for album typography — upper register preferred. "
            "Subject placement feels deliberate, not incidentally cropped.\n\n"
            "STEP 5 — QUALITY STANDARD:\n"
            "· Line quality: each stroke is confident — no hesitation, no overworking\n"
            "· Tonal range: pure white paper at lightest, dense hatching or solid ink at darkest, "
            "with controlled mid-tones built through line spacing only\n"
            "· Paper surface: very light tooth — barely visible grain. "
            "The surface reads as smooth hot-press or slightly textured cartridge paper, not rough watercolor paper\n"
            "· The illustration has the clean, editorial quality of a graphic novel splash page "
            "or a contemporary Korean pencil sketch (감성 스케치) — modern, not classical\n"
            "· No color. No text. No watermark. No decorative border. No vignette.\n\n"
            "Aesthetic reference: the linework precision of Kim Jung Gi, "
            "the clean graphic hatching of contemporary Korean pencil illustration, "
            "the editorial restraint of David Downton — applied to ECM Records and 4AD sleeve format discipline.\n\n"
            "--ar 1:1 --style raw --stylize 800 --chaos 5"
        ),
    },
    "abstract": {
        "prompt": "Square vinyl album sleeve. Abstract art style. (placeholder — coming soon)",
    },
    "animation": {
        "prompt": "Square vinyl album sleeve. Animation style. (placeholder — coming soon)",
    },
}


@router.post("/{record_id}/cover/generate", response_model=ApiResponse)
async def generate_cover_image(
    record_id: uuid.UUID,
    style: str = Form(...),
    reference_image: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_user),
):
    """Generate a cover image using OpenAI gpt-image-1, upload to R2, return URL."""
    style_config = COVER_STYLE_PROMPTS.get(style)
    if not style_config:
        raise HTTPException(
            status_code=400,
            detail=f"지원하지 않는 스타일입니다: {style}",
        )

    service = RecordService(db)
    record = await service.get_record_by_id(record_id)
    if not record:
        raise NotFoundException("Record not found")

    # Check generation limit
    if record.cover_gen_count >= 3:
        raise HTTPException(
            status_code=400,
            detail="생성 횟수가 초과되었습니다 (최대 3회)",
        )

    # Read reference image bytes (required)
    img_content = await reference_image.read()
    if not img_content:
        raise HTTPException(status_code=400, detail="참고 이미지가 비어있습니다")
    reference_image_bytes = img_content

    openai_service = OpenAIService()
    storage = R2StorageService()

    try:
        image_bytes = await openai_service.generate_cover_image(
            prompt=style_config["prompt"],
            reference_image_bytes=reference_image_bytes,
        )
    except Exception as e:
        logger.error("Cover image generation failed: %s: %s", type(e).__name__, e)
        raise HTTPException(status_code=500, detail="이미지 생성에 실패했습니다")

    url = await storage.upload_file(image_bytes, "image/png", "png")

    # Increment generation count
    record.cover_gen_count += 1
    await db.commit()
    await db.refresh(record)

    data = CoverGenerateImageResponse(
        images=[url],
        remainingGenerations=3 - record.cover_gen_count,
    )
    return success_response(data=data, code=201, message="Cover image generated")


@router.put("/{record_id}/cover/url", response_model=ApiResponse)
async def save_cover_url(
    record_id: uuid.UUID,
    body: CoverUrlRequest,
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_user),
):
    """Save an already-uploaded R2 URL as the record's cover image."""
    service = RecordService(db)
    record = await service.get_record_by_id(record_id)
    if not record:
        raise NotFoundException("Record not found")

    cover = await service.save_cover_image(record_id, body.url)
    data = CoverImageResponse(url=cover.url)
    return success_response(data=data)


@router.post("/share", response_model=ApiResponse)
async def add_shared_record(
    body: ShareRecordRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """walk/{id} URL에서 record_id를 추출하여 공유 앨범으로 추가."""
    match = re.search(r"walk/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})", body.url)
    if not match:
        raise HTTPException(status_code=400, detail="유효한 walk URL이 아닙니다")

    record_id = uuid.UUID(match.group(1))
    service = RecordService(db)
    record = await service.share_record(current_user.id, record_id)

    data = RecordListItem(
        id=record.id,
        title=record.title,
        subtitle=record.subtitle,
        coverImage=CoverImageInfo(url=record.cover_image.url) if record.cover_image else None,
        bgColor=record.bg_color,
        color=record.color,
        keyColor=record.key_color,
        theme=record.theme,
        role="shared",
        lifestory=LifestorySummary(
            mood=record.lifestory.mood,
            content=record.lifestory.content,
        ) if record.lifestory else None,
        timeline=TimelineSummary(
            events=[
                EventItem(
                    title=e.title,
                    timestamp=e.timestamp,
                    description=e.description,
                )
                for e in (record.timeline.events if record.timeline and record.timeline.events else [])
            ]
        ) if record.timeline else None,
        createdAt=record.created_at,
        updatedAt=record.updated_at,
    )
    return success_response(data=data, code=201, message="Shared record added")


@router.delete("/{record_id}/share", response_model=ApiResponse)
async def remove_shared_record(
    record_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """공유 앨범 제거 (role='shared' 연관만 삭제)."""
    service = RecordService(db)
    await service.unshare_record(current_user.id, record_id)
    return success_response(data={"ok": True}, message="Shared record removed")
