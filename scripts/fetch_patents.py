#!/usr/bin/env python3
"""
Tech vigilance patent fetcher.
Sources: EPO Open Patent Services (EP/WO/GB/FR/DE…), USPTO PatentsView (US).
Reads watchtags.csv → writes patents.json + patents.csv + patents_readable.txt.
"""

import csv
import json
import os
import re
import time
import datetime
import requests
import xml.etree.ElementTree as ET
from pathlib import Path

# ── Config ─────────────────────────────────────────────────────────────────────

REPO_ROOT       = Path(__file__).parent.parent
TAGS_FILE       = REPO_ROOT / "watchtags.csv"
OUTPUT_JSON     = REPO_ROOT / "patents.json"
OUTPUT_CSV      = REPO_ROOT / "patents.csv"
OUTPUT_READABLE = REPO_ROOT / "patents_readable.txt"

DAYS_BACK       = 730   # 2 years — patents publish slower than papers
DELAY           = 0.5   # seconds between PatentsView calls
DELAY_EPO       = 1.5   # EPO OPS free tier: ~2500 req/hr = 1 per 1.44s; stay safe at 1.5s
EPO_PAGE_SIZE   = 100   # results per EPO page (max 100 per request)
EPO_MAX_RESULTS = 300   # max results to fetch per query (3 pages)

EPO_OPS_KEY    = os.environ.get("EPO_OPS_KEY", "").strip()
EPO_OPS_SECRET = os.environ.get("EPO_OPS_SECRET", "").strip()

EPO_AUTH_URL    = "https://ops.epo.org/3.2/auth/accesstoken"
EPO_SEARCH_BASE = "https://ops.epo.org/3.2/rest-services/published-data/search"
PATENTSVIEW_V1  = "https://api.patentsview.org/patents/query"   # v1 (fallback)
PATENTSVIEW_V2  = "https://search.patentsview.org/api/v1/patent/"  # v2 (may fail DNS)

# Google Patents indexes these jurisdictions reliably
_GOOGLE_JURISDICTIONS = {"US","EP","WO","DE","GB","FR","JP","CN","KR","CA","AU","CH","NL","BE","SE","DK"}

_GRANTED_RE = re.compile(r'^[BCEFGHIU]')   # kind codes for granted patents

# ── Tag loading ────────────────────────────────────────────────────────────────

def load_tags(path: Path) -> list[dict]:
    tags = []
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row.get("active", "true").strip().lower() == "false":
                continue
            synonyms = [s.strip() for s in row.get("synonyms", "").split(",") if s.strip()]
            must     = [m.strip() for m in row.get("mustInclude", "").split(",") if m.strip()]
            tags.append({
                "tag":         row["tag"].strip(),
                "synonyms":    synonyms,
                "mustInclude": must,
                "domain":      row.get("domain", "General").strip(),
                "folder":      row.get("folder", "General").strip(),
            })
    return tags

# ── EPO Open Patent Services ───────────────────────────────────────────────────

_epo_disabled = False
_epo_token    = ""
_epo_token_ts = 0.0


def _refresh_epo_token() -> bool:
    global _epo_token, _epo_token_ts, _epo_disabled
    try:
        r = requests.post(
            EPO_AUTH_URL,
            data={"grant_type": "client_credentials"},
            auth=(EPO_OPS_KEY, EPO_OPS_SECRET),
            timeout=20,
        )
        if r.status_code in (401, 403):
            print("  [EPO] Invalid credentials — disabling EPO for this run")
            _epo_disabled = True
            return False
        r.raise_for_status()
        _epo_token    = r.json()["access_token"]
        _epo_token_ts = time.time()
        return True
    except Exception as e:
        print(f"  [EPO] Auth error: {e}")
        _epo_disabled = True
        return False


def _epo_headers() -> dict:
    global _epo_token, _epo_token_ts
    # Token expires in 1200 s; refresh 90 s before expiry
    if not _epo_token or (time.time() - _epo_token_ts) > 1110:
        _refresh_epo_token()
    return {
        "Authorization": f"Bearer {_epo_token}",
        "Accept":        "application/json",
    }


