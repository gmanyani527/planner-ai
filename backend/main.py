from fastapi import FastAPI, HTTPException, Depends
from pydantic import BaseModel, Field
from enum import Enum
from datetime import datetime
from uuid import UUID, uuid4
from sqlalchemy.orm import Session

import models
from database import engine, get_db

models.Base.metadata.create_all(bind=engine)
app = FastAPI()

class TaskCategory(str, Enum):
    SCHOOL = "school"
    EXAM = "exam"
    INTERNSHIP = "internship"
    DSA = "dsa"
    PROJECT = "project"
    PERSONAL = "personal"

class TaskStatus(str, Enum):
    TODO = "todo"
    IN_PROGRESS = "in_progress"
    DONE = "done"


class TaskCreate(BaseModel):
    title: str = Field(min_length=1)
    category: TaskCategory
    estimated_minutes: int = Field(ge=5)
    importance: int = Field(ge=1, le=10)
    due_at:datetime | None = None
    parent_task_id: UUID | None = None
    depends_on_task_id: UUID | None = None
    

class Task(TaskCreate):
    id: UUID
    status: TaskStatus = TaskStatus.TODO
    started_at: datetime | None = None
    completed_at: datetime | None = None

@app.get("/")

def home():
    return {"message" : "Planner AI is running"}

@app.get("/analytics/category/{category}")
def get_category_analytics(
    category: TaskCategory,
    db: Session = Depends(get_db)
):
    multiplier = calculate_category_multiplier(
        category,
        db
    )

    return {
        "category": category,
        "estimate_multiplier": multiplier
    }


@app.get("/tasks")
def get_tasks(
    status: TaskStatus | None = None,
    db: Session = Depends(get_db)
    ):
    query = db.query(models.TaskDB)

    if status:
            query = query.filter(
            models.TaskDB.status == status.value
            )
    tasks_from_db = query.all()

    sorted_tasks = sorted(
        tasks_from_db,
        key=lambda task: calculate_priority(task, db),
        reverse=True
    )

    return [
        {
         
     "id": task.id,
    "title": task.title,
    "importance": task.importance,
    "due_at": task.due_at,
    "status": task.status,
    "estimated_minutes": task.estimated_minutes,
    "recommended_minutes": calculate_recommended_minutes(task,db),
    "actual_minutes": calculate_actual_minutes(task),
    "estimate_difference": calculate_estimate_difference(task),
    "estimate_ratio": calculate_estimate_ratio(task),
    "deadline_risk": calculate_deadline_risk(task,db),
    "priority_score": calculate_priority(task, db),
    "parent_task_id": task.parent_task_id,
    "blocked": is_task_blocked(task, db),
    "blocked_by": (
        get_blocking_task(task, db).title
        if get_blocking_task(task, db)
        else None
    ),
        }
        for task in sorted_tasks
    ]

@app.get("/tasks/{task_id}/subtasks")
def get_subtasks(
    task_id: UUID,
    db: Session = Depends(get_db)
):
    subtasks = (
        db.query(models.TaskDB)
        .filter(models.TaskDB.parent_task_id == task_id)
        .all()
    )

    return subtasks

@app.get("/tasks/next")
def get_next_task(
    db: Session = Depends(get_db)
):
    unfinished_tasks = (
        db.query(models.TaskDB)
        .filter(models.TaskDB.status != TaskStatus.DONE.value)
        .all()
    )

    available_tasks = [
        task for task in unfinished_tasks
        if not is_task_blocked(task, db)
    ]

    if not available_tasks:
        return {"message": "No available tasks"}

    next_task = max(
        available_tasks,
        key=lambda task: calculate_priority(task, db)
    )

    return {
        "id": next_task.id,
        "title": next_task.title,
        "status": next_task.status,
        "priority_score": calculate_priority(next_task, db)
    }

@app.get("/tasks/current")
def get_current_task(
    db: Session = Depends(get_db)
):
    current_task = (
        db.query(models.TaskDB)
        .filter(models.TaskDB.status == TaskStatus.IN_PROGRESS.value)
        .first()
    )

    if current_task is None:
        return {"message": "No task currently in progress"}

    return current_task

@app.get("/tasks/{task_id}/progress")
def get_task_progress(
    task_id: UUID,
    db: Session = Depends(get_db)
):
    progress = calculate_task_progress(task_id, db)

    if progress is None:
        return {
            "total": 0,
            "completed": 0,
            "percentage": 0
        }

    return progress

@app.post("/tasks")
def create_task(
    task: TaskCreate,
    db: Session = Depends(get_db)
):
    new_task = models.TaskDB(
        title=task.title,
        category=task.category.value,
        estimated_minutes=task.estimated_minutes,
        importance=task.importance,
        due_at=task.due_at,
        parent_task_id=task.parent_task_id,
        depends_on_task_id=task.depends_on_task_id
    )

    db.add(new_task)
    db.commit()
    db.refresh(new_task)

    return new_task

@app.patch("/tasks/{task_id}/done")
def complete_task(
    task_id: UUID,
    db: Session = Depends(get_db)
):
    task = (
    db.query(models.TaskDB)
    .filter(models.TaskDB.id == task_id)
    .first()
)

    if task is None:
        raise HTTPException(
        status_code=404,
        detail="Task not found"
    )

    if is_task_blocked(task, db):
        raise HTTPException(
        status_code=409,
        detail="Task dependency is not completed"
    )

    task.status = TaskStatus.DONE.value
    task.completed_at = datetime.now()

    db.commit()
    db.refresh(task)

    update_parent_status(task, db)

    return task

