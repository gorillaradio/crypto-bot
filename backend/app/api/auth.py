import secrets
from fastapi import APIRouter, Depends, HTTPException, Request, status
from app.core.config import settings
from app.db.base import SessionLocal
from app.db.models import ShareLink
from app.api.schemas import LoginIn, ViewerIn, MeOut, ShareLinkIn, ShareLinkOut

router = APIRouter(prefix="/api")


def session_dep():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def current_role(request: Request, session) -> str | None:
    """Resolve the caller's role from the signed session, re-validating a
    viewer's link against the DB so revocation takes effect immediately."""
    role = request.session.get("role")
    if role == "admin":
        return "admin"
    if role == "viewer":
        link_id = request.session.get("link_id")
        if link_id is not None and session.get(ShareLink, link_id) is not None:
            return "viewer"
    return None


def require_admin(request: Request) -> str:
    if request.session.get("role") == "admin":
        return "admin"
    raise HTTPException(status.HTTP_401_UNAUTHORIZED, "authentication required")


def require_viewer_or_admin(request: Request, session=Depends(session_dep)) -> str:
    role = current_role(request, session)
    if role is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "authentication required")
    return role


@router.post("/auth/login", response_model=MeOut)
def login(payload: LoginIn, request: Request):
    if settings.admin_password and secrets.compare_digest(payload.password, settings.admin_password):
        request.session.clear()
        request.session["role"] = "admin"
        return MeOut(role="admin")
    raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid password")


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(request: Request):
    request.session.clear()


@router.get("/auth/me", response_model=MeOut)
def me(request: Request, session=Depends(session_dep)):
    return MeOut(role=current_role(request, session))


@router.post("/auth/viewer", response_model=MeOut)
def viewer(payload: ViewerIn, request: Request, session=Depends(session_dep)):
    link = session.query(ShareLink).filter_by(token=payload.token).first()
    if link is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid link")
    request.session.clear()
    request.session["role"] = "viewer"
    request.session["link_id"] = link.id
    return MeOut(role="viewer")


def _link_out(request: Request, link: ShareLink) -> ShareLinkOut:
    return ShareLinkOut(
        id=link.id, label=link.label, token=link.token,
        url=f"{request.base_url}#{link.token}", created_at=link.created_at,
    )


@router.get("/share-links", response_model=list[ShareLinkOut])
def list_share_links(request: Request, _: str = Depends(require_admin), session=Depends(session_dep)):
    rows = session.query(ShareLink).order_by(ShareLink.created_at.desc()).all()
    return [_link_out(request, link) for link in rows]


@router.post("/share-links", response_model=ShareLinkOut, status_code=status.HTTP_201_CREATED)
def create_share_link(payload: ShareLinkIn, request: Request,
                      _: str = Depends(require_admin), session=Depends(session_dep)):
    link = ShareLink(label=payload.label, token=secrets.token_urlsafe(32))
    session.add(link)
    session.commit()
    session.refresh(link)
    return _link_out(request, link)


@router.delete("/share-links/{link_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_share_link(link_id: int, _: str = Depends(require_admin), session=Depends(session_dep)):
    link = session.get(ShareLink, link_id)
    if link is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "link not found")
    session.delete(link)
    session.commit()