def _cql_escape(text: str) -> str:
    cleaned = re.sub(r'["\\/()&|!{}^]', ' ', text).strip()
    cleaned = re.sub(r'\s+', ' ', cleaned)
    return cleaned[:100]


def _epo_fetch_page(url: str, cql: str, start: int) -> tuple[list[dict], int]:
    """
    Fetch one page of EPO OPS results.
    Returns (patents, total_count). Returns (None, 0) on auth error to signal retry.
    """
    end     = start + EPO_PAGE_SIZE - 1
    headers = {**_epo_headers(), "Range": f"items={start}-{end}"}
    try:
        r = requests.get(url, params={"q": cql}, headers=headers, timeout=30)
        if r.status_code == 401:
            return None, 0   # caller should refresh token and retry
        if r.status_code == 403:
            return "throttle", 0
        if r.status_code == 400:
            print(f"  [EPO] 400: {r.text[:200]}")
            return [], 0
        if r.status_code == 404:
            return [], 0
        if r.status_code in (500, 503):
            print(f"  [EPO] {r.status_code}")
            return [], 0
        r.raise_for_status()
        data       = r.json()
        bs         = data.get("ops:world-patent-data", {}).get("ops:biblio-search", {})
        total      = int(bs.get("@total-result-count", 0))
        patents    = _parse_epo_json(data)
        return patents, total
    except Exception as e:
        print(f"  [EPO page {start}] {e}")
        return [], 0


def search_epo(query: str, days: int) -> list[dict]:
    """Search EPO OPS — covers EP, WO, GB, FR, DE and 50+ patent offices.
    Paginates up to EPO_MAX_RESULTS per query to capture more results."""
    global _epo_disabled
    if _epo_disabled or not (EPO_OPS_KEY and EPO_OPS_SECRET):
        return []
    today     = datetime.date.today()
    date_from = (today - datetime.timedelta(days=days)).strftime("%Y%m%d")
    date_to   = today.strftime("%Y%m%d")
    q_clean   = _cql_escape(query)
    if not q_clean:
        return []
    cql = f'(ti any "{q_clean}" OR ab any "{q_clean}") AND pd within "{date_from},{date_to}"'
    url = f"{EPO_SEARCH_BASE}/biblio"

    all_patents: list[dict] = []
    start = 1
    while start <= EPO_MAX_RESULTS:
        result, total = _epo_fetch_page(url, cql, start)

        if result is None:   # 401 — refresh token once
            if not _refresh_epo_token():
                _epo_disabled = True
                return all_patents
            result, total = _epo_fetch_page(url, cql, start)
            if result is None:
                _epo_disabled = True
                return all_patents

        if result == "throttle":   # 403 — wait and retry once
            print("  [EPO] 403 throttle — waiting 60s")
            time.sleep(60)
            result, total = _epo_fetch_page(url, cql, start)
            if result == "throttle":
                print("  [EPO] 403 persists — disabling EPO")
                _epo_disabled = True
                return all_patents

        if not result:       # empty / error
            break

        all_patents.extend(result)

        if total == 0 or len(result) < EPO_PAGE_SIZE or start + EPO_PAGE_SIZE - 1 >= min(total, EPO_MAX_RESULTS):
            break

        start += EPO_PAGE_SIZE
        time.sleep(DELAY_EPO)   # respect rate limit between pages

    return all_patents


def _get(obj, *keys, default=""):
    for k in keys:
        if not isinstance(obj, dict):
            return default
        obj = obj.get(k, default)
    return obj or default


def _as_list(val) -> list:
    if val is None:
        return []
    return val if isinstance(val, list) else [val]


def _parse_epo_json(data: dict) -> list[dict]:
    try:
        search_result = (
            data
            .get("ops:world-patent-data", {})
            .get("ops:biblio-search", {})
            .get("ops:search-result", {})
        )
        exchange_documents = search_result.get("exchange-documents", {})
        # exchange-documents is a list of {"exchange-document": ...} wrappers
        # OR a single dict with an "exchange-document" key
        if isinstance(exchange_documents, list):
            docs = []
            for wrapper in exchange_documents:
                docs.extend(_as_list(wrapper.get("exchange-document")))
        else:
            docs = _as_list(exchange_documents.get("exchange-document"))
    except Exception:
        return []

    out = []
    for doc in docs:
        try:
            p = _parse_epo_doc(doc)
            if p:
                out.append(p)
        except Exception:
            continue
    return out


