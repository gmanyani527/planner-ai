# ============================================================
# SCHEDULING ENGINE
# ============================================================

from datetime import datetime, timedelta
from enum import Enum
from uuid import UUID

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session


# ============================================================
# COMMITMENT TYPES
# ============================================================

class CommitmentType(str, Enum):
    SLEEP = "sleep"
    CLASS = "class"
    WORK = "work"
    GYM = "gym"
    PERSONAL = "personal"


# ============================================================
# SCHEDULING MODELS
# ============================================================

class TimeWindow(BaseModel):
    start: datetime
    end: datetime


class CalendarEvent(BaseModel):
    start: datetime
    end: datetime

    commitment_type: CommitmentType = (
        CommitmentType.PERSONAL
    )


class WindowTest(BaseModel):
    start: datetime
    end: datetime

    total_minutes: int = Field(
        gt=0
    )

    block_minutes: int = Field(
        gt=0
    )

    buffer_minutes: int = Field(
        default=10,
        ge=0
    )


class ScheduleRequest(BaseModel):
    windows: list[TimeWindow]

    total_minutes: int = Field(
        gt=0
    )

    block_minutes: int = Field(
        gt=0
    )

    buffer_minutes: int = Field(
        default=10,
        ge=0
    )


class FreeWindowRequest(BaseModel):
    day_start: datetime
    day_end: datetime

    events: list[CalendarEvent]


class TaskScheduleRequest(BaseModel):
    day_start: datetime
    day_end: datetime

    events: list[CalendarEvent]

    total_minutes: int = Field(
        gt=0
    )

    block_minutes: int = Field(
        gt=0
    )

    buffer_minutes: int = Field(
        default=10,
        ge=0
    )


class TaskIdScheduleRequest(BaseModel):
    task_id: UUID

    day_start: datetime
    day_end: datetime

    events: list[CalendarEvent]

    buffer_minutes: int = Field(
        default=10,
        ge=0
    )


class DayScheduleRequest(BaseModel):
    day_start: datetime
    day_end: datetime

    events: list[CalendarEvent]

    buffer_minutes: int = Field(
        default=10,
        ge=0
    )


class DayCalendar(BaseModel):
    day_start: datetime
    day_end: datetime

    events: list[CalendarEvent] = []


class MultiDayScheduleRequest(BaseModel):
    days: list[DayCalendar]

    buffer_minutes: int = Field(
        default=10,
        ge=0
    )


# ============================================================
# BASIC TIME FUNCTIONS
# ============================================================

def calculate_window_minutes(
    window: TimeWindow
):
    return round(
        (
            window.end
            - window.start
        ).total_seconds() / 60
    )


def can_fit_block(
    block_minutes: int,
    window: TimeWindow
):
    available_minutes = (
        calculate_window_minutes(
            window
        )
    )

    return (
        block_minutes
        <= available_minutes
    )


# ============================================================
# TASK BLOCK SIZE
# ============================================================

def calculate_block_minutes(
    task,
    db: Session
):
    recommended_minutes = (
        calculate_recommended_minutes(
            task,
            db
        )
    )

    if recommended_minutes <= 30:
        return recommended_minutes

    if recommended_minutes <= 90:
        return 45

    return 60


def calculate_block_plan(
    task,
    db: Session
):
    recommended_minutes = (
        calculate_recommended_minutes(
            task,
            db
        )
    )

    block_minutes = (
        calculate_block_minutes(
            task,
            db
        )
    )

    full_blocks = (
        recommended_minutes
        // block_minutes
    )

    remaining_minutes = (
        recommended_minutes
        % block_minutes
    )

    return {
        "recommended_minutes":
            recommended_minutes,

        "block_minutes":
            block_minutes,

        "full_blocks":
            full_blocks,

        "remaining_minutes":
            remaining_minutes
    }


# ============================================================
# CREATE ONE SCHEDULED BLOCK
# ============================================================

def create_scheduled_block(
    window: TimeWindow,
    block_minutes: int
):
    if not can_fit_block(
        block_minutes,
        window
    ):
        return None

    start_time = window.start

    end_time = (
        start_time
        + timedelta(
            minutes=block_minutes
        )
    )

    return {
        "start":
            start_time,

        "end":
            end_time,

        "duration_minutes":
            block_minutes
    }


# ============================================================
# CREATE MULTIPLE BLOCKS INSIDE ONE WINDOW
# ============================================================

