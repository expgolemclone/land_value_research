from __future__ import annotations

import hashlib
import html
import io
import json
import logging
import os
import re
import threading
import urllib.request
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

import pdfplumber

from src.jp_address import normalize_addr, split_tokyo_municipality
from src.network import urlopen_with_retry
from src.utils import validate_url_not_private

logger = logging.getLogger(__name__)

_RE_TAG = re.compile(r"<[^>]+>")
_RE_LINE_TOKYO = re.compile(r"東京都[^\n]{0,120}")


@dataclass(frozen=True)
class AddressCandidate:
    address: str
    score: int
    source_url: str


class WebAddressResearcher:
    def __init__(self, cache_dir: str, timeout_sec: int = 15):
        self.cache_dir = cache_dir
        self.timeout_sec = timeout_sec
        os.makedirs(self.cache_dir, exist_ok=True)
        self._text_cache: dict[str, str] = {}
        self._addr_cache: dict[str, list[str]] = {}
        self._resolve_cache_path = os.path.join(self.cache_dir, "resolve_cache.json")
        self._resolve_cache: dict[str, dict[str, object]] = {}
        self._resolve_cache_dirty = False
        self._lock = threading.Lock()
        if os.path.exists(self._resolve_cache_path):
            try:
                with open(self._resolve_cache_path, encoding="utf-8") as f:
                    d = json.load(f)
                if isinstance(d, dict):
                    self._resolve_cache = d
            except Exception:
                logger.debug("resolve cache load failed: %s", self._resolve_cache_path, exc_info=True)
                self._resolve_cache = {}

    def seed_cache(self, url: str, local_path: str) -> None:
        """Register an already-downloaded file to avoid re-downloading."""
        cache_path = self._cache_path(url)
        if not os.path.exists(cache_path):
            import shutil

            shutil.copy2(local_path, cache_path)

    def _cache_path(self, url: str) -> str:
        key = hashlib.sha1(url.encode("utf-8")).hexdigest()
        return os.path.join(self.cache_dir, key)

    def _analysis_cache_path(self, url: str) -> str:
        key = hashlib.sha1(url.encode("utf-8")).hexdigest()
        return os.path.join(self.cache_dir, f"{key}.analysis.json")

    def _fetch_bytes(self, url: str) -> bytes:
        cache_path = self._cache_path(url)
        if os.path.exists(cache_path):
            with open(cache_path, "rb") as f:
                return f.read()

        validate_url_not_private(url)
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 (compatible; land_value_research/1.0)"},
        )
        body = urlopen_with_retry(req, timeout_sec=self.timeout_sec)
        with open(cache_path, "wb") as f:
            f.write(body)
        return body

    @staticmethod
    def _html_to_text(s: str) -> str:
        s = html.unescape(s)
        s = s.replace("<br>", "\n").replace("<br/>", "\n").replace("<br />", "\n")
        s = _RE_TAG.sub("\n", s)
        # 連続空白だけを圧縮し, 改行は保持する
        s = re.sub(r"[ \t\r\f\v]+", " ", s)
        return s

    @staticmethod
    def _pdf_to_text(data: bytes) -> str:
        out: list[str] = []
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            for p in pdf.pages:
                txt = p.extract_text() or ""
                if txt:
                    out.append(txt)
        return "\n".join(out)

    @staticmethod
    def _trim_tokyo_address(addr: str) -> str:
        a = normalize_addr(addr).replace(" ", "")
        i = a.find("東京都")
        if i >= 0:
            a = a[i:]

        a = re.split(r"TEL|FAX|https?://|〒|[（()）]", a)[0]
        a = re.split(r"[。､,，;；]", a)[0]
        a = re.sub(r"(に移転|へ移転|移転予定|移転)$", "", a)

        m = re.match(r"^(東京都.+?号)", a)
        if m:
            return m.group(1)

        # 例: 六本木3-4-333926.29 のような末尾ノイズは 3-4 までに丸める
        m = re.match(r"^(東京都.+?\d{1,4}-\d{1,4})-\d{5,}.*$", a)
        if m:
            return m.group(1)

        m = re.match(r"^(東京都.+?(?:\d+丁目)?\d{1,4}-\d{1,4}(?:-\d{1,4})?).*$", a)
        if m:
            return m.group(1)

        m = re.match(r"^(東京都.+?\d+丁目\d+番(?:地|\d+)?).*$", a)
        if m:
            return m.group(1)

        m = re.match(r"^(東京都.+?\d+丁目).*$", a)
        if m:
            return m.group(1)

        return a

    @staticmethod
    def _cleanup_addr_token(s: str) -> str:
        return WebAddressResearcher._trim_tokyo_address(s)

    def _extract_candidates(self, text: str) -> list[str]:
        out: list[str] = []
        for m in _RE_LINE_TOKYO.finditer(text):
            addr = self._cleanup_addr_token(m.group(0))
            if not addr.startswith("東京都"):
                continue
            if not re.search(r"(区|市|町|村)", addr):
                continue
            # 少なくとも丁目または番地系の情報を含むものを候補とする
            if not re.search(r"(\d+丁目|\d+-\d+|\d+番|\d+号)", addr):
                continue
            if addr not in out:
                out.append(addr)
        return out

    def _extract_candidates_by_url(self, url: str) -> list[str]:
        cached = self._addr_cache.get(url)
        if cached is not None:
            return cached

        text = self._text_cache.get(url)
        if text is None:
            raw_cache_path = self._cache_path(url)
            analysis_cache_path = self._analysis_cache_path(url)
            if os.path.exists(raw_cache_path) and os.path.exists(analysis_cache_path):
                try:
                    raw_stat = os.stat(raw_cache_path)
                    with open(analysis_cache_path, encoding="utf-8") as f:
                        d = json.load(f)
                    if int(d.get("raw_size", -1)) == int(raw_stat.st_size) and float(d.get("raw_mtime", -1.0)) == float(
                        raw_stat.st_mtime
                    ):
                        text = str(d.get("text", ""))
                        addrs = [str(x) for x in d.get("addrs", [])]
                        self._text_cache[url] = text
                        self._addr_cache[url] = addrs
                        return addrs
                except Exception:
                    logger.debug("analysis cache load failed: %s", url, exc_info=True)

            try:
                raw = self._fetch_bytes(url)
            except Exception:
                logger.debug("fetch failed: %s", url, exc_info=True)
                return []

            if url.lower().endswith(".pdf") or raw[:5] == b"%PDF-":
                try:
                    text = self._pdf_to_text(raw)
                except Exception:
                    logger.debug("pdf to text failed: %s", url, exc_info=True)
                    self._addr_cache[url] = []
                    return []
            else:
                text = self._html_to_text(raw.decode("utf-8", errors="ignore"))
            self._text_cache[url] = text

        addrs = self._extract_candidates(text)
        self._addr_cache[url] = addrs
        try:
            raw_cache_path = self._cache_path(url)
            raw_stat = os.stat(raw_cache_path)
            with open(self._analysis_cache_path(url), "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "raw_size": int(raw_stat.st_size),
                        "raw_mtime": float(raw_stat.st_mtime),
                        "text": text,
                        "addrs": addrs,
                    },
                    f,
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
        except Exception:
            logger.debug("analysis cache write failed: %s", url, exc_info=True)
        return addrs

    @staticmethod
    def _score(site_name: str, location_short: str, addr: str, page_text: str) -> int:
        score = 0
        addr_n = normalize_addr(addr)
        loc_n = normalize_addr(location_short)
        site_n = normalize_addr(site_name)

        muni, _ = split_tokyo_municipality(loc_n)
        if muni and muni in addr_n:
            score += 20
        elif muni:
            score -= 40

        if loc_n and loc_n in addr_n:
            score += 30

        if "丁目" in addr_n or "-" in addr_n:
            score += 10
        if re.search(r"\d+番\d*号?", addr_n) or re.search(r"\d+-\d+", addr_n):
            score += 20
        if addr_n.endswith("丁目"):
            score -= 5

        i = page_text.find(addr_n)
        if i >= 0:
            left = max(0, i - 100)
            right = min(len(page_text), i + 100)
            ctx = page_text[left:right]
            if site_n and site_n in ctx:
                score += 40
            if muni and muni in ctx:
                score += 10

        return score

    def resolve(
        self,
        site_name: str,
        location_short: str,
        source_urls: Iterable[str],
    ) -> AddressCandidate | None:
        urls = [u.strip() for u in source_urls if (u or "").strip()]
        key = "|".join([normalize_addr(site_name), normalize_addr(location_short), "||".join(urls)])
        with self._lock:
            cached = self._resolve_cache.get(key)
        if isinstance(cached, dict):
            if "address" in cached and "score" in cached and "source_url" in cached:
                return AddressCandidate(
                    address=str(cached["address"]),
                    score=int(cached["score"]),
                    source_url=str(cached["source_url"]),
                )
            if cached.get("none") is True:
                return None

        # Fetch all URLs concurrently (I/O-bound), then score using cached results
        valid_urls = [u for u in urls if u]
        if len(valid_urls) > 1:
            with ThreadPoolExecutor(max_workers=min(4, len(valid_urls))) as executor:
                list(executor.map(self._extract_candidates_by_url, valid_urls))

        best: AddressCandidate | None = None
        for url in valid_urls:
            addrs = self._extract_candidates_by_url(url)
            text = self._text_cache.get(url, "")
            for addr in addrs:
                score = self._score(site_name=site_name, location_short=location_short, addr=addr, page_text=text)
                cand = AddressCandidate(address=addr, score=score, source_url=url)
                if best is None:
                    best = cand
                elif cand.score > best.score:
                    best = cand
                elif cand.score == best.score and cand.address < best.address:
                    best = cand

        with self._lock:
            if best is None:
                self._resolve_cache[key] = {"none": True}
            else:
                self._resolve_cache[key] = {
                    "address": best.address,
                    "score": int(best.score),
                    "source_url": best.source_url,
                }
            self._resolve_cache_dirty = True
        return best

    def flush(self) -> None:
        """Write resolve cache to disk if it has been modified."""
        with self._lock:
            if not self._resolve_cache_dirty:
                return
            try:
                with open(self._resolve_cache_path, "w", encoding="utf-8") as f:
                    json.dump(self._resolve_cache, f, ensure_ascii=False, separators=(",", ":"))
                self._resolve_cache_dirty = False
            except Exception:
                logger.debug("resolve cache flush failed: %s", self._resolve_cache_path, exc_info=True)