def _norm_date(d: str) -> str:
    """Normalize EPO YYYYMMDD → YYYY-MM-DD; pass through anything else."""
    d = (d or "").strip()[:10]
    if len(d) == 8 and d.isdigit():
        return f"{d[:4]}-{d[4:6]}-{d[6:]}"
    return d


def _parse_epo_doc(doc: dict) -> dict | None:
    country       = doc.get("@country", "")
    doc_number    = doc.get("@doc-number", "")
    kind          = doc.get("@kind", "")
    patent_number = f"{country}{doc_number}{kind}" if country else doc_number

    bib = doc.get("bibliographic-data") or {}

    # Title (prefer English)
    titles = _as_list(bib.get("invention-title"))
    title  = next((_get(t, "$") for t in titles if _get(t, "@lang") == "en"), "")
    if not title and titles:
        title = _get(titles[0], "$")
    if not title:
        return None

    # Publication date — EPO returns YYYYMMDD, normalize to YYYY-MM-DD
    pub_ids  = _as_list(_get(bib, "publication-reference", "document-id"))
    pub_date = ""
    for pid in pub_ids:
        if _get(pid, "@document-id-type") == "epodoc":
            pub_date = _norm_date(_get(pid, "date", "$"))
            break
    if not pub_date:
        for pid in pub_ids:
            pub_date = _norm_date(_get(pid, "date", "$"))
            if pub_date:
                break

    # Filing date
    app_ids     = _as_list(_get(bib, "application-reference", "document-id"))
    filing_date = ""
    for aid in app_ids:
        filing_date = _norm_date(_get(aid, "date", "$"))
        if filing_date:
            break

    # Assignees
    applicants = _as_list(_get(bib, "parties", "applicants", "applicant"))
    asgn_names = []
    for a in applicants[:3]:
        name = _get(a, "applicant-name", "name")
        asgn_names.append((name.get("$", "") if isinstance(name, dict) else str(name)).strip())
    assignee = "; ".join(filter(None, asgn_names))
    if len(applicants) > 3:
        assignee += " et al."

    # Inventors
    inventors_raw = _as_list(_get(bib, "parties", "inventors", "inventor"))
    inv_names = []
    for i in inventors_raw[:3]:
        name = _get(i, "inventor-name", "name")
        inv_names.append((name.get("$", "") if isinstance(name, dict) else str(name)).strip())
    inventors = "; ".join(filter(None, inv_names))
    if len(inventors_raw) > 3:
        inventors += " et al."

    # IPC codes — EPO biblio uses classifications-ipcr; fall back to patent-classifications
    raw_cls = (
        _as_list(_get(bib, "classifications-ipcr", "classification-ipcr")) or
        _as_list(_get(bib, "patent-classifications", "patent-classification"))
    )
    ipc_codes = []
    for cl in raw_cls[:8]:
        # IPCR format: single "$" text like "B65D 65/46 20060101 A I"
        text = _get(cl, "$") or _get(cl, "text", "$")
        if text:
            code = text.strip().split()[0]  # take first token e.g. "B65D"
            if code:
                ipc_codes.append(code)
            continue
        # Structured format (patent-classification)
        scheme = _get(cl, "classification-scheme", "@scheme")
        if scheme not in ("IPC", "IPCR", ""):
            continue
        sec = _get(cl, "section", "$")
        cls_c = _get(cl, "class", "$")
        sub = _get(cl, "subclass", "$")
        mg  = _get(cl, "main-group", "$")
        sg  = _get(cl, "subgroup", "$")
        code = f"{sec}{cls_c}{sub}{mg}/{sg}".strip("/")
        if code:
            ipc_codes.append(code)
    ipc_codes = list(dict.fromkeys(ipc_codes))

    # Abstract (prefer English)
    abs_raw  = doc.get("abstract")
    abs_text = ""
    if abs_raw:
        abs_list = _as_list(abs_raw)
        abs_en   = next((a for a in abs_list if _get(a, "@lang") == "en"),
                        abs_list[0] if abs_list else {})
        p_val    = abs_en.get("p", "")
        if isinstance(p_val, list):
            abs_text = " ".join(
                (p.get("$", "") if isinstance(p, dict) else str(p)) for p in p_val
            )
        elif isinstance(p_val, dict):
            abs_text = p_val.get("$", "")
        else:
            abs_text = str(p_val)

    is_granted    = bool(_GRANTED_RE.match(kind)) if kind else False
    status        = "granted" if is_granted else "pending"
    year          = (pub_date or filing_date)[:4]
    # Google Patents reliably indexes only major jurisdictions; others return error pages.
    google_url    = (f"https://patents.google.com/patent/{patent_number}"
                     if patent_number and country in _GOOGLE_JURISDICTIONS else "")
    espacenet_url = (f"https://worldwide.espacenet.com/patent/search?q={patent_number}"
                     if patent_number else "")

    return {
        "patent_number": patent_number,
        "lens_id":       "",
        "title":         title.strip(),
        "abstract":      abs_text.strip(),
        "assignee":      assignee,
        "inventors":     inventors,
        "filing_date":   filing_date,
        "pub_date":      pub_date,
        "year":          year,
        "status":        status,
        "jurisdiction":  country or "EP",
        "ipc_codes":     ipc_codes,
        "patent_url":    espacenet_url,
        "google_url":    google_url,
        "citations":     0,
        "source":        "EPO",
    }