def create_blocks_in_window(
    window: TimeWindow,
    total_minutes: int,
    block_minutes: int,
    buffer_minutes: int = 10
):
    blocks = []

    current_start = (
        window.start
    )

    remaining_minutes = (
        total_minutes
    )

    while remaining_minutes > 0:

        current_block_minutes = min(
            block_minutes,
            remaining_minutes
        )

        current_end = (
            current_start
            + timedelta(
                minutes=current_block_minutes
            )
        )

        if current_end > window.end:
            break

        blocks.append({
            "start":
                current_start,

            "end":
                current_end,

            "duration_minutes":
                current_block_minutes
        })

        remaining_minutes -= (
            current_block_minutes
        )

        current_start = (
            current_end
            + timedelta(
                minutes=buffer_minutes
            )
        )

    return {
        "blocks":
            blocks,

        "remaining_minutes":
            remaining_minutes
    }


# ============================================================
# CREATE BLOCKS ACROSS MULTIPLE WINDOWS
# ============================================================

def create_blocks_across_windows(
    windows: list[TimeWindow],
    total_minutes: int,
    block_minutes: int,
    buffer_minutes: int = 10
):
    all_blocks = []

    remaining_minutes = (
        total_minutes
    )

    sorted_windows = sorted(
        windows,
        key=lambda window:
            window.start
    )

    for window in sorted_windows:

        if remaining_minutes <= 0:
            break

        result = (
            create_blocks_in_window(
                window=window,
                total_minutes=remaining_minutes,
                block_minutes=block_minutes,
                buffer_minutes=buffer_minutes
            )
        )

        all_blocks.extend(
            result["blocks"]
        )

        remaining_minutes = (
            result[
                "remaining_minutes"
            ]
        )

    return {
        "blocks":
            all_blocks,

        "remaining_minutes":
            remaining_minutes
    }


# ============================================================
# COMMITMENT PROTECTION
# ============================================================

def is_commitment_protected(
    event: CalendarEvent,
    allow_flexible_override: bool = False
):
    # These are always protected.
    if event.commitment_type in [
        CommitmentType.SLEEP,
        CommitmentType.CLASS,
        CommitmentType.WORK
    ]:
        return True

    # Gym and personal time can become
    # available during an emergency.
    if event.commitment_type in [
        CommitmentType.GYM,
        CommitmentType.PERSONAL
    ]:
        return not allow_flexible_override

    return True


# ============================================================
# DETERMINE WHETHER A TASK MAY OVERRIDE FLEXIBLE EVENTS
# ============================================================

def should_override_flexible_commitments_calendar(
    task,
    days: list[DayCalendar],
    db: Session,
    buffer_minutes: int = 10,
    reserve_percent: float = 0.20,
    max_scheduled_minutes: int = 360,
    max_task_minutes_per_day: int = 120
):
    risk = calculate_calendar_deadline_risk(
        task=task,
        days=days,
        db=db,
        buffer_minutes=buffer_minutes,
        reserve_percent=reserve_percent,
        max_scheduled_minutes=max_scheduled_minutes,
        max_task_minutes_per_day=max_task_minutes_per_day
    )

    return risk in [
        "high",
        "overdue"
    ]


# ============================================================
# FIND FREE WINDOWS
# ============================================================

def calculate_free_windows(
    day_start: datetime,
    day_end: datetime,
    events: list[CalendarEvent],
    allow_flexible_override: bool = False
):
    free_windows = []

    protected_events = [
        event
        for event in events
        if is_commitment_protected(
            event,
            allow_flexible_override
        )
    ]

    sorted_events = sorted(
        protected_events,
        key=lambda event:
            event.start
    )

    current_time = (
        day_start
    )

    for event in sorted_events:

        # Event ends before scheduling period.
        if event.end <= day_start:
            continue

        # Event starts after scheduling period.
        if event.start >= day_end:
            continue

        # Clip event to scheduling range.
        event_start = max(
            event.start,
            day_start
        )

        event_end = min(
            event.end,
            day_end
        )

        # Time before event is free.
        if event_start > current_time:

            free_windows.append(
                TimeWindow(
                    start=current_time,
                    end=event_start
                )
            )

        # Move current pointer past event.
        if event_end > current_time:
            current_time = event_end

    # Add free time after final event.
    if current_time < day_end:

        free_windows.append(
            TimeWindow(
                start=current_time,
                end=day_end
            )
        )

    return free_windows


# ============================================================
# DEADLINE WINDOW FILTER
# ============================================================

def filter_windows_before_deadline(
    windows: list[TimeWindow],
    due_at: datetime | None
):
    if due_at is None:
        return windows

    usable_windows = []

    for window in windows:

        # Entire window starts after deadline.
        if window.start >= due_at:
            continue

        window_end = min(
            window.end,
            due_at
        )

        if window.start < window_end:

            usable_windows.append(
                TimeWindow(
                    start=window.start,
                    end=window_end
                )
            )

    return usable_windows


# ============================================================
# TOTAL FREE MINUTES
# ============================================================

def calculate_total_free_minutes(
    windows: list[TimeWindow]
):
    return sum(
        calculate_window_minutes(
            window
        )
        for window in windows
    )


# ============================================================
# SCHEDULE FEASIBILITY
# ============================================================

