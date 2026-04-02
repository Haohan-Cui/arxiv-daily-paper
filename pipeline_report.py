from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional


@dataclass
class StageReport:
    name: str
    status: str = "pending"
    metrics: Dict[str, Any] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None

    def start(self) -> None:
        self.status = "running"
        self.started_at = datetime.utcnow()

    def finish(self, status: str = "ok") -> None:
        self.status = status
        self.ended_at = datetime.utcnow()

    def add_warning(self, message: str) -> None:
        self.warnings.append(message)

    def add_error(self, message: str) -> None:
        self.errors.append(message)
        self.status = "error"

    def set_metric(self, key: str, value: Any) -> None:
        self.metrics[key] = value

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        for key in ("started_at", "ended_at"):
            if data[key] is not None:
                data[key] = data[key].isoformat()
        return data


@dataclass
class PipelineReport:
    stages: Dict[str, StageReport] = field(default_factory=dict)

    def stage(self, name: str) -> StageReport:
        if name not in self.stages:
            self.stages[name] = StageReport(name=name)
        return self.stages[name]

    def has_errors(self) -> bool:
        return any(stage.errors for stage in self.stages.values())

    def summary_lines(self) -> List[str]:
        lines: List[str] = []
        for name, stage in self.stages.items():
            metrics = ", ".join(f"{k}={v}" for k, v in sorted(stage.metrics.items()))
            line = f"[REPORT] {name}: status={stage.status}"
            if metrics:
                line += f" | {metrics}"
            lines.append(line)
            for warning in stage.warnings:
                lines.append(f"[REPORT][WARN] {name}: {warning}")
            for error in stage.errors:
                lines.append(f"[REPORT][ERROR] {name}: {error}")
        return lines

    def to_dict(self) -> Dict[str, Any]:
        return {"stages": {name: stage.to_dict() for name, stage in self.stages.items()}}
