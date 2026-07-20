"""
База данных Qalqan.

Хранит:
 - Conversation — одна переписка с одним потенциальным мошенником
 - Message — каждое сообщение внутри переписки (входящее/предложенное/отправленное)
 - Entity — извлечённые цифровые следы (телефон, карта, telegram, ссылка, крипто-кошелёк, email)
 - Report — сформированный отчёт по переписке
"""
import os
import datetime
from sqlalchemy import (
    create_engine, Column, Integer, String, Text, DateTime, Boolean,
    ForeignKey
)
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")  # всегда ищем .env рядом с этим файлом, независимо от CWD

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./qalqan.db")

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class Conversation(Base):
    __tablename__ = "conversations"

    id = Column(Integer, primary_key=True, index=True)
    tg_user_id = Column(String, index=True, nullable=True)       # telegram id собеседника
    tg_username = Column(String, nullable=True)
    tg_display_name = Column(String, nullable=True)
    status = Column(String, default="active")                   # active / closed
    scam_type = Column(String, nullable=True)                    # тип схемы (дропперство, фишинг ...)
    risk_level = Column(Integer, default=0)                      # 0-10
    is_scam = Column(Boolean, nullable=True)
    red_flags = Column(Text, nullable=True)                      # JSON-строка со списком признаков
    parent_contact = Column(String, nullable=True)               # telegram username родителя/доверенного лица (по желанию оператора)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    messages = relationship("Message", back_populates="conversation", cascade="all, delete-orphan")
    entities = relationship("Entity", back_populates="conversation", cascade="all, delete-orphan")
    reports = relationship("Report", back_populates="conversation", cascade="all, delete-orphan")


class Message(Base):
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True, index=True)
    conversation_id = Column(Integer, ForeignKey("conversations.id"))
    direction = Column(String)          # "incoming" (от мошенника) / "outgoing" (от нашего персонажа)
    text = Column(Text)
    status = Column(String, default="received")
    # received (входящее) / suggested (черновик от ИИ, ждёт оператора) /
    # sent (отправлено как есть) / edited_sent (отправлено с правкой оператора) / skipped
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    conversation = relationship("Conversation", back_populates="messages")


class Entity(Base):
    __tablename__ = "entities"

    id = Column(Integer, primary_key=True, index=True)
    conversation_id = Column(Integer, ForeignKey("conversations.id"))
    entity_type = Column(String)   # phone / card / telegram / link / crypto / email
    value = Column(String, index=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    conversation = relationship("Conversation", back_populates="entities")


class Report(Base):
    __tablename__ = "reports"

    id = Column(Integer, primary_key=True, index=True)
    conversation_id = Column(Integer, ForeignKey("conversations.id"))
    content = Column(Text)          # markdown-текст отчёта
    risk_level = Column(Integer)
    scam_type = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    conversation = relationship("Conversation", back_populates="reports")


def init_db():
    Base.metadata.create_all(bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
