from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import timedelta

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import SessionLocal, SessionToken, User, utcnow


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 240_000)
    return f"pbkdf2_sha256$240000${salt.hex()}${digest.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        _, rounds, salt_hex, expected = encoded.split("$", 3)
        actual = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), int(rounds)
        ).hex()
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def issue_token(db: Session, user: User) -> str:
    raw = secrets.token_urlsafe(40)
    db.add(SessionToken(token=raw, user_id=user.id, expires_at=utcnow() + timedelta(days=7)))
    db.commit()
    return raw


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    header = request.headers.get("authorization", "")
    token = header[7:] if header.lower().startswith("bearer ") else request.cookies.get("studyship_token")
    if not token:
        raise HTTPException(401, "请先登录")
    row = db.scalar(select(SessionToken).where(SessionToken.token == token))
    if not row or row.expires_at < utcnow():
        raise HTTPException(401, "登录已过期")
    user = db.get(User, row.user_id)
    if not user:
        raise HTTPException(401, "用户不存在")
    return user


def require_teacher(user: User = Depends(current_user)) -> User:
    if user.role != "teacher":
        raise HTTPException(403, "此操作需要教师身份")
    return user
