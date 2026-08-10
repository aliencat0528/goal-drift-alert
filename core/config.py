"""參數載入。

`config/params.yaml` 是所有門檻的唯一真相，程式碼不得硬編碼門檻值。
本模組唯一的職責是把它讀成可點號存取的物件，並且**取不到就爆**——
給預設值會讓「參數漏寫」悄悄變成「行為改變」，而那正是最難查的一種錯。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PARAMS_PATH = REPO_ROOT / "config" / "params.yaml"

_MISSING = object()


class ParamError(KeyError):
    """參數不存在。訊息帶完整路徑，例如 `gate.daily_quota`。"""


class Params:
    """YAML 節點的唯讀包裝，支援 `params.gate.daily_quota` 這種讀法。"""

    def __init__(self, data: dict, path: str = "") -> None:
        object.__setattr__(self, "_data", data)
        object.__setattr__(self, "_path", path)

    def _child_path(self, name: str) -> str:
        return f"{self._path}.{name}" if self._path else name

    def _wrap(self, name: str, value: Any) -> Any:
        if isinstance(value, dict):
            return Params(value, self._child_path(name))
        return value

    def __getattr__(self, name: str) -> Any:
        data = object.__getattribute__(self, "_data")
        if name not in data:
            raise ParamError(f"參數不存在：{self._child_path(name)}（正本在 config/params.yaml）")
        return self._wrap(name, data[name])

    def __setattr__(self, name: str, value: Any) -> None:
        raise AttributeError(
            "Params 是唯讀的：參數是人的意志，程式不得回寫（← docs/ARCHITECTURE.md）"
        )

    def __getitem__(self, name: str) -> Any:
        return self.__getattr__(name)

    def __contains__(self, name: str) -> bool:
        return name in self._data

    def get(self, name: str, default: Any = _MISSING) -> Any:
        """明示 opt-in 的取值。沒給 default 時行為與屬性存取相同（取不到即爆）。"""
        if name in self._data:
            return self._wrap(name, self._data[name])
        if default is _MISSING:
            raise ParamError(f"參數不存在：{self._child_path(name)}")
        return default

    def to_dict(self) -> dict:
        return dict(self._data)

    def __repr__(self) -> str:
        return f"Params({self._path or 'root'}: {sorted(self._data)})"


def load_params(path: str | Path | None = None) -> Params:
    """讀取參數檔。`path` 留空時用 repo 內的 `config/params.yaml`。"""
    params_path = Path(path) if path else DEFAULT_PARAMS_PATH
    with open(params_path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if not isinstance(data, dict):
        raise ValueError(f"參數檔格式錯誤（頂層必須是 mapping）：{params_path}")
    return Params(data)
