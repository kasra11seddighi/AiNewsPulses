"""بررسی زنده‌ی فیدها (نیازمند اینترنت). پیش از اولین اجرا یک بار اجرا کنید:

    python scripts/check_feeds.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from collector import collect_all  # noqa: E402
from sources import SOURCES  # noqa: E402


def main() -> int:
    active = [s for s in SOURCES if s.enabled and s.url]
    result = collect_all(active, max_items=3)
    bad = 0
    for r in result.results:
        mark = "OK  " if r.ok else "FAIL"
        bad += 0 if r.ok else 1
        print(f"[{mark}] {r.source:28} items={r.count:<3} {r.error}")
    skipped = [s.name for s in SOURCES if not (s.enabled and s.url)]
    if skipped:
        print("\nغیرفعال/بدون آدرس:", ", ".join(skipped))
    if bad:
        print(f"\n{bad} فید مشکل دارد: آدرس را در sources.py اصلاح کنید یا enabled=False بگذارید.")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
