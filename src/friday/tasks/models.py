from enum import Enum
from typing import Optional, Dict, Any
from pydantic import BaseModel, Field
from datetime import datetime
import uuid

class ScheduleType(str, Enum):
    ONE_TIME = "one_time"
    INTERVAL = "interval"
    DAILY = "daily"
    WEEKLY = "weekly"

class SafetyLevel(str, Enum):
    SAFE = "safe"
    SENSITIVE = "sensitive"
    DANGEROUS = "dangerous"

class Task(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    schedule_type: ScheduleType
    schedule_params: Dict[str, Any]  # e.g. {"run_at": "2026-08-20T10:00:00"} or {"interval_seconds": 3600}
    enabled: bool = True
    safety_level: SafetyLevel = SafetyLevel.SAFE
    max_calls: int = 100
    retry_limit: int = 3
    daily_cap: Optional[int] = None
    circuit_breaker_threshold: int = 5
    run_count: int = 0
    failure_streak: int = 0
    last_run: Optional[datetime] = None

class TaskRunLog(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    task_id: str
    run_time: datetime = Field(default_factory=datetime.utcnow)
    success: bool
    result: Optional[Any] = None
    error: Optional[str] = None
    attempt: int = 1
