from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.api.deps import get_current_user
from app.models.user import User
from app.schemas.common import ApiResponse, success_response
from app.schemas.record import (
    RecordListItem,
    CoverImageInfo,
    LifestorySummary,
    TimelineSummary,
    EventItem,
    trial_fields,
)
from app.services.record import RecordService
from app.api.v1.record import _to_record_type

router = APIRouter()


@router.get("", response_model=ApiResponse)
async def get_record_list(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = RecordService(db)
    records_with_role = await service.get_records_by_user(current_user.id)

    data = [
        RecordListItem(
            id=r.id,
            title=r.title,
            subtitle=r.subtitle,
            coverImage=CoverImageInfo(url=r.cover_image.url) if r.cover_image else None,
            bgColor=r.bg_color,
            color=r.color,
            keyColor=r.key_color,
            theme=r.theme,
            exhibitionType=r.exhibition_type,
            coverTitleVisible=r.cover_title_visible,
            coverTitlePosition=r.cover_title_position,
            coverTitleFont=r.cover_title_font,
            coverTitleColor=r.cover_title_color,
            coverTitleBgColor=r.cover_title_bg_color,
            isPublic=r.is_public,
            bgmId=r.bgm_id,
            bgmUrl=r.bgm_url,
            externalLinkTitle=r.external_link_title,
            externalLinkUrl=r.external_link_url,
            backCoverImageUrl=r.back_cover_image_url,
            recordType=_to_record_type(r.exhibition_type),
            vhsFilter=r.vhs_filter,
            vhsTransition=r.vhs_transition,
            vhsPhotoFrameIndex=r.vhs_photo_frame_index,
            vhsImageDuration=r.vhs_image_duration,
            vhsVideoMode=r.vhs_video_mode,
            walkCameraSpeed=r.walk_camera_speed,
            walkVideoPreview=r.walk_video_preview,
            walkVideoMaxDuration=r.walk_video_max_duration,
            role=role,
            lifestory=LifestorySummary(
                mood=r.lifestory.mood,
                content=r.lifestory.content,
            ) if r.lifestory else None,
            timeline=TimelineSummary(
                events=[
                    EventItem(
                        title=e.title,
                        timestamp=e.timestamp,
                        description=e.description,
                    )
                    for e in (r.timeline.events if r.timeline and r.timeline.events else [])
                ]
            ) if r.timeline else None,
            **trial_fields(r.is_trial, r.created_at),
            createdAt=r.created_at,
            updatedAt=r.updated_at,
        )
        for (r, role) in records_with_role
    ]
    return success_response(data=data)
