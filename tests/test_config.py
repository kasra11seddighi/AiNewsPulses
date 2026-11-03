
from config import Settings


def test_safe_defaults():
    s = Settings.from_env({})

    assert s.enable_publishing is False
    assert s.enable_bale_publishing is False
    assert s.daily_post_limit == 10
    assert s.max_posts_per_run == 1

    assert s.min_quality_score == 65
    assert s.allow_article_images is False
    assert s.timezone == "Asia/Tehran"

    assert s.publishing_active() is False
    assert s.bale_active() is False


def test_unset_or_garbage_enable_publishing_is_false():
    assert Settings.from_env(
        {"ENABLE_PUBLISHING": ""}
    ).enable_publishing is False

    assert Settings.from_env(
        {"ENABLE_PUBLISHING": "maybe"}
    ).enable_publishing is False


def test_publishing_needs_explicit_flag_credentials_and_no_dry_run():
    env = {
        "ENABLE_PUBLISHING": "true",
        "TELEGRAM_BOT_TOKEN": "123456:abcdefghijklmnop",
        "TELEGRAM_CHANNEL_ID": "@AiNewsPulses",
    }

    s = Settings.from_env(env)

    assert s.publishing_active() is True
    assert s.publishing_active(dry_run=True) is False

    assert Settings.from_env({
        **env,
        "TELEGRAM_BOT_TOKEN": "",
    }).publishing_active() is False


def test_bale_safe_defaults():
    s = Settings.from_env({})

    assert s.enable_bale_publishing is False
    assert s.bale_bot_token == ""
    assert s.bale_channel_id == "@AINewsD1"
    assert s.bale_active() is False


def test_bale_publishing_needs_explicit_flag_and_credentials():
    env = {
        "ENABLE_BALE_PUBLISHING": "true",
        "BALE_BOT_TOKEN": "bale-secret-token",
        "BALE_CHANNEL_ID": "@AINewsD1",
    }

    s = Settings.from_env(env)

    assert s.enable_bale_publishing is True
    assert s.bale_active() is True
    assert s.bale_active(dry_run=True) is False


def test_bale_publishing_requires_token():
    env = {
        "ENABLE_BALE_PUBLISHING": "true",
        "BALE_CHANNEL_ID": "@AINewsD1",
    }

    assert Settings.from_env(env).bale_active() is False


def test_bale_publishing_requires_channel():
    s = Settings(
        enable_bale_publishing=True,
        bale_bot_token="bale-secret-token",
        bale_channel_id="",
    )

    assert s.bale_active() is False


def test_bale_publishing_requires_explicit_flag():
    env = {
        "BALE_BOT_TOKEN": "bale-secret-token",
        "BALE_CHANNEL_ID": "@AINewsD1",
    }

    assert Settings.from_env(env).bale_active() is False


def test_unset_or_garbage_enable_bale_publishing_is_false():
    assert Settings.from_env({
        "ENABLE_BALE_PUBLISHING": "",
    }).enable_bale_publishing is False

    assert Settings.from_env({
        "ENABLE_BALE_PUBLISHING": "maybe",
    }).enable_bale_publishing is False


def test_daily_limit_is_capped_and_invalid_numbers_fall_back():
    assert Settings.from_env({
        "DAILY_POST_LIMIT": "99",
    }).daily_post_limit == 10

    assert Settings.from_env({
        "MIN_QUALITY_SCORE": "abc",
    }).min_quality_score == 65


def test_secrets_are_hidden_from_repr():
    s = Settings.from_env({
        "TELEGRAM_BOT_TOKEN": "123456:SECRETSECRETSECRET",
        "BALE_BOT_TOKEN": "BALE_SECRET_SECRET",
        "GEMINI_API_KEY": "AIzaSECRETSECRETSECRET1234",
    })

    assert "SECRET" not in repr(s)
    assert "BALE_SECRET" not in repr(s)


def test_secrets_include_all_api_keys():
    s = Settings.from_env({
        "TELEGRAM_BOT_TOKEN": "telegram-secret",
        "BALE_BOT_TOKEN": "bale-secret",
        "GEMINI_API_KEY": "gemini-secret",
    })

    assert "telegram-secret" in s.secrets()
    assert "bale-secret" in s.secrets()
    assert "gemini-secret" in s.secrets()


def test_weights_can_be_overridden():
    s = Settings.from_env({
        "SCORE_WEIGHTS": '{"source": 10}',
    })

    assert s.weights["source"] == 10
    assert s.weights["freshness"] == 20

