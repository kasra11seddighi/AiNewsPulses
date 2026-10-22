
"""منابع خبری پروژه AiNewsPulses.

پس از تغییر آدرس‌ها، این دستور را اجرا کنید:
    python scripts/check_feeds.py

اگر یک فید خراب بود، می‌توانید enabled=False قرار دهید.
خرابی یک فید نباید جلوی دریافت خبر از منابع دیگر را بگیرد.
"""

from __future__ import annotations

from models import Source


SOURCES = [
    # --- منابع رسمی هوش مصنوعی و فناوری ---
    Source(
        "OpenAI",
        "https://openai.com/news/rss.xml",
        "official",
        "ai",
        0.95,
    ),
    Source(
        "Google AI Blog",
        "https://blog.google/technology/ai/rss/",
        "official",
        "ai",
        0.95,
    ),
    Source(
        "Google DeepMind",
        "https://deepmind.google/blog/rss.xml",
        "official",
        "ai",
        0.95,
    ),
    Source(
        "Microsoft Research",
        "https://www.microsoft.com/en-us/research/feed/",
        "official",
        "ai",
        0.92,
    ),
    Source(
        "Microsoft AI Blog",
        "https://www.microsoft.com/en-us/microsoft-cloud/blog/feed/",
        "official",
        "ai",
        0.90,
    ),
	
   Source(
    "NVIDIA Blog",
    "https://blogs.nvidia.com/feed/",
    "official",
    "tech",
    0.90,
    enabled=False,
    notes="فعلاً به دلیل خطای HTTP 403 غیرفعال است.",
),
    Source(
        "GitHub Blog",
        "https://github.blog/feed/",
        "official",
        "programming",
        0.92,
    ),
    Source(
        "GitHub Changelog",
        "https://github.blog/changelog/feed/",
        "official",
        "programming",
        0.90,
    ),
    Source(
        "Python Insider",
        "https://blog.python.org/rss.xml",
        "official",
        "programming",
        0.95,
    ),
    Source(
        "Hugging Face Blog",
        "https://huggingface.co/blog/feed.xml",
        "official",
        "ai",
        0.90,
    ),
    Source(
        "AWS Machine Learning Blog",
        "https://aws.amazon.com/blogs/machine-learning/feed/",
        "official",
        "ai",
        0.88,
    ),

    # این دو منبع تا زمان مشخص شدن آدرس فید معتبر غیرفعال‌اند.
    Source(
        "Anthropic",
        "",
        "official",
        "ai",
        0.95,
        enabled=False,
        notes="تا زمان مشخص شدن آدرس فید معتبر غیرفعال است.",
    ),
    Source(
        "Meta AI",
        "",
        "official",
        "ai",
        0.92,
        enabled=False,
        notes="تا زمان مشخص شدن آدرس فید معتبر غیرفعال است.",
    ),

    # --- رسانه‌های خبری ---
    Source(
        "TechCrunch AI",
        "https://techcrunch.com/category/artificial-intelligence/feed/",
        "media",
        "ai",
        0.78,
    ),
    Source(
        "The Verge AI",
        "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml",
        "media",
        "ai",
        0.78,
    ),
    Source(
        "Ars Technica",
        "https://feeds.arstechnica.com/arstechnica/technology-lab",
        "media",
        "tech",
        0.80,
    ),

    # --- آموزش برنامه‌نویسی ---
    Source(
        "Real Python",
        "https://realpython.com/atom.xml",
        "tutorial",
        "tutorial",
        0.80,
    ),
]


def enabled_sources():
    """برگرداندن منابع فعال دارای آدرس."""
    return [
        source
        for source in SOURCES
        if source.enabled and source.url
    ]
