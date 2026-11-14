"""行为上报：前端攒一批事件后 POST /api/t（页面关闭时用 keepalive）。不需要登录，按 IP 限频。"""

import json

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from ..auth import client_ip, current_user_optional
from ..db import get_db
from ..models import User
from ..services import visits

router = APIRouter(prefix="/api", tags=["track"])


@router.post("/t", status_code=204)
async def track(request: Request, db: Session = Depends(get_db), user: User | None = Depends(current_user_optional)):
    try:
        body = json.loads((await request.body())[:64_000] or b"{}")
    except ValueError:
        return Response(status_code=204)
    if not isinstance(body, dict):
        return Response(status_code=204)
    vid = visits.vid_of(request) or (str(body.get("vid") or "") if visits.VID_RE.match(str(body.get("vid") or "")) else "")
    events = body.get("events") if isinstance(body.get("events"), list) else []
    if vid and events and visits.rate_ok(client_ip(request)):
        visits.ingest(db, request, user, vid, [e for e in events if isinstance(e, dict)],
                        referrer=str(body.get("referrer") or ""), landing=str(body.get("landing") or ""))
    return Response(status_code=204)
