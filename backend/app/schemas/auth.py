from pydantic import BaseModel


class LoginRequest(BaseModel):
    password: str


class SessionStatus(BaseModel):
    authenticated: bool