# ── USPTO PatentsView ──────────────────────────────────────────────────────────

_pv_disabled = False


def _patentsview_parse(patents_list: list) -> list[dict]:
    out = []
    for p in patents_list:
        pat_id        = (p.get("patent_id") or p.get("patentId") or "").strip()
        patent_number = f"US{pat_id}B2" if pat_id else ""

        assignees = p.get("assignees") or []
        asgn = "; ".join(
            (a.get("assignee_organization") or a.get("organization") or "").strip()
            for a in assignees[:3]
            if (a.get("assignee_organization") or a.get("organization"))
        )
        if len(assignees) > 3:
            asgn += " et al."

        inventors_list = p.get("inventors") or []
        inv_names = [
            f"{i.get('inventor_last_name','')}, {i.get('inventor_first_name','')}".strip(", ")
            for i in inventors_list[:3]
        ]
        inventors = "; ".join(filter(None, inv_names))
        if len(inventors_list) > 3:
            inventors += " et al."

        pub_date   = (p.get("patent_date") or p.get("grantDate") or "")[:10]
        year       = pub_date[:4] if pub_date else ""
        google_url = f"https://patents.google.com/patent/{patent_number}" if patent_number else ""

        out.append({
            "patent_number": patent_number,
            "lens_id":       "",
            "title":         (p.get("patent_title") or p.get("title") or "").strip(),
            "abstract":      (p.get("patent_abstract") or p.get("abstract") or "").strip(),
            "assignee":      asgn,
            "inventors":     inventors,
            "filing_date":   "",
            "pub_date":      pub_date,
            "year":          year,
            "status":        "granted",
            "jurisdiction":  "US",
            "ipc_codes":     [],
            "patent_url":    f"https://patents.google.com/patent/{patent_number}",
            "google_url":    google_url,
            "citations":     0,
            "source":        "PatentsView",
        })
    return out


