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
    PublicUpdateRequest,
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
        title=body.title or "",
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
        coverTitleVisible=record.cover_title_visible,
        coverTitlePosition=record.cover_title_position,
        coverTitleFont=record.cover_title_font,
        coverTitleColor=record.cover_title_color,
        coverTitleBgColor=record.cover_title_bg_color,
        isPublic=record.is_public,
        bgmId=record.bgm_id,
        bgmUrl=record.bgm_url,
        coverImage=CoverImageInfo(url=record.cover_image.url) if record.cover_image else None,
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
        "coverTitleVisible": "cover_title_visible",
        "coverTitlePosition": "cover_title_position",
        "coverTitleFont": "cover_title_font",
        "coverTitleColor": "cover_title_color",
        "coverTitleBgColor": "cover_title_bg_color",
        "isPublic": "is_public",
        "bgmId": "bgm_id",
        "bgmUrl": "bgm_url",
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
        coverTitleVisible=record.cover_title_visible,
        coverTitlePosition=record.cover_title_position,
        coverTitleFont=record.cover_title_font,
        coverTitleColor=record.cover_title_color,
        coverTitleBgColor=record.cover_title_bg_color,
        isPublic=record.is_public,
        bgmId=record.bgm_id,
        bgmUrl=record.bgm_url,
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