def calculate_schedule_feasibility(
    total_minutes: int,
    windows: list[TimeWindow]
):
    available_minutes = (
        calculate_total_free_minutes(
            windows
        )
    )

    if available_minutes <= 0:

        return {
            "status":
                "impossible",

            "required_minutes":
                total_minutes,

            "available_minutes":
                0
        }

    if total_minutes > available_minutes:

        status = "high_risk"

    elif total_minutes > (
        available_minutes * 0.75
    ):

        status = "tight"

    else:

        status = "safe"

    return {
        "status":
            status,

        "required_minutes":
            total_minutes,

        "available_minutes":
            available_minutes
    }


# ============================================================
# REMOVE ALREADY CLAIMED BLOCKS FROM FREE WINDOWS
# ============================================================

def remove_scheduled_blocks_from_windows(
    windows: list[TimeWindow],
    blocks: list[dict]
):
    updated_windows = (
        windows.copy()
    )

    for block in blocks:

        block_start = (
            block["start"]
        )

        block_end = (
            block["end"]
        )

        new_windows = []

        for window in updated_windows:

            # No overlap.
            if (
                block_end <= window.start
                or block_start >= window.end
            ):
                new_windows.append(
                    window
                )

                continue

            # Free portion before scheduled block.
            if block_start > window.start:

                new_windows.append(
                    TimeWindow(
                        start=window.start,
                        end=block_start
                    )
                )

            # Free portion after scheduled block.
            if block_end < window.end:

                new_windows.append(
                    TimeWindow(
                        start=block_end,
                        end=window.end
                    )
                )

        updated_windows = (
            new_windows
        )

    return updated_windows


# ============================================================
# SORT TASKS BY PRIORITY
# ============================================================

def sort_tasks_for_scheduling(
    tasks,
    db: Session
):
    return sorted(
        tasks,
        key=lambda task:
            calculate_priority(
                task,
                db
            ),
        reverse=True
    )


# ============================================================
# SCHEDULE ONE DATABASE TASK FOR ONE DAY
# ============================================================

def generate_task_schedule(
    task,
    events: list[CalendarEvent],
    day_start: datetime,
    day_end: datetime,
    db: Session,
    buffer_minutes: int = 10
):
    recommended_minutes = (
        calculate_recommended_minutes(
            task,
            db
        )
    )

    block_minutes = (
        calculate_block_minutes(
            task,
            db
        )
    )

    allow_override = (
        should_override_flexible_commitments(
            task,
            db
        )
    )

    free_windows = (
        calculate_free_windows(
            day_start=day_start,
            day_end=day_end,
            events=events,
            allow_flexible_override=allow_override
        )
    )

    usable_windows = (
        filter_windows_before_deadline(
            free_windows,
            task.due_at
        )
    )

    feasibility = (
        calculate_schedule_feasibility(
            recommended_minutes,
            usable_windows
        )
    )

    result = (
        create_blocks_across_windows(
            windows=usable_windows,
            total_minutes=recommended_minutes,
            block_minutes=block_minutes,
            buffer_minutes=buffer_minutes
        )
    )

    return {
        "task_id":
            task.id,

        "title":
            task.title,

        "priority_score":
            calculate_priority(
                task,
                db
            ),

        "deadline_risk":
            calendar_risk,

        "recommended_minutes":
            recommended_minutes,

        "block_minutes":
            block_minutes,

        "buffer_minutes":
            buffer_minutes,

        "flexible_commitments_overridden":
            allow_override,

        "free_windows":
            usable_windows,

        "scheduled_blocks":
            result["blocks"],

        "remaining_minutes":
            result[
                "remaining_minutes"
            ],

        "fully_scheduled":
            result[
                "remaining_minutes"
            ] == 0,

        "feasibility":
            feasibility
    }


# ============================================================
# SCHEDULE MULTIPLE TASKS DURING ONE DAY
# ============================================================

