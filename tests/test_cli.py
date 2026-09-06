from app.cli import parser
import pytest


def test_collector_and_telegram_authorization_remain_available():
    assert parser().parse_args(["collect"]).command == "collect"
    assert parser().parse_args(["auth-web"]).command == "auth-web"


@pytest.mark.parametrize("command", ["web", "run"])
def test_removed_python_dashboard_commands_are_rejected(command):
    with pytest.raises(SystemExit) as error:
        parser().parse_args([command])
    assert error.value.code == 2