@app.patch("/tasks/{task_id}/start")
def start_task(
    task_id: UUID,
    db: Session = Depends(get_db)
):
    current_task = (
        db.query(models.TaskDB)
        .filter(models.TaskDB.status == TaskStatus.IN_PROGRESS.value)
        .first()
    )

    if current_task and current_task.id != task_id:
        raise HTTPException(
            status_code=409,
            detail=f"{current_task.title} is already in progress"
        )

    task = (
        db.query(models.TaskDB)
        .filter(models.TaskDB.id == task_id)
        .first()
    )


    if task is None:
        raise HTTPException(
            status_code=404,
            detail="Task not found"
        )
    
    if is_task_blocked(task, db):
            raise HTTPException(
            status_code=409,
            detail="Task dependency is not completed"
        )

    task.status = TaskStatus.IN_PROGRESS.value
    task.started_at = datetime.now()

    db.commit()
    db.refresh(task)

    return task

def calculate_priority(
    task,
    db: Session
):
    score = task.importance * 10

    risk = calculate_deadline_risk(task, db)

    if risk == "overdue":
        score += 50
    elif risk == "high":
        score += 30
    elif risk == "medium":
        score += 15

    if task.category == TaskCategory.EXAM.value:
        score += 20
    elif task.category == TaskCategory.SCHOOL.value:
        score += 15
    elif task.category == TaskCategory.INTERNSHIP.value:
        score += 10
    elif task.category == TaskCategory.DSA.value:
        score += 5

    if task.due_at:
        now = datetime.now(task.due_at.tzinfo)

        hours_until_due = (
            task.due_at - now
        ).total_seconds() / 3600

        if hours_until_due <= 24:
            score += 30
        elif hours_until_due <= 72:
            score += 20
        elif hours_until_due <= 168:
            score += 10

    return score

def calculate_actual_minutes(task: Task):
    if task.started_at and task.completed_at:
        return round(
    (task.completed_at - task.started_at).total_seconds() / 60,
    2
)

    return None

def calculate_estimate_difference(task: Task):
    actual_minutes = calculate_actual_minutes(task)

    if actual_minutes is None:
        return None

    return round(
        actual_minutes - task.estimated_minutes,
        2
    )

def calculate_estimate_ratio(task: Task):
    actual_minutes = calculate_actual_minutes(task)

    if actual_minutes is None:
        return None

    return round(
        actual_minutes / task.estimated_minutes,
        2
    )

def calculate_category_multiplier(
    category: TaskCategory,
    db: Session
):
    completed_tasks = (
        db.query(models.TaskDB)
        .filter(
            models.TaskDB.category == category.value,
            models.TaskDB.status == TaskStatus.DONE.value
        )
        .all()
    )

    ratios = []

    for task in completed_tasks:
        ratio = calculate_estimate_ratio(task)

        if ratio is not None:
            ratios.append(ratio)

    if not ratios:
        return 1.0

    return round(
        sum(ratios) / len(ratios),
        2
    )

def calculate_recommended_minutes(
    task,
    db: Session
):
    multiplier = calculate_category_multiplier(
        TaskCategory(task.category),
        db
    )

    return round(
        task.estimated_minutes * multiplier
    )

def calculate_deadline_risk(
    task,
    db: Session
):
    if task.due_at is None:
        return "none"

    now = datetime.now(task.due_at.tzinfo)

    hours_until_due = (
        task.due_at - now
    ).total_seconds() / 3600

    recommended_minutes = calculate_recommended_minutes(
        task,
        db
    )

    if hours_until_due <= 0:
        return "overdue"

    available_minutes = hours_until_due * 60

    if recommended_minutes > available_minutes:
        return "high"

    if recommended_minutes > available_minutes * 0.5:
        return "medium"

    return "low"

def calculate_task_progress(
    task_id: UUID,
    db: Session
):
    subtasks = (
        db.query(models.TaskDB)
        .filter(models.TaskDB.parent_task_id == task_id)
        .all()
    )

    if not subtasks:
        return None

    completed = [
        task for task in subtasks
        if task.status == TaskStatus.DONE.value
    ]

    return {
        "total": len(subtasks),
        "completed": len(completed),
        "percentage": round(
            len(completed) / len(subtasks) * 100
        )
    }

def is_task_blocked(task, db: Session):
    if task.depends_on_task_id is None:
        return False

    blocking_task = (
        db.query(models.TaskDB)
        .filter(models.TaskDB.id == task.depends_on_task_id)
        .first()
    )

    if blocking_task is None:
        return True

    return blocking_task.status != TaskStatus.DONE.value

def get_blocking_task(task, db: Session):
    if task.depends_on_task_id is None:
        return None

    return (
        db.query(models.TaskDB)
        .filter(models.TaskDB.id == task.depends_on_task_id)
        .first()
    )

def update_parent_status(task, db: Session):
    if task.parent_task_id is None:
        return

    parent = (
        db.query(models.TaskDB)
        .filter(models.TaskDB.id == task.parent_task_id)
        .first()
    )

    if parent is None:
        return

    subtasks = (
        db.query(models.TaskDB)
        .filter(models.TaskDB.parent_task_id == parent.id)
        .all()
    )

    if subtasks and all(
        subtask.status == TaskStatus.DONE.value
        for subtask in subtasks
    ):
        parent.status = TaskStatus.DONE.value
        parent.completed_at = datetime.now()

        db.commit()
        db.refresh(parent)