def schedule_all_tasks(
    tasks,
    events: list[CalendarEvent],
    day_start: datetime,
    day_end: datetime,
    db: Session,
    buffer_minutes: int = 10
):
    sorted_tasks = (
        sort_tasks_for_scheduling(
            tasks,
            db
        )
    )

    schedule = []

    claimed_blocks = []

    for task in sorted_tasks:

        if (
            task.status
            == TaskStatus.DONE.value
        ):
            continue

        if is_task_blocked(
            task,
            db
        ):
            continue

        allow_override = (
            should_override_flexible_commitments(
                task,
                db
            )
        )

        free_windows = (
            calculate_free_windows(
                day_start=day_start,
                day_end=day_end,
                events=events,
                allow_flexible_override=allow_override
            )
        )

        # Remove blocks that tasks scheduled
        # earlier already claimed.
        free_windows = (
            remove_scheduled_blocks_from_windows(
                free_windows,
                claimed_blocks
            )
        )

        # Do not schedule this task
        # after its own deadline.
        usable_windows = (
            filter_windows_before_deadline(
                free_windows,
                task.due_at
            )
        )

        recommended_minutes = (
            calculate_recommended_minutes(
                task,
                db
            )
        )

        block_minutes = (
            calculate_block_minutes(
                task,
                db
            )
        )

        result = (
            create_blocks_across_windows(
                windows=usable_windows,
                total_minutes=recommended_minutes,
                block_minutes=block_minutes,
                buffer_minutes=buffer_minutes
            )
        )

        task_blocks = (
            result["blocks"]
        )

        schedule.append({
            "task_id":
                task.id,

            "title":
                task.title,

            "priority_score":
                calculate_priority(
                    task,
                    db
                ),

            "deadline_risk":
                calendar_risk,

            "recommended_minutes":
                recommended_minutes,

            "block_minutes":
                block_minutes,

            "flexible_commitments_overridden":
                allow_override,

            "scheduled_blocks":
                task_blocks,

            "remaining_minutes":
                result[
                    "remaining_minutes"
                ],

            "fully_scheduled":
                result[
                    "remaining_minutes"
                ] == 0
        })

        claimed_blocks.extend(
            task_blocks
        )

    normal_free_windows = (
        calculate_free_windows(
            day_start=day_start,
            day_end=day_end,
            events=events,
            allow_flexible_override=False
        )
    )

    remaining_free_windows = (
        remove_scheduled_blocks_from_windows(
            normal_free_windows,
            claimed_blocks
        )
    )

    return {
        "schedule":
            schedule,

        "remaining_free_windows":
            remaining_free_windows
    }


# ============================================================
# SCHEDULE ONE TASK ACROSS MULTIPLE DAYS
# ============================================================

def schedule_task_across_days(
    task,
    days: list[DayCalendar],
    db: Session,
    buffer_minutes: int = 10
):
    recommended_minutes = (
        calculate_recommended_minutes(
            task,
            db
        )
    )

    block_minutes = (
        calculate_block_minutes(
            task,
            db
        )
    )

    remaining_minutes = (
        recommended_minutes
    )

    scheduled_days = []

    sorted_days = sorted(
        days,
        key=lambda day:
            day.day_start
    )

    allow_override = (
        should_override_flexible_commitments(
            task,
            db
        )
    )

    for day in sorted_days:

        if remaining_minutes <= 0:
            break

        # If this entire day starts
        # after the deadline, stop.
        if (
            task.due_at is not None
            and day.day_start >= task.due_at
        ):
            break

        free_windows = (
            calculate_free_windows(
                day_start=day.day_start,
                day_end=day.day_end,
                events=day.events,
                allow_flexible_override=allow_override
            )
        )

        usable_windows = (
            filter_windows_before_deadline(
                free_windows,
                task.due_at
            )
        )

        result = (
            create_blocks_across_windows(
                windows=usable_windows,
                total_minutes=remaining_minutes,
                block_minutes=block_minutes,
                buffer_minutes=buffer_minutes
            )
        )

        task_blocks = (
            result["blocks"]
        )

        remaining_minutes = (
            result[
                "remaining_minutes"
            ]
        )

        if task_blocks:

            scheduled_days.append({
                "date":
                    day.day_start.date(),

                "blocks":
                    task_blocks
            })

    return {
        "task_id":
            task.id,

        "title":
            task.title,

        "priority_score":
            calculate_priority(
                task,
                db
            ),

        "deadline_risk":
            calendar_risk,

        "recommended_minutes":
            recommended_minutes,

        "block_minutes":
            block_minutes,

        "flexible_commitments_overridden":
            allow_override,

        "scheduled_days":
            scheduled_days,

        "remaining_minutes":
            remaining_minutes,

        "fully_scheduled":
            remaining_minutes == 0
    }


# ============================================================
# SCHEDULE ALL TASKS ACROSS MULTIPLE DAYS
# ============================================================

