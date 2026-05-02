"""Account lifecycle management API."""
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from core.lifecycle import (
    check_accounts_validity,
    flag_expiring_trials,
    refresh_expiring_tokens,
)

router = APIRouter(prefix="/lifecycle", tags=["lifecycle"])


class CheckRequest(BaseModel):
    platform: str = ""
    limit: int = 100


class RefreshRequest(BaseModel):
    platform: str = ""
    limit: int = 50


class WarningRequest(BaseModel):
    hours: int = 48


@router.post("/check")
def trigger_validity_check(body: CheckRequest):
    """Manually trigger batch account validity check."""
    results = check_accounts_validity(platform=body.platform, limit=body.limit)
    return {"ok": True, "data": results}


@router.post("/refresh")
def trigger_token_refresh(body: RefreshRequest):
    """Manually trigger batch token refresh."""
    results = refresh_expiring_tokens(platform=body.platform, limit=body.limit)
    return {"ok": True, "data": results}


@router.post("/warn")
def trigger_expiry_warning(body: WarningRequest):
    """Manually trigger expiry warning scan."""
    results = flag_expiring_trials(hours_warning=body.hours)
    return {"ok": True, "data": results}


@router.get("/status")
def lifecycle_status():
    """Return lifecycle manager running status."""
    from core.lifecycle import lifecycle_manager
    return {
        "running": lifecycle_manager._running,
        "check_interval_hours": lifecycle_manager.check_interval / 3600,
        "refresh_interval_hours": lifecycle_manager.refresh_interval / 3600,
        "warning_hours": lifecycle_manager.warning_hours,
    }
