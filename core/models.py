"""資料模型。schema 正本在 `docs/DATA-CONTRACT.md`，本檔只是它的 Python 形。

刻意不用 pandas 的 row 直接在各層流動：欄位名打錯在 DataFrame 裡是 KeyError，
在 dataclass 裡是 import 時就看得見的錯。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

GOAL_TYPES = ("cumulative", "rate", "streak")
M1_GOAL_TYPES = ("cumulative",)  # M1 只實作 cumulative（← docs/DATA-CONTRACT.md）

LOSS_KINDS = (
    "linear_excess",
    "opportunity",
    "at_risk_stock",
    "deadline_miss",
    "interrupt_only",
)

PROGRESS_SOURCES = ("notion_diff", "notion_diff_gap", "manual", "backfill")


@dataclass(frozen=True)
class Goal:
    """`goals.csv` 的一列。"""

    goal_id: str
    name: str
    type: str
    target: float
    start_date: date
    deadline: date
    unit_value: float | None = None
    loss_kind: str = "interrupt_only"
    parent_id: str | None = None
    owner: str = "self"

    @property
    def total_days(self) -> int:
        """起訖含頭含尾的天數。單日目標＝1，不是 0。"""
        return (self.deadline - self.start_date).days + 1

    def elapsed_days(self, as_of: date) -> int:
        """已過天數，夾在 [0, total_days]。"""
        if as_of < self.start_date:
            return 0
        return min((as_of - self.start_date).days + 1, self.total_days)

    def remaining_days(self, as_of: date) -> int:
        """**含今天**的剩餘可行動天數。deadline 當天仍算 1 天——今天還做得了事。

        因為兩端都含頭含尾，`elapsed_days + remaining_days` 會比 `total_days` 多 1（今天被算兩次）。
        這是刻意的：required rate 的分母若不含今天，最後一天就會變成除以零，
        而「最後一天」正是最需要算得出數字的那一天。
        """
        if as_of > self.deadline:
            return 0
        if as_of < self.start_date:
            return self.total_days
        return (self.deadline - as_of).days + 1

    def is_closed(self, as_of: date) -> bool:
        """期間已結束。結束的目標不發警示——那不是風險，是結果。"""
        return as_of > self.deadline

    def elapsed_ratio(self, as_of: date) -> float:
        return self.elapsed_days(as_of) / self.total_days

    def remaining_time_ratio(self, as_of: date) -> float:
        """V 公式裡的「剩餘可行動時間比例」。"""
        return self.remaining_days(as_of) / self.total_days

    def has_money(self) -> bool:
        """有沒有金額可換算。沒有就走 interrupt_only 的注意力單位。"""
        return self.unit_value is not None and self.loss_kind != "interrupt_only"


@dataclass(frozen=True)
class ProgressEntry:
    """`progress.csv` 的一列。**delta 是當天增量，不是累積值。**"""

    date: date
    goal_id: str
    delta: float
    source: str = "manual"


@dataclass(frozen=True)
class SnapshotRow:
    """`snapshots/YYYY-MM-DD.csv` 的一列。存在的唯一理由是還原流量。"""

    snapshot_date: date
    data_source: str
    dimension: str
    value: str
    count: int


@dataclass
class Issue:
    """關卡 0／1 的檢查結果。

    `level` 只有兩種：`reject` 擋下該筆／該目標，`note` 只記錄不擋。
    分兩級而不是三級，是因為第三級（warning）在實務上等於沒人看。
    """

    level: str
    code: str
    message: str
    goal_id: str | None = None

    def __str__(self) -> str:
        prefix = f"[{self.level}] {self.code}"
        return f"{prefix} {self.goal_id or '-'} — {self.message}"


@dataclass
class Dataset:
    """一次執行的完整輸入。"""

    goals: list[Goal] = field(default_factory=list)
    progress: list[ProgressEntry] = field(default_factory=list)
    issues: list[Issue] = field(default_factory=list)

    def goal_by_id(self, goal_id: str) -> Goal | None:
        for goal in self.goals:
            if goal.goal_id == goal_id:
                return goal
        return None

    def children_of(self, goal_id: str) -> list[Goal]:
        return [g for g in self.goals if g.parent_id == goal_id]


def business_date(moment: datetime, boundary_hour: int) -> date:
    """依日界把時間戳歸日。

    日界取 04:00 而非自然日（`meta.day_boundary_hour`）：作息常跨午夜，
    自然日會把同一段工作切成兩天，run rate 就會憑空多出一個零值日。
    """
    if moment.hour < boundary_hour:
        return (moment - timedelta(days=1)).date()
    return moment.date()
