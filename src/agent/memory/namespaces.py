"""Store 命名空间规范。

统一之后的结构：

    ("memories", <user_id>, "semantic")    用户级稳定事实（偏好、画像）
    ("memories", <user_id>, "episodic")    用户级情节归档（做过什么）
    ("memories", <user_id>, "procedural")  用户级经验/流程（怎么做事）
    ("memories", "org", "policies")        组织级只读策略
    ("memories", <user_id>, "projection")  WARM 偏好投影
"""
from __future__ import annotations

from typing import Optional, Tuple

ROOT = "memories"

SEMANTIC = "semantic"
EPISODIC = "episodic"
PROCEDURAL = "procedural"
POLICIES = "policies"
PROJECTION = "projection"

ORG_ID = "org"
PREFERENCES_KEY = "preferences"


def semantic_ns(user_id: str) -> Tuple[str, str, str]:
    return (ROOT, user_id or "default_user", SEMANTIC)


def episodic_ns(user_id: str) -> Tuple[str, str, str]:
    return (ROOT, user_id or "default_user", EPISODIC)


def procedural_ns(user_id: str) -> Tuple[str, str, str]:
    return (ROOT, user_id or "default_user", PROCEDURAL)


def org_policies_ns() -> Tuple[str, str, str]:
    return (ROOT, ORG_ID, POLICIES)


def preferences_ns(user_id: str) -> Tuple[str, str, str]:
    return (ROOT, user_id or "default_user", PROJECTION)


def type_ns(user_id: str, memory_type: str) -> Tuple[str, str, str]:
    if memory_type == EPISODIC:
        return episodic_ns(user_id)
    if memory_type == PROCEDURAL:
        return procedural_ns(user_id)
    return semantic_ns(user_id)


def user_namespaces(user_id: str) -> Tuple[Tuple[str, ...], ...]:
    return (semantic_ns(user_id), episodic_ns(user_id), procedural_ns(user_id))


def parse(namespace) -> dict:
    """把命名空间解析成结构化信息，解析不出来时给出安全的默认值。"""
    parts = [str(p) for p in (namespace or ())]
    info = {
        "root": parts[0] if parts else "",
        "scope": parts[1] if len(parts) > 1 else "",
        "type": parts[2] if len(parts) > 2 else "",
    }
    info["is_memory"] = info["root"] == ROOT
    info["is_org"] = info["is_memory"] and info["scope"] == ORG_ID
    return info


def user_of(namespace) -> Optional[str]:
    info = parse(namespace)
    if info["is_memory"] and not info["is_org"]:
        return info["scope"] or None
    return None
