from sqlalchemy import Column, String, Integer, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from uuid import uuid4

from database import Base


class TaskDB(Base):
    __tablename__ = "tasks"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid4
    )

    title = Column(
        String,
        nullable=False
    )

    category = Column(
        String,
        nullable=False
    )

    estimated_minutes = Column(
        Integer,
        nullable=False
    )

    importance = Column(
        Integer,
        nullable=False
    )

    status = Column(
        String,
        nullable=False,
        default="todo"
    )

    due_at = Column(
        DateTime(timezone=True),
        nullable=True
    )

    started_at = Column(
        DateTime(timezone=True),
        nullable=True
    )

    completed_at = Column(
        DateTime(timezone=True),
        nullable=True
    )

    parent_task_id = Column(
    UUID(as_uuid=True),
    ForeignKey("tasks.id"),
    nullable=True
    )
    depends_on_task_id = Column(
        UUID(as_uuid=True),
        ForeignKey("tasks.id"),
        nullable=True
    )
    