def schedule_all_tasks_across_days(
    tasks,
    days: list[DayCalendar],
    db: Session,
    buffer_minutes: int = 10,
    reserve_percent: float = 0.20,
    max_scheduled_minutes: int = 360,
    max_task_minutes_per_day: int = 120
):
    sorted_tasks = (
        sort_tasks_for_scheduling(
            tasks,
            db
        )
    )

    sorted_days = sorted(
        days,
        key=lambda day:
            day.day_start
    )

    full_schedule = []

    claimed_blocks_by_day = {}

    daily_capacity_by_day = {}

    # ========================================================
    # PREPARE EACH DAY
    # ========================================================

    for day in sorted_days:

        day_key = (
            day.day_start.date()
        )

        claimed_blocks_by_day[
            day_key
        ] = []

        # Calculate NORMAL free time.
        # This protects gym/personal time.
        normal_free_windows = (
            calculate_free_windows(
                day_start=day.day_start,
                day_end=day.day_end,
                events=day.events,
                allow_flexible_override=False
            )
        )

        daily_capacity_by_day[
            day_key
        ] = (
            calculate_daily_work_capacity(
                windows=normal_free_windows,
                reserve_percent=reserve_percent,
                max_scheduled_minutes=max_scheduled_minutes
            )
        )

    # ========================================================
    # SCHEDULE TASKS BY PRIORITY
    # ========================================================

    for task in sorted_tasks:

        if (
            task.status
            == TaskStatus.DONE.value
        ):
            continue

        if is_task_blocked(
            task,
            db
        ):
            continue

        recommended_minutes = (
            calculate_recommended_minutes(
                task,
                db
            )
        )

        block_minutes = (
            calculate_block_minutes(
                task,
                db
            )
        )

        remaining_minutes = (
            recommended_minutes
        )

        task_schedule = []

        calendar_risk = (
        calculate_calendar_deadline_risk(
            task=task,
            days=sorted_days,
            db=db,
            buffer_minutes=buffer_minutes,
            reserve_percent=reserve_percent,
            max_scheduled_minutes=max_scheduled_minutes,
            max_task_minutes_per_day=max_task_minutes_per_day
            )
        )

        allow_override = (
            calendar_risk
            in [
            "high",
            "overdue"
            ]
        )

        # ====================================================
        # TRY EACH DAY
        # ====================================================

        for day in sorted_days:

            if remaining_minutes <= 0:
                break

            if (
                task.due_at is not None
                and day.day_start
                >= task.due_at
            ):
                break

            day_key = (
                day.day_start.date()
            )

            # =================================================
            # FIND FREE TIME FOR THIS TASK
            # =================================================

            free_windows = (
                calculate_free_windows(
                    day_start=day.day_start,
                    day_end=day.day_end,
                    events=day.events,
                    allow_flexible_override=allow_override
                )
            )

            free_windows = (
                remove_scheduled_blocks_from_windows(
                    free_windows,
                    claimed_blocks_by_day[
                        day_key
                    ]
                )
            )

            usable_windows = (
                filter_windows_before_deadline(
                    free_windows,
                    task.due_at
                )
            )

            # =================================================
            # HOW MUCH WORK HAS TODAY ALREADY RECEIVED?
            # =================================================

            already_scheduled_minutes = (
                calculate_claimed_minutes(
                    claimed_blocks_by_day[
                        day_key
                    ]
                )
            )

            daily_capacity = (
                daily_capacity_by_day[
                    day_key
                ]
            )

            remaining_day_capacity = max(
                0,
                daily_capacity
                - already_scheduled_minutes
            )

            if remaining_day_capacity <= 0:
                continue

            # =================================================
            # HOW MUCH OF THIS TASK MAY GO TODAY?
            # =================================================

            minutes_to_schedule_today = (
                calculate_task_daily_allowance(
                    remaining_task_minutes=remaining_minutes,
                    remaining_day_capacity=remaining_day_capacity,
                    max_task_minutes_per_day=max_task_minutes_per_day,
                    allow_override=allow_override
                )
            )

            if minutes_to_schedule_today <= 0:
                continue

            # =================================================
            # SCHEDULE THAT PORTION
            # =================================================

            result = (
                create_blocks_across_windows(
                    windows=usable_windows,
                    total_minutes=minutes_to_schedule_today,
                    block_minutes=block_minutes,
                    buffer_minutes=buffer_minutes
                )
            )

            task_blocks = (
                result["blocks"]
            )

            # Actual minutes successfully scheduled.
            scheduled_today = (
                minutes_to_schedule_today
                - result[
                    "remaining_minutes"
                ]
            )

            remaining_minutes -= (
                scheduled_today
            )

            if task_blocks:

                claimed_blocks_by_day[
                    day_key
                ].extend(
                    task_blocks
                )

                task_schedule.append({
                    "date":
                        day_key,

                    "scheduled_minutes":
                        scheduled_today,

                    "daily_capacity":
                        daily_capacity,

                    "blocks":
                        task_blocks
                })

        # ====================================================
        # SAVE RESULT FOR THIS TASK
        # ====================================================

        full_schedule.append({
            "task_id":
                task.id,

            "title":
                task.title,

            "priority_score":
                calculate_priority(
                    task,
                    db
                ),

            "deadline_risk":
                calendar_risk, 
                

            "recommended_minutes":
                recommended_minutes,

            "block_minutes":
                block_minutes,

            "flexible_commitments_overridden":
                allow_override,

            "scheduled_days":
                task_schedule,

            "remaining_minutes":
                remaining_minutes,

            "fully_scheduled":
                remaining_minutes == 0,

            "required_minutes":
                recommended_minutes,

            "available_minutes_before_deadline":
                calculate_available_task_minutes_before_deadline(
                task=task,
                days=sorted_days,
                db=db,
                buffer_minutes=buffer_minutes,
                reserve_percent=reserve_percent,
                max_scheduled_minutes=max_scheduled_minutes,
                max_task_minutes_per_day=max_task_minutes_per_day
            ),
        })

    # ========================================================
    # DAILY SUMMARY
    # ========================================================

    daily_summary = []

    for day in sorted_days:

        day_key = (
            day.day_start.date()
        )

        scheduled_minutes = (
            calculate_claimed_minutes(
                claimed_blocks_by_day[
                    day_key
                ]
            )
        )

        capacity = (
            daily_capacity_by_day[
                day_key
            ]
        )

        daily_summary.append({
            "date":
                day_key,

            "scheduled_minutes":
                scheduled_minutes,

            "daily_capacity":
                capacity,

            "remaining_capacity":
                max(
                    0,
                    capacity
                    - scheduled_minutes
                )
        })

    return {
        "schedule":
            full_schedule,

        "daily_summary":
            daily_summary,

        "claimed_blocks_by_day":
            claimed_blocks_by_day
    }


