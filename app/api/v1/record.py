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



Copy

COVER_STYLE_PROMPTS: dict[str, dict] = {
    "minimal": {
        "prompt": (
            "Square vinyl album sleeve. Premium hand-drawn illustration. Minimal modern.\n\n"
 
            "STEP 1 — READ THE REFERENCE:\n"
            "Identify exactly what the reference image contains: the subject, their pose and position within the frame, "
            "the number of figures, the spatial setting, and the lighting condition "
            "(bright interior, outdoor daylight, night scene, dramatic backlight). "
            "The lighting condition determines how the background is treated in Step 2. "
            "This content must appear in the output without substitution or addition.\n\n"
 
            "STEP 2 — RENDERING HIERARCHY (most critical rule):\n"
            "The illustration uses four zones, each requiring a different combination of four techniques: "
            "solid ink fill, hatching, clean linework, and ink wash. "
            "These four techniques must be mixed dynamically — no single technique should dominate the entire image. "
            "Applying uniform hatching everywhere is a failure.\n\n"
 
            "THE FOUR TECHNIQUES — use each where it is most appropriate:\n\n"
            "· SOLID INK FILL (spot black): Used for the darkest masses — hair, deep cast shadows, black clothing. "
            "Fill these areas as flat, opaque, solid black with no visible lines inside the mass. "
            "A few flowing directional strokes may ride the edge of the mass to suggest movement or texture, "
            "but the interior must be pure filled black, never hatching.\n\n"
            "· HATCHING / CROSS-HATCHING: Used exclusively for mid-tone gray areas — "
            "skin shadow planes, clothing folds in ambient light, structural mid-tones. "
            "Hatching represents gray, not black. Spacing between lines controls the value. "
            "Never use hatching where solid fill should be.\n\n"
            "· CLEAN LINEWORK: Used for contour edges, silhouette boundaries, facial features, "
            "and structural definition. Line weight varies — thick at major silhouette edges, "
            "medium at form transitions, fine at detail. This is the skeleton of the image.\n\n"
            "· INK WASH: Used for soft atmospheric tones — diffuse shadow on skin, "
            "hazy background atmosphere, environmental depth in wide scenes. "
            "Wash layers are transparent and directional, not covering the paper tooth. "
            "Use wash where hatching lines would feel too mechanical.\n\n"
 
            "ZONE 1 — FULL DETAIL (approx. 5% of image area):\n"
            "Eyes, eyebrows, nose, lips. Combine clean linework for structure with fine hatching for shadow planes. "
            "This is the only zone with maximum rendering density. All other zones must be less rendered.\n\n"
 
            "ZONE 2 — BOLD MASSES (approx. 15% of image area):\n"
            "Hair, deep shadows, dark clothing. Use solid ink fill as the primary technique. "
            "Do not use hatching here — fill solidly. Edge strokes for movement are acceptable.\n\n"
 
            "ZONE 3 — MINIMAL SUGGESTION (approx. 20% of image area):\n"
            "Shoulders, hands, clothing, foreground objects. Use clean linework for structure, "
            "with optional sparse hatching or a single wash layer for form. "
            "3 to 7 marks maximum per area — leave the rest as white paper.\n\n"
 
            "ZONE 4 — BACKGROUND (remaining area, scene-dependent):\n"
            "The background is never rendered at the same density as Zone 1. "
            "Choose treatment based on lighting condition from Step 1:\n\n"
            "· Bright interior or portrait scene: mostly white paper. "
            "1 to 3 structural contour lines only to anchor the figure in space.\n\n"
            "· Environmentally important scene (street, crowd, architecture): "
            "clean contour lines for key structures, light wash for atmosphere, "
            "hatching at half the density of Zone 1. Secondary figures as simplified silhouettes.\n\n"
            "· Night scene or dramatic lighting: solid ink fill and dense wash permitted extensively. "
            "The subject must read as a clear silhouette against the dark background — "
            "figure-ground contrast must remain strong. Background serves the subject, never competes.\n\n"
            "In all cases: background rendering density is always subordinate to the foreground subject.\n\n"
 
            "STEP 3 — LINE WEIGHT:\n"
            "Use three distinct weights deliberately:\n"
            "· Thick anchor lines: outer silhouette, boundaries between solid masses and white areas.\n"
            "· Medium lines: facial features, major form transitions.\n"
            "· Fine lines: detail inside Zone 1 and edge strokes on Zone 2 masses only.\n"
            "Uniform line weight throughout is a failure.\n\n"
 
            "STEP 4 — THE DISCIPLINE OF OMISSION:\n"
            "White paper is an active compositional element, not empty space. "
            "The figure should feel like it is emerging from the paper. "
            "Total unmarked area must exceed total marked area in most scenes.\n\n"
 
            "STEP 5 — COMPOSE FOR THE SLEEVE:\n"
            "Maintain the compositional intent of the reference. "
            "Leave minimum 25% of the square as open space for typography.\n\n"
 
            "STEP 6 — QUALITY:\n"
            "· Achromatic only: pure ink black, mid-gray wash and hatching, paper white — "
            "three values, cleanly separated and never confused\n"
            "· Paper surface: light-tooth cartridge or smooth hot-press — "
            "individual marks and wash edges must remain visible\n"
            "· No color. No text. No watermark. No border. No vignette.\n\n"
 
            "Aesthetic reference: manga spot-black inking technique for dark masses, "
            "the selective linework economy of Kim Jung Gi, "
            "ink wash atmosphere of contemporary Korean pencil illustration (감성 스케치), "
            "editorial restraint of David Downton — "
            "all four techniques used together dynamically, never uniformly.\n\n"
 
            "--ar 1:1 --style raw --stylize 800 --chaos 8"
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
