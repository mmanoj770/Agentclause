from fastapi import APIRouter, Depends
from app.auth.dependencies import CurrentUser, get_current_user, require_role
from app.db import get_conn

router = APIRouter()

@router.get("/me")
def me(user: CurrentUser = Depends(get_current_user), conn=Depends(get_conn)):
    profile = conn.execute(
        "select id, email, full_name, role, org_id from profiles where id = %s",
        (user.id,),
    ).fetchone()
    return {"token": user, "profile": profile}

@router.get("/lawyer/ping")
def lawyer_ping(user: CurrentUser = Depends(require_role("lawyer"))):
    return {"ok": True, "lawyer_id": user.id}
