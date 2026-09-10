"""load_config() hands every caller its own copy."""
from src.config import load_config


def test_mutating_the_returned_config_does_not_leak():
    cfg = load_config()
    cfg["models"]["agent"]["name"] = "changed/model"
    assert load_config()["models"]["agent"]["name"] != "changed/model"
