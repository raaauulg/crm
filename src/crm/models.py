"""Modelo de datos (SQLAlchemy 2.0, estilo tipado).

Importes en céntimos (int). Fechas como `date` / `datetime` sin zona: se interpretan
siempre en Europe/Madrid (ver `crm.services.clock`).
"""

from datetime import date, datetime
from enum import StrEnum

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from crm.services.clock import now


class Phase(StrEnum):
    LEAD = "0-Lead"
    IDENTIFIED = "1-Identificado"
    CONTACTED = "2-Contactado"
    MEETING = "3-Reunión"
    DIAGNOSIS = "4-Diagnóstico"
    PROPOSAL_SENT = "5-Propuesta enviada"
    WON = "6-Ganado"
    LOST = "7-Perdido"


class Channel(StrEnum):
    CALL = "llamada"
    VISIT = "visita"
    EMAIL = "email"
    WHATSAPP = "whatsapp"
    EVENT = "evento"
    OTHER = "otro"


class ContractStatus(StrEnum):
    ACTIVE = "activo"
    CANCELLED = "cancelado"


class Base(DeclarativeBase):
    pass


class AuditMixin:
    """Quién y cuándo. El autor es el nombre de usuario, o `mcp` / `cli` / `demo`."""

    created_by: Mapped[str] = mapped_column(String(50))
    updated_by: Mapped[str] = mapped_column(String(50))
    created_at: Mapped[datetime] = mapped_column(default=now)
    updated_at: Mapped[datetime] = mapped_column(default=now, onupdate=now)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(50), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(default=now)


class Service(Base):
    __tablename__ = "services"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    setup_price_cents: Mapped[int] = mapped_column(default=0)
    monthly_fee_cents: Mapped[int] = mapped_column(default=0)
    active: Mapped[bool] = mapped_column(default=True)


class Company(AuditMixin, Base):
    __tablename__ = "companies"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True)
    sector: Mapped[str] = mapped_column(String(100), default="")
    municipality: Mapped[str] = mapped_column(String(100), default="")
    website: Mapped[str] = mapped_column(String(200), default="")
    phone: Mapped[str] = mapped_column(String(50), default="")
    source: Mapped[str] = mapped_column(String(100), default="")
    phase: Mapped[str] = mapped_column(String(30), default=Phase.IDENTIFIED.value, index=True)
    service_id: Mapped[int | None] = mapped_column(ForeignKey("services.id"))
    estimated_value_cents: Mapped[int | None] = mapped_column()
    estimated_fee_cents: Mapped[int | None] = mapped_column()
    pain_score: Mapped[int | None] = mapped_column()
    notes: Mapped[str] = mapped_column(Text, default="")
    next_step: Mapped[str] = mapped_column(String(300), default="")
    next_step_date: Mapped[date | None] = mapped_column(index=True)

    service: Mapped[Service | None] = relationship()
    contacts: Mapped[list["Contact"]] = relationship(
        back_populates="company",
        cascade="all, delete-orphan",
        order_by="(Contact.is_primary.desc(), Contact.name)",
    )
    interactions: Mapped[list["Interaction"]] = relationship(
        back_populates="company",
        cascade="all, delete-orphan",
        order_by="(Interaction.occurred_on.desc(), Interaction.id.desc())",
    )
    contracts: Mapped[list["Contract"]] = relationship(
        back_populates="company", order_by="Contract.start_date.desc()"
    )
    invoices: Mapped[list["Invoice"]] = relationship(
        back_populates="company", order_by="Invoice.issue_date.desc()"
    )


class Contact(AuditMixin, Base):
    __tablename__ = "contacts"

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    name: Mapped[str] = mapped_column(String(150))
    role: Mapped[str] = mapped_column(String(100), default="")
    phone: Mapped[str] = mapped_column(String(50), default="")
    email: Mapped[str] = mapped_column(String(150), default="")
    is_primary: Mapped[bool] = mapped_column(default=False)
    data_source: Mapped[str] = mapped_column(String(100), default="")
    data_date: Mapped[date | None] = mapped_column()

    company: Mapped[Company] = relationship(back_populates="contacts")


