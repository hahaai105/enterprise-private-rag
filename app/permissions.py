"""部门访问控制：文档访问组与本地测试身份映射。

这是本地演示用的最小实现，不是生产级鉴权：
- 身份映射保存在内存或环境变量中，可被伪造；
- 没有登录、签名校验或用户体系；
- 仅用于验证“检索阶段按部门过滤”这一机制。
"""

from __future__ import annotations

from collections.abc import Mapping

PUBLIC = "public"
KNOWN_DEPARTMENTS = frozenset({"public", "finance", "hr", "rd"})

# 本地测试用虚拟飞书 open_id；真实用户可通过 TEST_USER_DEPARTMENTS 覆盖
DEFAULT_TEST_USER_DEPARTMENTS: dict[str, str] = {
    "ou_finance_demo": "finance",
    "ou_hr_demo": "hr",
    "ou_rd_demo": "rd",
}


def department_for_user(
    user_id: str | None,
    overrides: Mapping[str, str] | None = None,
) -> str:
    """按飞书用户 ID 返回部门；未知用户或非法配置一律按 public 处理。"""
    if not user_id:
        return PUBLIC

    mapping = dict(DEFAULT_TEST_USER_DEPARTMENTS)
    if overrides:
        mapping.update(overrides)

    department = mapping.get(user_id, PUBLIC)
    return department if department in KNOWN_DEPARTMENTS else PUBLIC


def allowed_access_groups(department: str | None) -> list[str]:
    """public 始终可见，其余部门只能额外看到本部门文档。"""
    if department in KNOWN_DEPARTMENTS and department != PUBLIC:
        return [PUBLIC, department]
    return [PUBLIC]