# ============================================================
# ENDPOINT: TEST ONE WINDOW
# ============================================================

@app.post("/schedule/window")
def test_time_window(
    data: WindowTest
):
    window = TimeWindow(
        start=data.start,
        end=data.end
    )

    result = (
        create_blocks_in_window(
            window=window,
            total_minutes=data.total_minutes,
            block_minutes=data.block_minutes,
            buffer_minutes=data.buffer_minutes
        )
    )

    return {
        "start":
            window.start,

        "end":
            window.end,

        "available_minutes":
            calculate_window_minutes(
                window
            ),

        "blocks":
            result["blocks"],

        "remaining_minutes":
            result[
                "remaining_minutes"
            ]
    }


# ============================================================
# ENDPOINT: TEST MULTIPLE WINDOWS
# ============================================================

@app.post("/schedule/windows")
def test_multiple_windows(
    data: ScheduleRequest
):
    result = (
        create_blocks_across_windows(
            windows=data.windows,
            total_minutes=data.total_minutes,
            block_minutes=data.block_minutes,
            buffer_minutes=data.buffer_minutes
        )
    )

    return {
        "blocks":
            result["blocks"],

        "remaining_minutes":
            result[
                "remaining_minutes"
            ]
    }


# ============================================================
# ENDPOINT: CALCULATE FREE WINDOWS
# ============================================================

@app.post("/schedule/free-windows")
def get_free_windows(
    data: FreeWindowRequest
):
    windows = (
        calculate_free_windows(
            day_start=data.day_start,
            day_end=data.day_end,
            events=data.events
        )
    )

    return {
        "free_windows":
            windows
    }


# ============================================================
# ENDPOINT: MANUAL TASK SCHEDULING
# ============================================================

@app.post("/schedule/task")
def schedule_task(
    data: TaskScheduleRequest
):
    free_windows = (
        calculate_free_windows(
            day_start=data.day_start,
            day_end=data.day_end,
            events=data.events
        )
    )

    result = (
        create_blocks_across_windows(
            windows=free_windows,
            total_minutes=data.total_minutes,
            block_minutes=data.block_minutes,
            buffer_minutes=data.buffer_minutes
        )
    )

    feasibility = (
        calculate_schedule_feasibility(
            data.total_minutes,
            free_windows
        )
    )

    return {
        "free_windows":
            free_windows,

        "scheduled_blocks":
            result["blocks"],

        "remaining_minutes":
            result[
                "remaining_minutes"
            ],

        "feasibility":
            feasibility
    }


# ============================================================
# ENDPOINT: SCHEDULE ONE POSTGRESQL TASK
# ============================================================

@app.post("/schedule/task-from-db")
def schedule_task_from_db(
    data: TaskIdScheduleRequest,
    db: Session = Depends(get_db)
):
    task = (
        db.query(
            models.TaskDB
        )
        .filter(
            models.TaskDB.id
            == data.task_id
        )
        .first()
    )

    if task is None:

        raise HTTPException(
            status_code=404,
            detail="Task not found"
        )

    if (
        task.status
        == TaskStatus.DONE.value
    ):

        raise HTTPException(
            status_code=409,
            detail=(
                "Completed tasks "
                "cannot be scheduled"
            )
        )

    if is_task_blocked(
        task,
        db
    ):

        raise HTTPException(
            status_code=409,
            detail=(
                "Task dependency "
                "is not completed"
            )
        )

    return generate_task_schedule(
        task=task,
        events=data.events,
        day_start=data.day_start,
        day_end=data.day_end,
        db=db,
        buffer_minutes=data.buffer_minutes
    )