class Interaction(Base):
    __tablename__ = "interactions"

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    occurred_on: Mapped[date] = mapped_column(index=True)
    channel: Mapped[str] = mapped_column(String(20))
    summary: Mapped[str] = mapped_column(Text)
    result: Mapped[str] = mapped_column(Text, default="")
    created_by: Mapped[str] = mapped_column(String(50))
    created_at: Mapped[datetime] = mapped_column(default=now)

    company: Mapped[Company] = relationship(back_populates="interactions")


class Contract(AuditMixin, Base):
    __tablename__ = "contracts"

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    service_id: Mapped[int] = mapped_column(ForeignKey("services.id"))
    setup_price_cents: Mapped[int] = mapped_column(default=0)
    monthly_fee_cents: Mapped[int] = mapped_column(default=0)
    start_date: Mapped[date] = mapped_column()
    commitment_months: Mapped[int] = mapped_column(default=0)
    end_date: Mapped[date | None] = mapped_column()
    status: Mapped[str] = mapped_column(String(20), default=ContractStatus.ACTIVE.value)

    company: Mapped[Company] = relationship(back_populates="contracts")
    service: Mapped[Service] = relationship()


class Invoice(AuditMixin, Base):
    """Registro de una factura emitida en un programa externo. El CRM no emite facturas."""

    __tablename__ = "invoices"

    id: Mapped[int] = mapped_column(primary_key=True)
    number: Mapped[str] = mapped_column(String(50), unique=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    contract_id: Mapped[int | None] = mapped_column(ForeignKey("contracts.id"))
    issue_date: Mapped[date] = mapped_column(index=True)
    base_cents: Mapped[int] = mapped_column()
    vat_percent: Mapped[int] = mapped_column(default=21)
    total_cents: Mapped[int] = mapped_column()
    due_date: Mapped[date] = mapped_column()
    paid_date: Mapped[date | None] = mapped_column()

    company: Mapped[Company] = relationship(back_populates="invoices")
    contract: Mapped[Contract | None] = relationship()


class OAuthClient(Base):
    """Clientes OAuth 2.1 registrados (dinámicamente o preconfigurados)."""

    __tablename__ = "oauth_clients"

    client_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    client_secret_hash: Mapped[str | None] = mapped_column(String(255))
    client_name: Mapped[str] = mapped_column(String(120))
    redirect_uris: Mapped[str] = mapped_column(Text)  # JSON list of strings
    grant_types: Mapped[str] = mapped_column(String(100), default="authorization_code")
    response_types: Mapped[str] = mapped_column(String(50), default="code")
    created_at: Mapped[datetime] = mapped_column(default=now)


class OAuthAuthorizationCode(Base):
    """Códigos de autorización temporales emitidos con PKCE."""

    __tablename__ = "oauth_authorization_codes"

    code: Mapped[str] = mapped_column(String(120), primary_key=True)
    client_id: Mapped[str] = mapped_column(ForeignKey("oauth_clients.client_id"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    redirect_uri: Mapped[str] = mapped_column(Text)
    code_challenge: Mapped[str] = mapped_column(String(128))
    code_challenge_method: Mapped[str] = mapped_column(String(10), default="S256")
    scope: Mapped[str] = mapped_column(String(100), default="mcp")
    expires_at: Mapped[datetime] = mapped_column(index=True)
    used_at: Mapped[datetime | None] = mapped_column()


class OAuthAccessToken(Base):
    """Tokens de acceso Bearer emitidos para clientes OAuth."""

    __tablename__ = "oauth_access_tokens"

    token: Mapped[str] = mapped_column(String(120), primary_key=True)
    client_id: Mapped[str] = mapped_column(ForeignKey("oauth_clients.client_id"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    scope: Mapped[str] = mapped_column(String(100), default="mcp")
    created_at: Mapped[datetime] = mapped_column(default=now)
    expires_at: Mapped[datetime] = mapped_column(index=True)
    revoked_at: Mapped[datetime | None] = mapped_column()
