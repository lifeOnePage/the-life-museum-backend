from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.api.deps import get_current_user
from app.models.user import User
from app.schemas.common import ApiResponse, success_response
from app.schemas.record import RecordListItem, CoverImageInfo
from app.services.record import RecordService

router = APIRouter()


@router.get("", response_model=ApiResponse)
async def get_record_list(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = RecordService(db)
    records = await service.get_records_by_user(current_user.id)

    data = [
        RecordListItem(
            id=r.id,
            title=r.title,
            subtitle=r.subtitle,
            coverImage=CoverImageInfo(url=r.cover_image.url) if r.cover_image else None,
            createdAt=r.created_at,
            updatedAt=r.updated_at,
        )
        for r in records
    ]
    return success_response(data=data)
