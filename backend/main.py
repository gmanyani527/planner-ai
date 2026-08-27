from fastapi import FastAPI
from pydantic import BaseModel, Field
from enum import Enum


app = FastAPI()

class TaskCategory(str, Enum):
    SCHOOL = "school"
    EXAM = "exam"
    INTERNSHIP = "internship"
    DSA = "dsa"
    PROJECT = "project"
    PERSONAL = "personal"


class Task(BaseModel):
    title: str = Field(min_length=1)
    category: TaskCategory
    estimated_minutes: int = Field(ge=5)
    importance: int = Field(ge=1, le=10)

tasks = [] 
@app.get("/")

def home():
    return {"message" : "Planner AI is running"}


@app.get("/tasks")
def get_tasks():
    return tasks

@app.post("/tasks")
def create_task(task: Task):
    tasks.append(task)
    return tasks