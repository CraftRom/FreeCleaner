"""Typed cross-layer contracts used by workers and progress reporting."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass(slots=True)
class OperationResult:
    ok: bool
    operation: str
    message: str = ""
    error_code: Optional[str] = None
    data: Dict[str, Any] = field(default_factory=dict)
    cancelled: bool = False

    def to_dict(self) -> Dict[str, Any]:
        payload = dict(self.data)
        payload.update(
            {
                "ok": bool(self.ok),
                "op": str(self.operation),
                "message": str(self.message),
                "cancelled": bool(self.cancelled),
            }
        )
        if self.error_code:
            payload["error_code"] = str(self.error_code)
        return payload


@dataclass(slots=True)
class ProgressUpdate:
    operation: str
    stage: str
    completed: Optional[int] = None
    total: Optional[int] = None
    bytes_done: Optional[int] = None
    bytes_total: Optional[int] = None
    current_item: Optional[str] = None
    speed_bps: Optional[float] = None
    eta_seconds: Optional[float] = None
    message_key: Optional[str] = None

    @property
    def determinate(self) -> bool:
        return self.total is not None and self.total > 0 and self.completed is not None

    def percent(self) -> Optional[int]:
        if not self.determinate:
            return None
        return max(0, min(100, int(int(self.completed or 0) * 100 / max(1, int(self.total or 0)))))

    def to_payload(self) -> Dict[str, Any]:
        return {
            "operation": self.operation,
            "stage": self.stage,
            "completed": self.completed,
            "total": self.total,
            "bytes_done": self.bytes_done,
            "bytes_total": self.bytes_total,
            "current_item": self.current_item,
            "speed_bps": self.speed_bps,
            "eta_seconds": self.eta_seconds,
            "message_key": self.message_key,
            "percent": self.percent(),
            "determinate": self.determinate,
        }