def search_patentsview(query: str, days: int) -> list[dict]:
    """Search USPTO PatentsView for US granted patents.
    Tries v1 API (api.patentsview.org) first, falls back to v2."""
    global _pv_disabled
    if _pv_disabled:
        return []
    date_from = (datetime.date.today() - datetime.timedelta(days=days)).strftime("%Y-%m-%d")
    q = {
        "_and": [
            {"_or": [
                {"_text_any": {"patent_title":    query}},
                {"_text_any": {"patent_abstract": query}},
            ]},
            {"_gte": {"patent_date": date_from}},
        ]
    }
    f = [
        "patent_id", "patent_title", "patent_abstract", "patent_date",
        "assignees.assignee_organization",
        "inventors.inventor_first_name", "inventors.inventor_last_name",
    ]
    params = {"q": json.dumps(q), "f": json.dumps(f), "o": json.dumps({"per_page": 50})}
    headers = {"User-Agent": "patent-monitor/1.0"}

    for endpoint in (PATENTSVIEW_V1, PATENTSVIEW_V2):
        try:
            r = requests.get(endpoint, params=params, headers=headers, timeout=20)
            if r.status_code == 429:
                print("[PatentsView] rate limited — disabling for this run")
                _pv_disabled = True
                return []
            if r.status_code == 200:
                patents = r.json().get("patents") or []
                if isinstance(patents, list):
                    return _patentsview_parse(patents)
        except Exception as e:
            err = str(e)
            is_dns = ("NameResolutionError" in err or "Failed to resolve" in err
                      or "ConnectionError" in type(e).__name__)
            if not is_dns:
                print(f"  [PatentsView] '{query}' ({endpoint}): {e}")
            # try next endpoint

    print(f"[PatentsView] both endpoints failed — disabling")
    _pv_disabled = True
    return []

# ── Deduplication & merging ────────────────────────────────────────────────────

def _norm_id(pid: str) -> str:
    return re.sub(r'[\s\-]', '', (pid or "").upper().strip())


def merge_patents(raw: list[dict]) -> list[dict]:
    by_id: dict[str, dict] = {}
    no_id: list[dict]      = []

    for p in raw:
        nid = _norm_id(p.get("patent_number", ""))
        synthetic = nid.startswith("WO-")
        if nid and not synthetic:
            if nid in by_id:
                ex = by_id[nid]
                if len(p.get("abstract", "")) > len(ex.get("abstract", "")):
                    ex["abstract"] = p["abstract"]
                if (p.get("citations") or 0) > (ex.get("citations") or 0):
                    ex["citations"] = p["citations"]
                for f in ("assignee", "inventors", "filing_date", "ipc_codes",
                          "lens_id", "google_url", "patent_url"):
                    if not ex.get(f) and p.get(f):
                        ex[f] = p[f]
                srcs = set(ex["source"].split(" + ")) | {p["source"]}
                ex["source"] = " + ".join(sorted(srcs))
                if p.get("status") == "granted":
                    ex["status"] = "granted"
            else:
                by_id[nid] = {**p}
        else:
            no_id.append(p)

    seen_titles: set[str] = set()
    for p in no_id:
        key = re.sub(r'\s+', ' ', (p.get("title", "")).lower().strip())[:80]
        if key and key not in seen_titles:
            seen_titles.add(key)
            by_id[f"__notitle__{key}"] = p

    return list(by_id.values())


