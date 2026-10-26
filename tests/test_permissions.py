"""本地测试身份映射与访问组计算。"""

from app.config import Settings
from app.permissions import PUBLIC, allowed_access_groups, department_for_user


def test_known_users_map_to_departments():
    assert department_for_user("ou_finance_demo") == "finance"
    assert department_for_user("ou_hr_demo") == "hr"
    assert department_for_user("ou_rd_demo") == "rd"


def test_unknown_user_defaults_to_public():
    assert department_for_user(None) == PUBLIC
    assert department_for_user("") == PUBLIC
    assert department_for_user("ou_stranger") == PUBLIC


def test_overrides_take_precedence_and_invalid_values_fall_back():
    assert department_for_user("ou_me", {"ou_me": "finance"}) == "finance"
    assert department_for_user("ou_me", {"ou_me": "admin"}) == PUBLIC


def test_allowed_groups_always_include_public():
    assert allowed_access_groups("finance") == ["public", "finance"]
    assert allowed_access_groups("hr") == ["public", "hr"]
    assert allowed_access_groups("rd") == ["public", "rd"]
    assert allowed_access_groups(PUBLIC) == ["public"]
    assert allowed_access_groups("unknown") == ["public"]
    assert allowed_access_groups(None) == ["public"]


def test_settings_parses_department_mapping_from_env(monkeypatch):
    monkeypatch.setenv("TEST_USER_DEPARTMENTS", '{"ou_env_user": "hr"}')

    settings = Settings(_env_file=None)

    assert settings.test_user_departments == {"ou_env_user": "hr"}
    assert department_for_user("ou_env_user", settings.test_user_departments) == "hr"
