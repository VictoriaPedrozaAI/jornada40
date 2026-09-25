"""Shift model + LFT jornada classification (Art. 60-61).

A shift belongs to the calendar day it starts on (a 22:00-06:00 shift on Monday is a Monday shift).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

NIGHT_START = time(20, 0)  # Art. 60: nocturna window 20:00-06:00
NIGHT_END = time(6, 0)
MIXTA_NIGHT_THRESHOLD_H = 3.5  # >= 3.5 h of night -> nocturna
JORNADA_CODE = {"diurna": "D", "mixta": "M", "nocturna": "N"}  # user-facing badge
DAILY_MAX_H = {"diurna": 8.0, "mixta": 7.5, "nocturna": 7.0}  # Art. 61


@dataclass(frozen=True)
class ShiftDef:
    code: str
    start: time
    end: time  # end <= start means the shift crosses midnight
    description: str = ""

    @property
    def hours(self) -> float:
        s = datetime.combine(date.min, self.start)
        e = datetime.combine(date.min, self.end)
        if e <= s:
            e += timedelta(days=1)
        return (e - s).total_seconds() / 3600


@dataclass(frozen=True)
class Shift:
    employee_id: str
    day: date
    code: str
    start: datetime
    end: datetime

    @classmethod
    def from_def(cls, employee_id: str, day: date, d: ShiftDef) -> "Shift":
        s = datetime.combine(day, d.start)
        e = datetime.combine(day, d.end)
        if e <= s:
            e += timedelta(days=1)
        return cls(employee_id, day, d.code, s, e)

    @property
    def hours(self) -> float:
        return (self.end - self.start).total_seconds() / 3600

    @property
    def night_hours(self) -> float:
        total = 0.0
        d = self.start.date() - timedelta(days=1)
        while datetime.combine(d, NIGHT_START) < self.end:
            ws = datetime.combine(d, NIGHT_START)
            we = datetime.combine(d + timedelta(days=1), NIGHT_END)
            overlap = (min(self.end, we) - max(self.start, ws)).total_seconds()
            total += max(0.0, overlap) / 3600
            d += timedelta(days=1)
        return total

    @property
    def jornada_type(self) -> str:
        n = self.night_hours
        if n == 0:
            return "diurna"
        return "nocturna" if n >= MIXTA_NIGHT_THRESHOLD_H else "mixta"

    @property
    def jornada_code(self) -> str:
        """D/M/N badge derived from times — independent of the client's own shift code."""
        return JORNADA_CODE[self.jornada_type]

    @property
    def daily_max(self) -> float:
        return DAILY_MAX_H[self.jornada_type]

    @property
    def ordinary_hours(self) -> float:
        return min(self.hours, self.daily_max)

    @property
    def daily_excess_hours(self) -> float:
        """Hours above the Art. 61 daily max -> overtime (conservative default)."""
        return max(0.0, self.hours - self.daily_max)
