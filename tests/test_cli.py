from app.cli import parser


def test_collector_and_web_have_independent_cli_commands():
    assert parser().parse_args(["collect"]).command == "collect"
    assert parser().parse_args(["web"]).command == "web"
    assert parser().parse_args(["auth-web"]).command == "auth-web"