@router.patch("/{record_id}/public", response_model=ApiResponse)
async def update_public(
    record_id: uuid.UUID,
    body: PublicUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = RecordService(db)
    record = await service.get_record_by_id(record_id)
    if not record:
        raise NotFoundException("Record not found")

    assoc = await service.get_user_association(current_user.id, record_id)
    is_owner = (assoc is not None and assoc.role == "owner") or (
        record.creator_id == current_user.id
    )
    if not is_owner:
        raise ForbiddenException("Only the owner can change public status")

    record = await service.update_record(record, {"is_public": body.isPublic})
    return success_response(data={"ok": True, "isPublic": record.is_public})


@router.patch("/{record_id}/story-gen-count", response_model=ApiResponse)
async def increment_story_gen_count(
    record_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = RecordService(db)
    record = await service.get_record_by_id(record_id)
    if not record:
        raise NotFoundException("Record not found")

    assoc = await service.get_user_association(current_user.id, record_id)
    is_owner = (assoc is not None and assoc.role == "owner") or (
        record.creator_id == current_user.id
    )
    if not is_owner:
        raise ForbiddenException("Only the owner can update this record")

    if record.story_gen_count >= 3:
        raise HTTPException(
            status_code=400,
            detail="생애문 생성 횟수가 초과되었습니다 (최대 3회)",
        )

    record.story_gen_count += 1
    await db.commit()
    await db.refresh(record)

    return success_response(data={
        "storyGenCount": record.story_gen_count,
        "remainingGenerations": 3 - record.story_gen_count,
    })


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
        coverTitleVisible=record.cover_title_visible,
        coverTitlePosition=record.cover_title_position,
        coverTitleFont=record.cover_title_font,
        coverTitleColor=record.cover_title_color,
        coverTitleBgColor=record.cover_title_bg_color,
        isPublic=record.is_public,
        bgmId=record.bgm_id,
        bgmUrl=record.bgm_url,
        coverGenCount=record.cover_gen_count,
        storyGenCount=record.story_gen_count,
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
            '''
            Square vinyl album sleeve. Hand-drawn illustration in the manner of a skilled artist making deliberate choices — not a traced photograph, not a filtered image.

STEP 1 — READ, THEN INTERPRET:
Identify the subject, scene, mood, and key visual relationships in the reference image. Then make the following artistic decisions before drawing anything:
· What is the single most important visual element? This receives the most rendering.
· What supports the mood but does not need detail? This gets simplified.
· What is incidental noise that adds nothing? This gets omitted entirely.
The reference image is a starting point, not a blueprint. The drawing must show what an artist chose to draw, not what a camera captured.

STEP 1-B — FACE GEOMETRY LOCK (applies when reference contains a face):
Before any mark is made, measure and memorize the following spatial relationships from the reference image. These are fixed constraints. They must not change in the drawing output — not for stylistic reasons, not for aesthetic improvement, not for idealization.

FIXED MEASUREMENTS — preserve exactly:
· Eye position: the horizontal axis on which both eyes sit, and the vertical position of that axis relative to the total face height
· Inter-eye distance: the gap between the inner corners of the two eyes — preserve this ratio relative to face width
· Eye shape and tilt: the angle of each eye's opening — whether the outer corner rises, falls, or is level
· Nose length: the distance from the bridge to the tip, as a proportion of face height
· Nose width: the width of the nostrils relative to the eye width
· Philtrum length: the distance between the base of the nose and the top of the upper lip
· Lip width and shape: the horizontal span of the mouth, the curvature of the cupid's bow, the fullness ratio between upper and lower lip
· Jaw line angle and chin shape
· Face width-to-height ratio

WHAT THIS MEANS IN PRACTICE:
· If the reference person has eyes set close together, the drawing must have eyes set close together
· If the reference person has a wide mouth, the drawing must have a wide mouth
· The drawing may simplify or stylize — but it must not correct, idealize, or normalize any measurement
· A viewer who knows the person should recognize the same face structure in the drawing

DO NOT adjust the face toward more "balanced", "attractive", or "idealized" proportions. Do not apply any correction a beauty retoucher would apply.

STEP 2 — ABSTRACTION RULES (mandatory):
TEXT AND WRITING: Any text or lettering visible in the reference must NEVER be reproduced as readable characters. Translate all text into gestural marks — clusters of horizontal lines, scribbled texture, loose hatching that suggests writing without reproducing it. Readable text in the illustration is a failure.

PATTERNS AND REPETITIVE DETAIL: Dense repeating patterns are rendered as tonal masses or simplified texture strokes — not individually drawn repeated elements. A sweater becomes 5–7 curved lines suggesting knit. A wall of hanging objects becomes a suggested mass with gestural surface marks, not individually rendered items.

CROWDS AND BACKGROUND FIGURES: Reduce to silhouette shapes or shadow masses. No facial detail.

ARCHITECTURE AND STRUCTURES: Key structural lines only — enough to establish space. Decorative details are omitted.

STEP 3 — RENDERING HIERARCHY:

ZONE 1 — FACE (highest priority — geometry lock applies):
Render with maximum precision and densest linework. Face structure from Step 1-B is absolute. Within that structure, apply chosen drawing style: precise linework for features, hatching or ink wash for shadow planes. Maximum rendering density is here and only here.

ZONE 2 — SOLID BLACK MASSES (hair, deep shadows, dark elements):
Flat opaque solid black — no internal hatching. Edge strokes may suggest movement. Interior is pure filled black.

ZONE 3 — GESTURAL SUGGESTION (clothing, hands, secondary objects):
3 to 10 confident marks establish form. No fill, no texture rendering. Rest is white paper.

ZONE 4 — BACKGROUND (scene-dependent):
· Portrait or intimate scene: near-white. 1–3 structural lines anchor the figure.
· Important environment: key structural outlines at half Zone 1 density. Pattern becomes tonal suggestion.
· Night or dramatic: solid masses and ink wash. Subject silhouette remains clear.

STEP 4 — THE ARTIST'S MARK:
Every line is a deliberate decision. Lines are fast and confident, varied in weight (thick at silhouette, medium at form edges, fine at Zone 1 only), and incomplete where appropriate. Lines that look like careful photo tracing are a failure.

STEP 5 — COMPOSE FOR THE SLEEVE:
Reframe if needed to give the subject compositional weight, create open space (minimum 25%) for typography, and establish clear visual hierarchy. The composition should feel like an album cover, not a documentary sketch.

STEP 6 — QUALITY:
· Achromatic: ink black, graphite gray, paper white only
· Paper: smooth cartridge or hot-press — marks remain visible and crisp
· No photorealism. No photo-filter look. No uniform line density.
· No readable text. No watermark. No border. No vignette.

Aesthetic reference: the mark-making confidence of Kim Jung Gi, gestural abstraction of ink wash portraiture, tonal hierarchy of editorial fashion illustration — applied with deliberate restraint, not the completeness of a scanner.

--ar 1:1 --style raw --stylize 850 --chaos 12
            '''
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
        "prompt": '''
        Square vinyl album sleeve. Graphic art and abstract illustration style.

STEP 1 — READ THE REFERENCE:
Identify the subject, scene, spatial composition, dominant mood, and — critically — the luminosity structure of the reference image. Map the following before making any graphic decisions:
· Which areas are brightest in the original? (typically: face, skin, light surfaces)
· Which areas are mid-tone?
· Which areas are darkest? (typically: hair, shadows, deep background)
This luminosity map is a fixed constraint. Even when all colors are replaced with a deliberate graphic palette, the relative light-dark relationships must be preserved. A bright face in the original must remain the brightest region in the output. A dark background must remain darker than the subject.

STEP 2 — ESTABLISH VISUAL HIERARCHY (most critical rule):
The output must have a clear three-zone visual hierarchy based on complexity, pattern density, and outline weight. These zones map directly to spatial depth in the image:

ZONE A — PRIMARY SUBJECT (closest to camera, highest priority):
· Color: simplified flat planes — 2 to 4 colors maximum for this zone
· Texture/pattern: none or minimal. The subject is the LEAST patterned area in the image.
· Outline: boldest and thickest lines in the image define the subject's outer silhouette against the background
· Value: must be the lightest or highest-contrast area in the image — matching the original's luminosity structure
· The face, if present, receives the clearest, most readable color plane rendering

ZONE B — MID-GROUND (supporting environment, secondary elements):
· Color: flat planes, may use 1 to 2 simple accent patterns (dots, stripes) sparingly
· Outline: medium weight — thinner than Zone A's outer silhouette
· Value: mid-range — darker than Zone A, lighter than Zone C

ZONE C — BACKGROUND (farthest from camera, lowest priority):
· Color: flat planes with more graphic complexity — patterns, textures, and decorative fills are permitted here
· Outline: thinnest or absent — background elements do not compete with the subject
· Value: must be the darkest or most complex area — pushing the subject forward visually
· Background patterns and graphic elements recede, they do not compete with the subject

IF ANY ZONE HAS EQUAL COMPLEXITY TO ANOTHER, THE HIERARCHY HAS FAILED.

STEP 3 — GRAPHIC TRANSLATION PRINCIPLES:

COLOR AS DECISION, NOT OBSERVATION:
Do not use the colors from the reference photograph. Build a deliberate palette of 4 to 7 colors. The palette must have a wide value range — from a near-white or very light color to a near-black or very dark color. This range is essential for the hierarchy in Step 2 to function. Apply colors in flat, unblended planes — no photographic gradients.

FORM AS SHAPE, NOT RENDERING:
All subjects are reduced to simplified graphic shapes — no photorealistic skin texture, no smooth shadow gradients. Faces become 3 to 5 flat color shapes. Figures become silhouettes with internal color division. The medium simplifies, it does not trace.

MEDIUM / TEXTURE — choose one and apply with restraint:
· Screen print / silkscreen: flat color fills, registration offset between color layers, halftone dots used ONLY in Zone B and Zone C — never covering the primary subject's face or main color planes
· Risograph: two or three ink colors with slight offset; ink is grainy and translucent; used to suggest depth, not fill everything
· Flat graphic / vector: pure flat color, no texture anywhere, clean sharp edges
· Collage / mixed media: layered color shapes; patterns appear as fragments in Zone C, not as wallpaper across the whole image
· Expressionist paint: gestural color planes following emotional intent; value structure from Step 1 must still be respected
· Neon / vivid: dark background (Zone C is dark and rich), subject glows forward against it; no equal brightness everywhere

THE MEDIUM IS NOT AN EXCUSE TO FILL EVERY AREA WITH EQUAL PATTERN DENSITY. Patterns serve hierarchy, not decoration.

STEP 4 — OUTLINE LOGIC:
Outline weight must vary dramatically across the image:
· Primary subject outer boundary: thickest — this is the most important line in the image
· Internal divisions within the subject: medium weight
· Background elements: thin or no outline — they do not compete
Uniform outline weight across the entire image is a failure.

STEP 5 — SUBJECT RENDERING SPECIFICS:
· Person or figure: the silhouette is a bold graphic shape. The face is rendered with the fewest, largest color planes — not filled with pattern. Eyes, nose, and mouth may be simplified to minimal marks, but the face plane must be the clearest readable region in the image.
· Environment or scene: translate key structural elements into flat geometric color planes. Background patterns and graphic elements are used in Zone C only.
· Object: bold isolated graphic form. The object itself is clean; the background may be patterned.

STEP 6 — COMPOSE FOR THE SLEEVE:
Maintain the compositional structure of the reference. Leave a zone of open color field (minimum 25% of the frame) for album typography — this zone is a flat color plane, part of the design.

STEP 7 — QUALITY:
· The image must have a readable, clear visual hierarchy: subject pops from background
· Color is flat and deliberate — not naturalistic
· No photorealism, no smooth CGI rendering
· No uniform pattern density across all zones
· No text, no watermark, no border

Aesthetic lineage: Andy Warhol's silkscreen flatness, Roy Lichtenstein's halftone graphic language, contemporary flat editorial illustration — all of which maintain strong subject/background separation and value hierarchy.

--ar 1:1 --style raw --stylize 750 --chaos 10
        ''',
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
        image_bytes, mime_type, ext = await gemini.generate_cover_image(
            prompt=style_config["prompt"],
            reference_image_bytes=reference_image_bytes,
        )
    except Exception as e:
        logger.error("Cover image generation failed: %s: %s", type(e).__name__, e)
        raise HTTPException(status_code=500, detail="이미지 생성에 실패했습니다")

    url = await storage.upload_file(image_bytes, mime_type, ext)

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
    match = re.search(r"share/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})", body.url)
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
        coverTitleVisible=record.cover_title_visible,
        coverTitlePosition=record.cover_title_position,
        coverTitleFont=record.cover_title_font,
        coverTitleColor=record.cover_title_color,
        coverTitleBgColor=record.cover_title_bg_color,
        isPublic=record.is_public,
        bgmId=record.bgm_id,
        bgmUrl=record.bgm_url,
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
