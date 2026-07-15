#!/usr/bin/env python3
"""Scrapes enke.iq into content.json for the ENKE app.

Stdlib only (urllib + re) so it runs locally and in GitHub Actions.
The app treats this feed as the source of truth, with its bundled mock
catalog as offline fallback. When ENKE's real backend/CMS arrives, the
app just points at the new URL — same shape.
"""
import hashlib
import html
import json
import re
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")

NEWS_CATEGORIES = {
    "institution": "https://enke.iq/news/category/اهم-اخبار-المؤسسة",
    "publications": "https://enke.iq/news/category/الاصدارات",
    "bookFairs": "https://enke.iq/news/category/معارض-الكتب",
    "magazine": "https://enke.iq/news/category/مجلة-انكي-للعلوم-الأجتماعية-والانسانية",
    "activities": "https://enke.iq/news/category/انشطة",
}
STUDIES_URL = "https://enke.iq/book/category/المكتبة"

PER_CATEGORY = 4
STUDIES_COUNT = 8

CARD_SPLIT = 'class="m-25 relative flex flex-col shadow-md"'


def fetch(url: str) -> str:
    safe = urllib.parse.quote(url, safe=":/%?&=")
    req = urllib.request.Request(safe, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "replace")


def clean(text: str) -> str:
    out = html.unescape(re.sub(r"\s+", " ", text)).strip()
    # strip social-post artefacts from scraped titles/bodies
    out = re.sub(r"#[^\s#]+", "", out)          # hashtags
    out = out.replace("_", " ")                  # underscore separators
    return re.sub(r"\s{2,}", " ", out).strip(" -—·")


def item_id(url: str) -> str:
    return hashlib.md5(url.encode()).hexdigest()[:12]


def parse_cards(page: str, link_prefix: str):
    """Yields (url, image, title, date) per listing card."""
    for chunk in page.split(CARD_SPLIT)[1:]:
        chunk = chunk[:4000]
        m_link = re.search(
            r'href="(https://enke\.iq/' + link_prefix + r'/[^"]+)"', chunk)
        if not m_link or "/category/" in m_link.group(1):
            continue
        m_img = re.search(r'<img[^>]+src="([^"]+)"[^>]*alt="([^"]*)"', chunk)
        m_date = re.search(r"(\d{4}-\d{2}-\d{2})", chunk)
        title = clean(m_img.group(2)) if m_img and m_img.group(2) else ""
        if not title:
            m_t = re.search(r"<h\d[^>]*>(.*?)</h\d>", chunk, re.S)
            title = clean(re.sub(r"<[^>]+>", "", m_t.group(1))) if m_t else ""
        if not title:
            continue
        yield (
            urllib.parse.unquote(m_link.group(1)),
            m_img.group(1) if m_img else "",
            title,
            m_date.group(1) if m_date else "",
        )


def article_body(url: str, max_paragraphs: int = 8) -> str:
    try:
        page = fetch(url)
    except Exception:
        return ""
    paras = []
    for m in re.finditer(r"<p[^>]*>(.*?)</p>", page, re.S):
        text = clean(re.sub(r"<[^>]+>", " ", m.group(1)))
        if len(text) < 40:
            continue
        if any(skip in text for skip in ("جميع الحقوق", "cookies", "©")):
            continue
        paras.append(text)
        if len(paras) >= max_paragraphs:
            break
    return "\n\n".join(paras)


def bilingual(text: str):
    # English content isn't published for most items; fall back to Arabic
    # so the EN locale still shows real material.
    return {"ar": text, "en": text}


def main():
    news = []
    seen = set()
    for category, url in NEWS_CATEGORIES.items():
        try:
            page = fetch(url)
        except Exception as e:
            print(f"!! {category}: {e}", file=sys.stderr)
            continue
        count = 0
        for link, img, title, date in parse_cards(page, "news"):
            if link in seen or count >= PER_CATEGORY:
                continue
            seen.add(link)
            body = article_body(link)
            excerpt = body.split("\n\n")[0][:220] if body else title
            news.append({
                "id": item_id(link),
                "category": category,
                "title": bilingual(title),
                "excerpt": bilingual(excerpt),
                "body": bilingual(body or title),
                "imageUrl": img,
                "publishedAt": date or "2026-01-01",
                "url": link,
            })
            count += 1
        print(f"{category}: {count} items")

    studies = []
    try:
        page = fetch(STUDIES_URL)
        for link, img, title, date in parse_cards(page, "book"):
            if len(studies) >= STUDIES_COUNT:
                break
            body = article_body(link, max_paragraphs=4)
            studies.append({
                "id": item_id(link),
                "title": bilingual(title),
                "summary": bilingual(body or title),
                "author": bilingual("مؤسسة إنكي للدراسات والبحوث"),
                "imageUrl": img,
                "publishedAt": date or "2026-01-01",
                "pdfUrl": link,
                "url": link,
            })
        print(f"studies: {len(studies)} items")
    except Exception as e:
        print(f"!! studies: {e}", file=sys.stderr)

    if len(news) < 5 or len(studies) < 2:
        print("!! too little content scraped — refusing to overwrite",
              file=sys.stderr)
        sys.exit(1)

    out = {
        "version": 1,
        "generated": datetime.now(timezone.utc).isoformat(),
        "source": "enke.iq",
        "news": news,
        "studies": studies,
    }
    with open("content.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"content.json written: {len(news)} news, {len(studies)} studies")


if __name__ == "__main__":
    main()