# ============================================================
# ENDPOINT: GENERATE A COMPLETE DAY
# ============================================================

@app.post("/schedule/day")
def schedule_day(
    data: DayScheduleRequest,
    db: Session = Depends(get_db)
):
    tasks = (
        db.query(
            models.TaskDB
        )
        .filter(
            models.TaskDB.status
            != TaskStatus.DONE.value
        )
        .all()
    )

    return schedule_all_tasks(
        tasks=tasks,
        events=data.events,
        day_start=data.day_start,
        day_end=data.day_end,
        db=db,
        buffer_minutes=data.buffer_minutes
    )


# ============================================================
# ENDPOINT: MULTI-DAY SCHEDULING
# ============================================================

@app.post("/schedule/multi-day")
def schedule_multi_day(
    data: MultiDayScheduleRequest,
    db: Session = Depends(get_db)
):
    tasks = (
        db.query(
            models.TaskDB
        )
        .filter(
            models.TaskDB.status
            != TaskStatus.DONE.value
        )
        .all()
    )

    return (
        schedule_all_tasks_across_days(
            tasks=tasks,
            days=data.days,
            db=db,
            buffer_minutes=data.buffer_minutes,

            reserve_percent=(
                data.workload.reserve_percent
            ),

            max_scheduled_minutes=(
                data.workload.max_scheduled_minutes
            ),

            max_task_minutes_per_day=(
                data.workload.max_task_minutes_per_day
            )
        )
    )
# ============================================================
# DAILY WORKLOAD LIMITS / SCHEDULE RESERVE
# ============================================================

class DailyWorkloadSettings(BaseModel):
    reserve_percent: float = Field(
        default=0.20,
        ge=0,
        le=0.90
    )

    max_scheduled_minutes: int = Field(
        default=360,
        ge=30
    )

    max_task_minutes_per_day: int = Field(
        default=120,
        ge=15
    )


class MultiDayScheduleRequest(BaseModel):
    days: list[DayCalendar]

    buffer_minutes: int = Field(
        default=10,
        ge=0
    )

    workload: DailyWorkloadSettings = Field(
        default_factory=DailyWorkloadSettings
    )


def calculate_daily_work_capacity(
    windows: list[TimeWindow],
    reserve_percent: float,
    max_scheduled_minutes: int
):
    total_free_minutes = (
        calculate_total_free_minutes(
            windows
        )
    )

    usable_after_reserve = round(
        total_free_minutes
        * (1 - reserve_percent)
    )

    return min(
        usable_after_reserve,
        max_scheduled_minutes
    )

def calculate_claimed_minutes(
    blocks: list[dict]
):
    return sum(
        block["duration_minutes"]
        for block in blocks
    )

def calculate_task_daily_allowance(
    remaining_task_minutes: int,
    remaining_day_capacity: int,
    max_task_minutes_per_day: int,
    allow_override: bool = False
):
    if remaining_day_capacity <= 0:
        return 0

    if allow_override:
        task_cap = remaining_task_minutes
    else:
        task_cap = min(
            remaining_task_minutes,
            max_task_minutes_per_day
        )

    return min(
        task_cap,
        remaining_day_capacity
    )

def calculate_available_task_minutes_before_deadline(
    task,
    days: list[DayCalendar],
    db: Session,
    buffer_minutes: int = 10,
    reserve_percent: float = 0.20,
    max_scheduled_minutes: int = 360,
    max_task_minutes_per_day: int = 120
):
    if task.due_at is None:
        return None

    total_available_minutes = 0

    block_minutes = calculate_block_minutes(
        task,
        db
    )

    sorted_days = sorted(
        days,
        key=lambda day: day.day_start
    )

    for day in sorted_days:

        # Entire day is after deadline.
        if day.day_start >= task.due_at:
            break

        # ----------------------------------------------------
        # Get normal free time.
        #
        # Do NOT override gym/personal yet.
        # We want deadline risk to tell us whether
        # normal available time is enough first.
        # ----------------------------------------------------

        free_windows = calculate_free_windows(
            day_start=day.day_start,
            day_end=day.day_end,
            events=day.events,
            allow_flexible_override=False
        )

        # Remove anything after the deadline.
        usable_windows = filter_windows_before_deadline(
            free_windows,
            task.due_at
        )

        if not usable_windows:
            continue

        # ----------------------------------------------------
        # Calculate how much work we allow on this day.
        # ----------------------------------------------------

        daily_capacity = calculate_daily_work_capacity(
            windows=usable_windows,
            reserve_percent=reserve_percent,
            max_scheduled_minutes=max_scheduled_minutes
        )

        task_capacity_today = min(
            daily_capacity,
            max_task_minutes_per_day
        )

        if task_capacity_today <= 0:
            continue

        # ----------------------------------------------------
        # Actually simulate fitting blocks into the windows.
        #
        # This matters because:
        #
        # 9:00–9:20 may technically be 20 free minutes,
        # but a 45-minute study block cannot fit there.
        # ----------------------------------------------------

        result = create_blocks_across_windows(
            windows=usable_windows,
            total_minutes=task_capacity_today,
            block_minutes=block_minutes,
            buffer_minutes=buffer_minutes
        )

        scheduled_minutes = (
            task_capacity_today
            - result["remaining_minutes"]
        )

        total_available_minutes += scheduled_minutes

    return total_available_minutes

