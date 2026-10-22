from config import Settings


def test_safe_defaults():
    s = Settings.from_env({})
    assert s.enable_publishing is False and s.daily_post_limit == 4 and s.max_posts_per_run == 1
    assert s.min_quality_score == 65 and s.allow_article_images is False and s.timezone == "Asia/Tehran"
    assert s.publishing_active() is False


def test_unset_or_garbage_enable_publishing_is_false():
    assert Settings.from_env({"ENABLE_PUBLISHING": ""}).enable_publishing is False
    assert Settings.from_env({"ENABLE_PUBLISHING": "maybe"}).enable_publishing is False


def test_publishing_needs_explicit_flag_credentials_and_no_dry_run():
    env = {"ENABLE_PUBLISHING": "true", "TELEGRAM_BOT_TOKEN": "123456:abcdefghijklmnop", "TELEGRAM_CHANNEL_ID": "@AiNewsPulses"}
    s = Settings.from_env(env)
    assert s.publishing_active() is True
    assert s.publishing_active(dry_run=True) is False
    assert Settings.from_env({**env, "TELEGRAM_BOT_TOKEN": ""}).publishing_active() is False


def test_daily_limit_is_capped_and_invalid_numbers_fall_back():
    assert Settings.from_env({"DAILY_POST_LIMIT": "99"}).daily_post_limit == 4
    assert Settings.from_env({"MIN_QUALITY_SCORE": "abc"}).min_quality_score == 65


def test_secrets_are_hidden_from_repr():
    s = Settings.from_env({"TELEGRAM_BOT_TOKEN": "123456:SECRETSECRETSECRET", "GEMINI_API_KEY": "AIzaSECRETSECRETSECRET1234"})
    assert "SECRET" not in repr(s)


def test_weights_can_be_overridden():
    s = Settings.from_env({"SCORE_WEIGHTS": '{"source": 10}'})
    assert s.weights["source"] == 10 and s.weights["freshness"] == 20