def load_existing() -> list[dict]:
    if not OUTPUT_JSON.exists():
        return []
    try:
        data = json.loads(OUTPUT_JSON.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return data
    except Exception as e:
        print(f"[load_existing] {e}")
    return []


def merge_with_existing(new_patents: list[dict], existing: list[dict]) -> list[dict]:
    new_by_id     : set[str] = set()
    new_title_keys: set[str] = set()

    for p in new_patents:
        nid = _norm_id(p.get("patent_number", ""))
        if nid and not nid.startswith("WO-"):
            new_by_id.add(nid)
        else:
            key = re.sub(r'\s+', ' ', p.get("title", "").lower().strip())[:80]
            if key:
                new_title_keys.add(key)

    retained = []
    for p in existing:
        nid = _norm_id(p.get("patent_number", ""))
        if nid and not nid.startswith("WO-"):
            if nid not in new_by_id:
                retained.append(p)
        else:
            key = re.sub(r'\s+', ' ', p.get("title", "").lower().strip())[:80]
            if key and key not in new_title_keys:
                retained.append(p)

    combined = new_patents + retained
    combined.sort(key=lambda p: p.get("score", 0), reverse=True)
    return combined

# ── Scoring ─────────────────────────────────────────────────────────────────────

CUTOFF_DATE = datetime.date(2022, 1, 1)


def _patent_date(patent: dict) -> datetime.date | None:
    for field in ("pub_date", "filing_date", "year"):
        raw = (patent.get(field) or "").strip()
        if not raw:
            continue
        for fmt, length in (("%Y-%m-%d", 10), ("%Y-%m", 7), ("%Y", 4)):
            try:
                return datetime.datetime.strptime(raw[:length], fmt).date()
            except ValueError:
                continue
    return None


def score_patent(patent: dict, n_tags: int) -> int:
    s = min(n_tags * 15, 60)
    d = _patent_date(patent)
    if d:
        cy = datetime.date.today().year
        py = d.year
        s += 25 if py == cy else (15 if py == cy - 1 else (5 if py >= cy - 2 else 0))
    if patent.get("abstract"):
        s += 10
    if patent.get("status") == "granted":
        s += 10
    if patent.get("must_match"):
        s += 10
    cit = patent.get("citations") or 0
    s += 20 if cit >= 20 else (10 if cit >= 5 else (5 if cit >= 1 else 0))
    return s


def normalize_scores(patents: list[dict]) -> None:
    if not patents:
        return
    raw     = [p.get("raw_score", 0) for p in patents]
    lo, hi  = min(raw), max(raw)
    span    = hi - lo
    for p in patents:
        p["score"] = round((p["raw_score"] - lo) / span * 100) if span else 100

# ── Readable text export ───────────────────────────────────────────────────────

def write_readable_txt(patents: list[dict], path: Path) -> None:
    from collections import defaultdict
    today  = datetime.date.today().isoformat()
    subset = patents[:500]
    by_domain: dict[str, list] = defaultdict(list)
    for p in subset:
        by_domain[(p.get("domain") or "General")].append(p)

    lines = [
        "PATENT MONITOR — TECH VIGILANCE R&D",
        f"Last updated : {today}",
        f"Total patents: {len(subset)}",
        "",
    ]
    for domain in sorted(by_domain.keys()):
        lines += ["=" * 60, f"DOMAIN: {domain}", "=" * 60, ""]
        for p in by_domain[domain]:
            ipc_str = ", ".join(p.get("ipc_codes") or [])
            lines += [
                f"TITLE      : {(p.get('title') or '').strip()}",
                f"PATENT     : {p.get('patent_number','')}  [{p.get('jurisdiction','')}]  {p.get('status','').upper()}",
                f"ASSIGNEE   : {p.get('assignee','')}",
                f"INVENTORS  : {p.get('inventors','')}",
                f"FILED      : {p.get('filing_date','')}   PUB: {p.get('pub_date','')}",
                f"IPC        : {ipc_str}",
                f"SCORE      : {p.get('score','')}",
                f"LINK       : {p.get('patent_url','') or p.get('google_url','')}",
                f"ABSTRACT   : {(p.get('abstract') or '')[:500]}",
                "", "---", "",
            ]

    path.write_text("\n".join(lines), encoding="utf-8")
    print(f"patents_readable.txt  ->  {len(subset)} patents")

# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    today = datetime.date.today().isoformat()
    print(f"Patent fetcher — {today}  ({DAYS_BACK} days back)")
    print(f"Sources: EPO OPS (paginated, up to {EPO_MAX_RESULTS}/query)  |  USPTO PatentsView (v1+v2)\n")
    if not (EPO_OPS_KEY and EPO_OPS_SECRET):
        print("[EPO] No EPO_OPS_KEY / EPO_OPS_SECRET set — EPO disabled.")
        print("      Register free at https://developers.epo.org\n")

    tags = load_tags(TAGS_FILE)
    print(f"Loaded {len(tags)} active tag(s)\n")

    all_raw: list[dict]           = []
    tag_index:    dict[str, list] = {}
    domain_index: dict[str, str]  = {}
    must_index:   dict[str, bool] = {}

    for tag_info in tags:
        tag     = tag_info["tag"]
        domain  = tag_info["domain"]
        queries = [tag] + tag_info["synonyms"]
        print(f"-- {tag}  [{domain}]")

        batch: list[dict] = []
        seen_ids: set[str] = set()

        for query in queries:
            # EPO OPS: EP, WO, GB, FR, DE and 50+ patent offices
            for p in search_epo(query, DAYS_BACK):
                nid = _norm_id(p.get("patent_number", ""))
                if not nid or nid not in seen_ids:
                    if nid:
                        seen_ids.add(nid)
                    batch.append(p)
            time.sleep(DELAY_EPO)

            # USPTO PatentsView: US granted patents
            for p in search_patentsview(query, DAYS_BACK):
                nid = _norm_id(p.get("patent_number", ""))
                if nid and nid not in seen_ids:
                    seen_ids.add(nid)
                    batch.append(p)
            time.sleep(DELAY)

        # mustInclude soft bonus
        must = tag_info["mustInclude"]
        if must:
            for p in batch:
                haystack = (p.get("title", "") + " " + p.get("abstract", "")).lower()
                if all(m.lower() in haystack for m in must):
                    nid = _norm_id(p.get("patent_number", ""))
                    k   = nid if nid else f"__notitle__{p.get('title','')[:80].lower()}"
                    if k:
                        must_index[k] = True

        for p in batch:
            nid = _norm_id(p.get("patent_number", ""))
            key = nid if nid else f"__notitle__{p.get('title','')[:80].lower()}"
            if not key:
                continue
            p["domain"] = domain
            if key not in tag_index:
                tag_index[key]    = []
                domain_index[key] = domain
            tag_index[key].append(tag)

        all_raw.extend(batch)
        print(f"   raw: {len(batch)}")

    print(f"\nTotal raw  : {len(all_raw)}")
    if not all_raw:
        existing_count = len(load_existing())
        print(
            f"[WARNING] All sources returned 0 patents.\n"
            f"          Existing patents.json preserved ({existing_count} patents).\n"
            f"          Check API credentials (EPO_OPS_KEY/EPO_OPS_SECRET) and source availability."
        )
        return

    merged = merge_patents(all_raw)
    print(f"After dedup: {len(merged)}")
    merged = [p for p in merged if (_patent_date(p) or datetime.date(2020, 1, 1)) >= CUTOFF_DATE]
    print(f"After {CUTOFF_DATE} cutoff: {len(merged)}\n")

    today_iso = datetime.date.today().isoformat()
    for patent in merged:
        nid = _norm_id(patent.get("patent_number", ""))
        key = nid if nid else f"__notitle__{patent.get('title','')[:80].lower()}"
        tags_for               = sorted(set(tag_index.get(key, [])))
        patent["matched_tags"] = tags_for
        patent["domain"]       = domain_index.get(key, patent.get("domain", "General"))
        patent["must_match"]   = must_index.get(key, False)
        patent["raw_score"]    = score_patent(patent, len(tags_for))
        patent["score"]        = patent["raw_score"]
        patent["fetch_date"]   = today_iso

    existing = load_existing()
    if existing:
        new_count = len(merged)
        merged    = merge_with_existing(merged, existing)
        retained  = len(merged) - new_count
        print(f"Merged: {new_count} new + {retained} retained = {len(merged)} total\n")
    else:
        print("No existing patents.json — writing fresh file\n")

    for p in merged:
        if "raw_score" not in p:
            p["raw_score"] = score_patent(p, len(p.get("matched_tags") or []))

    normalize_scores(merged)
    merged.sort(key=lambda p: p.get("score", 0), reverse=True)

    OUTPUT_JSON.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"patents.json  ->  {len(merged)} patents")

    FIELDS = [
        "score", "raw_score", "patent_number", "lens_id", "title",
        "assignee", "inventors", "filing_date", "pub_date", "year",
        "status", "jurisdiction", "ipc_codes", "patent_url", "google_url",
        "domain", "matched_tags", "must_match", "citations", "source",
        "fetch_date", "abstract",
    ]
    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        w.writeheader()
        for p in merged:
            row = dict(p)
            row["matched_tags"] = "; ".join(row.get("matched_tags") or [])
            row["ipc_codes"]    = "; ".join(row.get("ipc_codes") or [])
            w.writerow(row)
    print(f"patents.csv  ->  {OUTPUT_CSV.name}")

    write_readable_txt(merged, OUTPUT_READABLE)


if __name__ == "__main__":
    main()
