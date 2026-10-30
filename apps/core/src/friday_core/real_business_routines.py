"""Persistent, timezone-aware read-only skills and routines from the Grok playbook."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from threading import RLock
from typing import Callable
import uuid
from zoneinfo import ZoneInfo


@dataclass
class Routine:
    id: str
    skill: str
    timezone: str
    hour: int
    minute: int
    weekdays: list[int]
    paused: bool = True
    next_run: float | None = None
    last_slot: float | None = None


class BusinessRoutineEngine:
    SKILLS = {'lead_review','ad_report','weekly_sweep'}

    def __init__(self, directory: str | Path, execute: Callable) -> None:
        self.directory = Path(directory)
        self.directory.mkdir(parents=True,exist_ok=True)
        self.execute = execute
        self.lock = RLock()
        self.skills: dict[str,dict] = {}
        self.routines: dict[str,Routine] = {}
        path = self.directory/'routines.json'
        if path.exists():
            data = json.loads(path.read_text())
            self.skills = data['skills']
            self.routines = {key:Routine(**value) for key,value in data['routines'].items()}

    def save(self) -> None:
        path = self.directory/'routines.json'
        temporary = path.with_suffix('.tmp')
        temporary.write_text(json.dumps({'skills':self.skills,'routines':{key:asdict(r) for key,r in self.routines.items()}}))
        temporary.replace(path)

    def save_skill(self, name: str, kind: str, sources: list[str], parameters: dict, validated: bool = False) -> dict:
        if not name.strip() or kind not in self.SKILLS or not sources:
            raise ValueError('named supported skill and approved source IDs required')
        with self.lock:
            # A source/parameter change invalidates prior validation and pauses its schedules.
            self.skills[name] = {'kind':kind,'sources':sources,'parameters':parameters,'validated':validated,'read_only':True}
            for routine in self.routines.values():
                if routine.skill==name:
                    routine.paused = True
            self.save()
        return self.skills[name]

    def next_time(self, routine: Routine, after: float) -> float:
        zone = ZoneInfo(routine.timezone)
        day = datetime.fromtimestamp(after,zone).date()
        for offset in range(15):
            date = day+timedelta(days=offset)
            candidate = datetime(date.year,date.month,date.day,routine.hour,routine.minute,tzinfo=zone)
            # Nonexistent DST local times are skipped. Ambiguous time uses fold=0 once.
            roundtrip = datetime.fromtimestamp(candidate.timestamp(),zone)
            if date.weekday() in routine.weekdays and candidate.timestamp()>after and roundtrip.replace(tzinfo=None)==candidate.replace(tzinfo=None):
                return candidate.timestamp()
        raise ValueError('cannot find next scheduled time')

    def create(self, skill: str, timezone_: str, hour: int, minute: int, weekdays: list[int], now: float) -> dict:
        ZoneInfo(timezone_)
        if skill not in self.skills or not self.skills[skill]['validated']:
            raise ValueError('Run and validate the skill before scheduling')
        if not 0<=hour<=23 or not 0<=minute<=59 or not weekdays or any(type(d) is not int or not 0<=d<=6 for d in weekdays):
            raise ValueError('invalid schedule')
        with self.lock:
            routine = Routine(uuid.uuid4().hex,skill,timezone_,hour,minute,sorted(set(weekdays)),False)
            routine.next_run = self.next_time(routine,now)
            self.routines[routine.id] = routine
            self.save()
            return asdict(routine)

    def pause(self, identifier: str, paused: bool, now: float) -> dict:
        with self.lock:
            routine = self.routines[identifier]
            if not paused and not self.skills[routine.skill]['validated']:
                raise ValueError('skill must be validated before resuming')
            routine.paused = paused
            if not paused:
                routine.next_run = self.next_time(routine,now)
            self.save()
            return asdict(routine)

    def tick(self, now: float, read_source: Callable[[str],dict]) -> list[dict]:
        results = []
        with self.lock:
            for routine in self.routines.values():
                if routine.paused or routine.next_run is None or now<routine.next_run:
                    continue
                slot = routine.next_run
                # Claim slot durably before execution: a restart cannot send/re-run it twice.
                routine.last_slot = slot
                routine.next_run = self.next_time(routine,now)
                self.save()
                skill = self.skills[routine.skill]
                try:
                    sources = {}
                    for source in skill['sources']:
                        item = read_source(source)
                        if item.get('error') or 'updated_at' not in item or now-item['updated_at']>86400 or item['updated_at']>now:
                            raise ValueError('source unavailable or stale: '+source)
                        sources[source] = item['data']
                    result = self.execute(skill['kind'],sources,skill['parameters'])
                    record = {'routine_id':routine.id,'slot':slot,'status':'completed','result':result}
                except Exception as error:
                    record = {'routine_id':routine.id,'slot':slot,'status':'failed','error':str(error)[:500]}
                with (self.directory/'runs.jsonl').open('a') as handle:
                    handle.write(json.dumps(record)+'\n')
                results.append(record)
        return results
