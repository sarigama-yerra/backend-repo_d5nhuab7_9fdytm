from typing import Optional, List
from pydantic import BaseModel, Field, EmailStr


class AdminCreate(BaseModel):
    email: EmailStr
    password: str


class AdminDB(BaseModel):
    id: Optional[str] = Field(default=None, alias="_id")
    email: EmailStr
    password_hash: str


class ClientCreate(BaseModel):
    name: str
    email: EmailStr
    phone: Optional[str] = None
    capital: float = 0.0
    profit: float = 0.0


class ClientUpdate(BaseModel):
    capital: Optional[float] = None
    profit: Optional[float] = None


class ClientDB(BaseModel):
    id: Optional[str] = Field(default=None, alias="_id")
    name: str
    email: EmailStr
    phone: Optional[str] = None
    capital: float = 0.0
    profit: float = 0.0


class TransactionLog(BaseModel):
    id: Optional[str] = Field(default=None, alias="_id")
    client_id: str
    amount: float
    action: str  # withdraw or transfer
    timestamp: Optional[str] = None
    note: Optional[str] = None


class WithdrawRequest(BaseModel):
    client_id: str
    amount: float
    note: Optional[str] = None


class TransferRequest(BaseModel):
    from_client_id: str
    to_client_id: str
    amount: float
    note: Optional[str] = None


class AdminLoginRequest(BaseModel):
    email: EmailStr
    password: str


class AdminLoginResponse(BaseModel):
    token: str
    email: EmailStr
