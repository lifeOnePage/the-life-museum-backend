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
from app.services.gemini import GeminiService
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
            "Identify exactly what the reference image contains: the subject, their pose and position within the frame, "
            "the number of figures, the spatial setting, and the lighting condition "
            "(bright interior, outdoor daylight, night scene, dramatic backlight). "
            "The lighting condition determines how the background is treated in Step 2. "
            "This content must appear in the output without substitution or addition.\n\n"

            "STEP 2 — RENDERING HIERARCHY (most critical rule):\n"
            "The illustration uses three tonal zones rendered with three completely different techniques. "
            "Never apply the same technique across different zones.\n\n"

            "ZONE 1 — LINEWORK AND PRECISE DETAIL (face, eyes, primary focal point):\n"
            "Clean ink lines and precise hatching only in this zone. Eyes, eyelashes, nose, lips receive focused "
            "linework with controlled shadow hatching. This is the only zone where hatching lines are used to build form.\n\n"

            "ZONE 2 — SOLID BLACK MASSES (hair, deep shadows, dark clothing):\n"
            "Fill these areas as flat, opaque, solid black — completely filled with no visible hatching lines inside "
            "the mass. This is called spot black or beta inking. The edge of the solid black shape may have a few "
            "flowing directional lines indicating hair movement or cloth drape, but the interior of the mass must be "
            "pure filled black, not hatching. Do not use cross-hatching or parallel lines to represent dark areas "
            "— fill them solidly.\n\n"

            "ZONE 3 — HATCHING FOR MID-TONES ONLY (clothing texture, skin shadow, structural mid-tones):\n"
            "Hatching is reserved exclusively for gray mid-tone values. Use parallel or cross-hatching lines with "
            "visible spacing between them. Ink wash is also acceptable here. "
            "This zone must never appear as dark as Zone 2.\n\n"

            "ZONE 4 — WHITE PAPER (skin highlights, background, negative space):\n"
            "Leave completely unmarked — pure paper white. Or, based on lighting condition:\n"
            "· Bright interior or portrait scene: background mostly white, 1 to 3 structural contour lines only.\n"
            "· Environment-important scene: key background structures in clean contour lines, hatching at less than "
            "half the density of Zone 1.\n"
            "· Night or dramatic scene: background may use solid black masses or dense ink to establish atmosphere, "
            "but the primary subject silhouette must remain clearly readable against the background.\n\n"

            "THE CORE RULE: hatching represents gray. Solid black represents black. These must never be confused. "
            "A dark area rendered with tight hatching instead of solid fill is a failure.\n\n"

            "STEP 3 — LINE WEIGHT:\n"
            "Three distinct weights:\n"
            "· Thick anchor lines: outer silhouette, boundaries between solid black masses and white areas.\n"
            "· Medium lines: facial structure, form transitions in Zone 1.\n"
            "· Fine lines: detail inside Zone 1 and directional strokes on the edges of Zone 2 masses only.\n"
            "Uniform line weight throughout = failure.\n\n"

            "STEP 4 — OMISSION:\n"
            "White paper is an active compositional element. The figure should feel like it is emerging from the paper. "
            "Total unmarked area must exceed total marked area in most scenes.\n\n"

            "STEP 5 — COMPOSE FOR THE SLEEVE:\n"
            "Preserve the compositional intent of the reference. "
            "Leave minimum 25% of the square as open space for typography.\n\n"

            "STEP 6 — QUALITY:\n"
            "· Achromatic only: pure ink black, mid-gray hatching, paper white — three values, cleanly separated\n"
            "· Paper: light-tooth cartridge or smooth hot-press — individual marks must remain visible\n"
            "· No color. No text. No watermark. No border. No vignette.\n\n"

            "Aesthetic reference: manga spot-black inking technique for dark masses, "
            "the selective linework economy of Kim Jung Gi, "
            "ink wash atmosphere of contemporary Korean pencil illustration (감성 스케치), "
            "editorial restraint of David Downton — "
            "all four techniques used together dynamically, never uniformly.\n\n"

            "--ar 1:1 --style raw --stylize 800 --chaos 8"
        ),
    },

    "animation": {
        "prompt": (
            "Square vinyl record album cover. Painterly animation-style illustration. Poetic, cinematic, summery.\n\n"

            "STEP 1 — READ THE REFERENCE:\n"
            "Identify the subject, scene setting, number of figures, spatial composition, and lighting condition "
            "from the reference image. Preserve the compositional structure and emotional mood. "
            "Do not reproduce literally — translate into a painted animation frame.\n\n"

            "STEP 2 — OVERALL VISUAL LANGUAGE:\n"
            "The illustration must feel like a single frame from a poetic animated film: part Makoto Shinkai "
            "atmospheric background painting, part watercolor-gouache illustration. The scene should carry the "
            "quiet emotional weight of a summer afternoon remembered — luminous, soft, and slightly bittersweet.\n\n"
            "The image is painterly but readable. Soft but not blurry. Anime-adjacent but not generic anime. "
            "Every element — sky, foliage, figures, ground — is rendered with the same painterly cohesion. "
            "Nothing is photorealistic. Nothing is left in linework alone.\n\n"

            "STEP 3 — FIGURE TREATMENT (critical for real-person references):\n"
            "If the reference contains a real person, do not attempt faithful likeness or photorealistic rendering. "
            "Translate the figure using these rules:\n\n"
            "· Shape language: reduce the person to simplified color masses and silhouette shapes. "
            "Facial features are minimal — eyes suggested, not detailed; "
            "skin rendered as warm color planes, not pored texture.\n"
            "· Form separation: use color temperature contrast (warm skin vs cool shadow) and light edge glow "
            "to define the figure, not outlines.\n"
            "· Clothing: render as broad watercolor washes with 2 to 3 value planes. "
            "Folds are suggested with soft color shifts, not drawn lines.\n"
            "· Hair: a single flowing mass of color, directional brush strokes indicating movement "
            "— not individual strands.\n"
            "· Pose and gesture: preserve from the reference. "
            "The body language carries the emotional meaning; the face does not need to.\n"
            "· Result: the figure should look like it belongs to the painted world around it "
            "— not like a photographed person placed on top of a painting.\n\n"

            "STEP 4 — LIGHT AND ATMOSPHERE:\n"
            "Light is the primary storytelling tool. Identify the lighting condition from the reference and apply:\n\n"
            "· Daylight / summer sun: warm golden or white overhead light, strong cast shadows with soft edges, "
            "light bouncing off pale surfaces (sidewalk, walls), sun flare or bloom where light sources are visible.\n"
            "· Overcast or shade: cool diffuse light, soft shadow gradients, muted saturation in shadows, "
            "vivid saturated mid-tones.\n"
            "· Backlight / contre-jour: figure appears as dark silhouette or softly rim-lit shape against luminous "
            "sky or foliage; halo of warm light around hair and shoulders.\n"
            "· Interior or enclosed space: window light as dominant source, contrast between lit and unlit zones, "
            "atmospheric softness in shadows.\n\n"

            "STEP 5 — ENVIRONMENT RENDERING:\n"
            "· Sky: painted in broad color washes — not gradient fills. "
            "Clouds built from layered gouache strokes with soft top edges and harder bottom edges. "
            "Sky color shifts from warm at horizon to cooler at zenith.\n"
            "· Foliage: not individual leaves — clusters of color shapes in 3 to 4 values of green, "
            "yellow-green, and shadow-green. "
            "Light filtering through leaves creates scattered bright spots and dappled patterns.\n"
            "· Architecture and streets: simplified planes of color with minimal detail. "
            "Structural lines implied rather than drawn. "
            "Shadows fall as cool color washes across warm surfaces.\n"
            "· Ground: textured wash indicating asphalt, cobblestone, or grass "
            "— directional brush strokes following perspective.\n\n"

            "STEP 6 — COLOR PALETTE:\n"
            "Extract the dominant color temperature from the reference image and build a limited palette:\n"
            "· Maximum 5 to 6 dominant hues, desaturated slightly toward pastel or muted tones\n"
            "· Shadow colors are not dark versions of the base color "
            "— they shift toward cooler or complementary hues\n"
            "· Highlight colors push toward warm white or pale yellow, never pure white unless it is a light source\n"
            "· The palette should feel cohesive — every element shares the same atmospheric color bias\n\n"

            "STEP 7 — COMPOSE FOR THE SLEEVE:\n"
            "Maintain the compositional intent of the reference. "
            "Leave minimum 25% of the square as open area — typically sky, or a light-colored wall "
            "— for album typography. "
            "The composition should feel like a film still: "
            "one clear spatial layer in the foreground, environmental depth behind.\n\n"

            "STEP 8 — QUALITY:\n"
            "· Medium: watercolor and gouache on textured paper, or digital equivalent with visible brush texture\n"
            "· No photorealism. No smooth CGI gradients. No linework-dominant illustration.\n"
            "· No text. No watermark. No border. No vignette.\n"
            "· The image should feel like a still from a Makoto Shinkai film reimagined as a painted illustration "
            "— cinematic framing, emotional atmosphere, painterly surface.\n\n"

            "--ar 1:1 --style raw --stylize 750 --chaos 10"
        ),
    },

    "abstract": {
        "prompt": "Square vinyl album sleeve. Abstract art style. (placeholder — coming soon)",
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
    """Generate a cover image using Gemini (via OpenAIService), upload to R2, return URL."""
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

    gemini = GeminiService()
    storage = R2StorageService()

    try:
        image_bytes = await gemini.generate_cover_image(
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
