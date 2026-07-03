import os


def get_app_mode() -> str:
    return os.environ.get("APP_MODE", "ai_fusion")


def is_pure_rss_mode() -> bool:
    return get_app_mode() == "pure_rss"
