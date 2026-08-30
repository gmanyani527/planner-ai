from fastapi import FastAPI
from pydantic import BaseModel, Field
from enum import Enum
from datetime import datetime
from uuid import UUID, uuid4
from fastapi import FastAPI, HTTPException


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

tasks = [] 
@app.get("/")

def home():
    return {"message" : "Planner AI is running"}

@app.get("/analytics/category/{category}")
def get_category_analytics(category: TaskCategory):
    multiplier = calculate_category_multiplier(category)

    return {
        "category": category,
        "estimate_multiplier": multiplier
    }


@app.get("/tasks")
def get_tasks(status: TaskStatus | None = None):
    filtered_tasks = tasks

    if status:
        filtered_tasks = [
            task for task in tasks
            if task.status == status
        ]

    sorted_tasks = sorted(
        filtered_tasks,
        key=calculate_priority,
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
    "recommended_minutes": calculate_recommended_minutes(task),
    "actual_minutes": calculate_actual_minutes(task),
    "estimate_difference": calculate_estimate_difference(task),
    "estimate_ratio": calculate_estimate_ratio(task),
    "deadline_risk": calculate_deadline_risk(task),
    "priority_score": calculate_priority(task),
    "parent_task_id": task.parent_task_id,
    "blocked": is_task_blocked(task),
    "blocked_by": (
        get_blocking_task(task).title
        if get_blocking_task(task)
        else None
    ),
        }
        for task in sorted_tasks
    ]

@app.get("/tasks/{task_id}/subtasks")
def get_subtasks(task_id: UUID):
    subtasks = [
        task for task in tasks
        if task.parent_task_id == task_id
    ]

    return subtasks

@app.get("/tasks/next")
def get_next_task():
    unfinished_tasks = [
        task for task in tasks
        if task.status != TaskStatus.DONE
        and not is_task_blocked(task)
    ]

    if not unfinished_tasks:
        return {"message": "No unfinished tasks"}

    next_task = max(
        unfinished_tasks,
        key=calculate_priority
    )

    return {
        "id": next_task.id,
        "title": next_task.title,
        "status": next_task.status,
        "priority_score": calculate_priority(next_task)
    }
@app.get("/tasks/current")
def get_current_task():
    for task in tasks:
        if task.status == TaskStatus.IN_PROGRESS:
            return task

    return {"message": "No task currently in progress"}

@app.get("/tasks/{task_id}/progress")
def get_task_progress(task_id: UUID):
    progress = calculate_task_progress(task_id)

    if progress is None:
        return {
            "total": 0,
            "completed": 0,
            "percentage": 0
        }

    return progress

@app.post("/tasks")
def create_task(task: TaskCreate):
    new_task = Task(
        **task.model_dump(),
        id=uuid4()
    )
    tasks.append(new_task)
    return new_task

@app.patch("/tasks/{task_id}/done")
def complete_task(task_id: UUID):
    for task in tasks:
        if task.id == task_id:
            task.status = TaskStatus.DONE
            task.completed_at = datetime.now()

            update_parent_status(task)

            return task

    raise HTTPException(
        status_code=404,
        detail="Task not found"
    )

@app.patch("/tasks/{task_id}/start")
def start_task(task_id: UUID):

    # First: make sure another task is not already active
    for task in tasks:
        if task.status == TaskStatus.IN_PROGRESS and task.id != task_id:
            raise HTTPException(
                status_code=409,
                detail=f"{task.title} is already in progress"
            )

    # Second: find the task the user is trying to start
    for task in tasks:
        if task.id == task_id:

            # Make sure its dependency is finished
            if is_task_blocked(task):
                raise HTTPException(
                    status_code=409,
                    detail="Task dependency is not completed"
                )

            task.status = TaskStatus.IN_PROGRESS
            task.started_at = datetime.now()

            return task

    # If we never found the task ID
    raise HTTPException(
        status_code=404,
        detail="Task not found"
    )

def calculate_priority(task: Task):
    score = task.importance * 10

    if risk == "overdue":
        score += 50
    elif risk == "high":
        score += 30
    elif risk == "medium":
        score += 15

    if task.category == TaskCategory.EXAM:
        score += 20 
    elif task.category == TaskCategory.SCHOOL:
        score += 15
    elif task.category == TaskCategory.INTERNSHIP:
        score += 10
    elif task.category == TaskCategory.DSA:
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

def calculate_category_multiplier(category: TaskCategory):
    ratios = []

    for task in tasks:
        if task.category == category and task.status == TaskStatus.DONE:
            ratio = calculate_estimate_ratio(task)

            if ratio is not None:
                ratios.append(ratio)

    if not ratios:
        return 1.0

    return round(
        sum(ratios) / len(ratios),
        2
    )

def calculate_recommended_minutes(task: Task):
    multiplier = calculate_category_multiplier(task.category)

    return round(
        task.estimated_minutes * multiplier
    )

def calculate_deadline_risk(task: Task):
    if task.due_at is None:
        return "none"

    now = datetime.now(task.due_at.tzinfo)

    hours_until_due = (
        task.due_at - now
    ).total_seconds() / 3600

    recommended_minutes = calculate_recommended_minutes(task)

    if hours_until_due <= 0:
        return "overdue"

    available_minutes = hours_until_due * 60

    if recommended_minutes > available_minutes:
        return "high"

    if recommended_minutes > available_minutes * 0.5:
        return "medium"

    return "low"

def calculate_task_progress(task_id: UUID):
    subtasks = [
        task for task in tasks
        if task.parent_task_id == task_id
    ]

    if not subtasks:
        return None

    completed = [
        task for task in subtasks
        if task.status == TaskStatus.DONE
    ]

    return {
        "total": len(subtasks),
        "completed": len(completed),
        "percentage": round(
            len(completed) / len(subtasks) * 100
        )
    }

def is_task_blocked(task: Task):
    if task.depends_on_task_id is None:
        return False

    for other_task in tasks:
        if other_task.id == task.depends_on_task_id:
            return other_task.status != TaskStatus.DONE

    return True

def get_blocking_task(task: Task):
    if task.depends_on_task_id is None:
        return None

    for other_task in tasks:
        if other_task.id == task.depends_on_task_id:
            return other_task

    return None

def update_parent_status(task: Task):
    if task.parent_task_id is None:
        return

    parent = None

    for other_task in tasks:
        if other_task.id == task.parent_task_id:
            parent = other_task
            break

    if parent is None:
        return

    subtasks = [
        other_task for other_task in tasks
        if other_task.parent_task_id == parent.id
    ]

    if subtasks and all(
        subtask.status == TaskStatus.DONE
        for subtask in subtasks
    ):
        parent.status = TaskStatus.DONE
        parent.completed_at = datetime.now()