def calculate_calendar_deadline_risk(
    task,
    days: list[DayCalendar],
    db: Session,
    buffer_minutes: int = 10,
    reserve_percent: float = 0.20,
    max_scheduled_minutes: int = 360,
    max_task_minutes_per_day: int = 120
):
    if task.due_at is None:
        return "none"

    now = datetime.now(
        task.due_at.tzinfo
    )

    if task.due_at <= now:
        return "overdue"

    required_minutes = calculate_recommended_minutes(
        task,
        db
    )

    available_minutes = (
        calculate_available_task_minutes_before_deadline(
            task=task,
            days=days,
            db=db,
            buffer_minutes=buffer_minutes,
            reserve_percent=reserve_percent,
            max_scheduled_minutes=max_scheduled_minutes,
            max_task_minutes_per_day=max_task_minutes_per_day
        )
    )

    if available_minutes is None:
        return "none"

    if available_minutes <= 0:
        return "high"

    # Cannot fit before deadline.
    if required_minutes > available_minutes:
        return "high"

    usage_ratio = (
        required_minutes
        / available_minutes
    )

    # Task consumes most available time.
    if usage_ratio >= 0.75:
        return "medium"

    return "low"

class RescheduleRequest(BaseModel):
    days: list[DayCalendar]

    current_time: datetime

    completed_block_ids: list[str] = Field(
        default_factory=list
    )

    buffer_minutes: int = Field(
        default=10,
        ge=0
    )

    workload: DailyWorkloadSettings = Field(
        default_factory=DailyWorkloadSettings
    )

def trim_windows_from_current_time(
    windows: list[TimeWindow],
    current_time: datetime
):
    updated_windows = []

    for window in windows:

        # Entire window is already in the past.
        if window.end <= current_time:
            continue

        # Window started earlier but still has
        # future time remaining.
        if (
            window.start < current_time
            < window.end
        ):
            updated_windows.append(
                TimeWindow(
                    start=current_time,
                    end=window.end
                )
            )

            continue

        # Entire window is still in the future.
        updated_windows.append(
            window
        )

    return updated_windows

def trim_days_from_current_time(
    days: list[DayCalendar],
    current_time: datetime
):
    future_days = []

    for day in days:

        # Entire scheduling day already passed.
        if day.day_end <= current_time:
            continue

        # We are currently inside this day.
        if (
            day.day_start
            <= current_time
            < day.day_end
        ):
            future_days.append(
                DayCalendar(
                    day_start=current_time,
                    day_end=day.day_end,
                    events=day.events
                )
            )

            continue

        # Future day stays unchanged.
        future_days.append(
            day
        )

    return future_days

def reschedule_remaining_tasks(
    tasks,
    days: list[DayCalendar],
    current_time: datetime,
    db: Session,
    buffer_minutes: int = 10,
    reserve_percent: float = 0.20,
    max_scheduled_minutes: int = 360,
    max_task_minutes_per_day: int = 120
):
    future_days = trim_days_from_current_time(
        days,
        current_time
    )

    if not future_days:
        return {
            "schedule": [],
            "daily_summary": [],
            "message": "No future scheduling time available"
        }

    unfinished_tasks = [
        task
        for task in tasks
        if task.status != TaskStatus.DONE.value
    ]

    return schedule_all_tasks_across_days(
        tasks=unfinished_tasks,
        days=future_days,
        db=db,
        buffer_minutes=buffer_minutes,
        reserve_percent=reserve_percent,
        max_scheduled_minutes=max_scheduled_minutes,
        max_task_minutes_per_day=max_task_minutes_per_day
    )

@app.post("/schedule/reschedule")
def reschedule(
    data: RescheduleRequest,
    db: Session = Depends(get_db)
):
    tasks = (
        db.query(models.TaskDB)
        .filter(
            models.TaskDB.status
            != TaskStatus.DONE.value
        )
        .all()
    )

    return reschedule_remaining_tasks(
        tasks=tasks,
        days=data.days,
        current_time=data.current_time,
        db=db,
        buffer_minutes=data.buffer_minutes,
        reserve_percent=data.workload.reserve_percent,
        max_scheduled_minutes=(
            data.workload.max_scheduled_minutes
        ),
        max_task_minutes_per_day=(
            data.workload.max_task_minutes_per_day
        )
    )