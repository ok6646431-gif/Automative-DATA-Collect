"""Temporary first-party report-page contract probe.

This does not modify production source. It prints only bounded report/pagination
controls from the already verified KCC official sustainability page so the generic
recovery can be implemented from the site's actual contract instead of guessing.
"""
from __future__ import annotations

import re
import requests
from bs4 import BeautifulSoup

URL = "https://www.kccworld.co.kr/esg/sustainability.do"


def main() -> int:
    r = requests.get(URL, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    print("PROBE_STATUS", r.status_code, r.url, len(r.content))
    html = r.text
    soup = BeautifulSoup(html, "html.parser")

    print("FORMS")
    for form in soup.find_all("form"):
        print("FORM", form.get("id"), form.get("name"), form.get("method"), form.get("action"))
        for inp in form.find_all(["input", "select"]):
            print(" FIELD", inp.name, inp.get("name"), inp.get("id"), inp.get("value"))

    print("PAGE_CONTROLS")
    for tag in soup.find_all(["a", "button"]):
        raw = " ".join([
            " ".join(tag.stripped_strings),
            str(tag.get("href") or ""),
            str(tag.get("onclick") or ""),
            str(tag.get("class") or ""),
            str(tag.get("id") or ""),
        ])
        if re.search(r"page|paging|next|prev|이전|다음|더보기|fn[A-Za-z]*Page|goPage", raw, re.I):
            print("CONTROL", raw[:1000])

    print("INLINE_PAGINATION_JS")
    for script in soup.find_all("script"):
        if script.get("src"):
            continue
        text = script.get_text() or ""
        for m in re.finditer(r".{0,500}(?:page|paging|currentPage|pageIndex|goPage|fn[A-Za-z]*Page).{0,1200}", text, re.I | re.S):
            snippet = re.sub(r"\s+", " ", m.group(0)).strip()
            print("JS", snippet[:1800])

    print("REPORT_CONTROLS")
    for tag in soup.find_all(["a", "button"]):
        raw = " ".join([str(tag.get("onclick") or ""), " ".join(tag.stripped_strings)])
        if "fnFileDown" in raw or "지속가능" in raw:
            print("REPORT", raw[:1000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
