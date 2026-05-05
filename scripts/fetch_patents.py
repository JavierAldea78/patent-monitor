#!/usr/bin/env python3
"""
Tech vigilance patent fetcher.
Sources: EPO Open Patent Services (EP/WO/GB/FR/DE…), WIPO PATENTSCOPE (PCT/WO), USPTO PatentsView (US).
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

DAYS_BACK  = 730   # 2 years — patents publish slower than papers
DELAY      = 0.5   # seconds between WIPO / PatentsView calls
DELAY_EPO  = 0.35  # ~3 req/sec — EPO OPS registered limit is 4/sec

EPO_OPS_KEY    = os.environ.get("EPO_OPS_KEY", "").strip()
EPO_OPS_SECRET = os.environ.get("EPO_OPS_SECRET", "").strip()

EPO_AUTH_URL   = "https://ops.epo.org/3.2/auth/accesstoken"
EPO_SEARCH_URL = "https://ops.epo.org/3.2/rest-services/published-data/search/biblio,abstract"
WIPO_RSS       = "https://patentscope.wipo.int/search/en/rss.jsf"
PATENTSVIEW    = "https://search.patentsview.org/api/v1/patent/"

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
        "Range":         "items=1-25",
    }


def _cql_escape(text: str) -> str:
    cleaned = re.sub(r'["\\/()&|!{}^]', ' ', text).strip()
    cleaned = re.sub(r'\s+', ' ', cleaned)
    return cleaned[:100]


def search_epo(query: str, days: int) -> list[dict]:
    """Search EPO OPS — covers EP, WO, GB, FR, DE and 50+ patent offices."""
    global _epo_disabled
    if _epo_disabled or not (EPO_OPS_KEY and EPO_OPS_SECRET):
        return []
    date_from = (datetime.date.today() - datetime.timedelta(days=days)).strftime("%Y%m%d")
    q_clean   = _cql_escape(query)
    if not q_clean:
        return []
    cql = f'(ti any "{q_clean}" OR ab any "{q_clean}") AND pd>={date_from}'
    try:
        r = requests.get(
            EPO_SEARCH_URL, params={"q": cql},
            headers=_epo_headers(), timeout=30,
        )
        if r.status_code in (401, 403):
            if not _refresh_epo_token():
                _epo_disabled = True
                return []
            r = requests.get(EPO_SEARCH_URL, params={"q": cql},
                             headers=_epo_headers(), timeout=30)
        if r.status_code == 404:
            return []  # no results
        if r.status_code == 429:
            print("  [EPO] Rate limited — waiting 15s")
            time.sleep(15)
            r = requests.get(EPO_SEARCH_URL, params={"q": cql},
                             headers=_epo_headers(), timeout=30)
        if r.status_code in (500, 503):
            print(f"  [EPO] Server error {r.status_code}")
            return []
        r.raise_for_status()
        return _parse_epo_json(r.json())
    except Exception as e:
        print(f"  [EPO] '{query}': {e}")
        return []


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
        docs = _as_list(
            search_result
            .get("exchange-documents", {})
            .get("exchange-document")
        )
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

    # Publication date
    pub_ids  = _as_list(_get(bib, "publication-reference", "document-id"))
    pub_date = ""
    for pid in pub_ids:
        if _get(pid, "@document-id-type") == "epodoc":
            pub_date = _get(pid, "date", "$")[:10]
            break
    if not pub_date:
        for pid in pub_ids:
            pub_date = _get(pid, "date", "$")[:10]
            if pub_date:
                break

    # Filing date
    app_ids     = _as_list(_get(bib, "application-reference", "document-id"))
    filing_date = ""
    for aid in app_ids:
        filing_date = _get(aid, "date", "$")[:10]
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

    # IPC codes
    classifications = _as_list(_get(bib, "patent-classifications", "patent-classification"))
    ipc_codes = []
    for cl in classifications[:8]:
        scheme = _get(cl, "classification-scheme", "@scheme")
        if scheme not in ("IPC", "IPCR", ""):
            continue
        sec = _get(cl, "section", "$")
        cls = _get(cl, "class", "$")
        sub = _get(cl, "subclass", "$")
        mg  = _get(cl, "main-group", "$")
        sg  = _get(cl, "subgroup", "$")
        code = f"{sec}{cls}{sub}{mg}/{sg}".strip("/")
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
    google_url    = (f"https://patents.google.com/patent/{patent_number}/en"
                     if patent_number else "")
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

# ── WIPO PATENTSCOPE ───────────────────────────────────────────────────────────

_wipo_disabled = False


def search_wipo(query: str, days: int) -> list[dict]:
    """Search WIPO PATENTSCOPE for PCT (WO) publications via RSS feed."""
    global _wipo_disabled
    if _wipo_disabled:
        return []
    date_from = (datetime.date.today() - datetime.timedelta(days=days)).strftime("%Y%m%d")
    params = {
        "query": f"EN_TITLEAB:({query}) AND PD:[{date_from} TO *]",
        "office": "WO",
        "rss":    "1",
    }
    try:
        r = requests.get(
            WIPO_RSS, params=params, timeout=20,
            headers={"User-Agent": "patent-monitor/1.0 (non-commercial research)"},
        )
        if r.status_code in (403, 503):
            print("[WIPO] endpoint unavailable — disabling WIPO for this run")
            _wipo_disabled = True
            return []
        r.raise_for_status()
        return _parse_wipo_rss(r.text)
    except Exception as e:
        print(f"  [WIPO] '{query}': {e}")
        return []


def _parse_wipo_rss(xml_text: str) -> list[dict]:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []

    items = root.findall(".//item")
    atom_ns = "{http://www.w3.org/2005/Atom}"
    if not items:
        items = root.findall(f".//{atom_ns}entry")

    out = []
    for item in items:
        def _txt(tag: str, atom_tag: str = "") -> str:
            el = item.find(tag) or (item.find(atom_tag) if atom_tag else None)
            return (el.text or "").strip() if el is not None else ""

        title  = _txt("title", f"{atom_ns}title")
        link   = _txt("link", f"{atom_ns}id")
        pubraw = _txt("pubDate", f"{atom_ns}published") or _txt("", f"{atom_ns}updated")
        desc   = _txt("description", f"{atom_ns}summary")

        if not title:
            continue

        pub_date = pubraw[:10] if pubraw and len(pubraw) >= 10 else ""
        year     = pub_date[:4] if pub_date else ""

        m = re.search(r'(WO\s*\d{4}[\s/]?\d+)', link + " " + title)
        patent_number = re.sub(r'[\s/]', '', m.group(1)) if m else ""

        abstract   = re.sub(r"<[^>]+>", "", desc).strip()
        google_url = (f"https://patents.google.com/patent/{patent_number}/en"
                      if patent_number else "")

        out.append({
            "patent_number": patent_number or f"WO-{title[:30]}",
            "lens_id":       "",
            "title":         title,
            "abstract":      abstract,
            "assignee":      "",
            "inventors":     "",
            "filing_date":   "",
            "pub_date":      pub_date,
            "year":          year,
            "status":        "pending",
            "jurisdiction":  "WO",
            "ipc_codes":     [],
            "patent_url":    link,
            "google_url":    google_url,
            "citations":     0,
            "source":        "WIPO",
        })
    return out

# ── USPTO PatentsView ──────────────────────────────────────────────────────────

_pv_disabled = False


def search_patentsview(query: str, days: int) -> list[dict]:
    """Search USPTO PatentsView for US granted patents (no API key required)."""
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
        "patent_id", "patent_title", "patent_abstract", "patent_date", "patent_type",
        "assignees.assignee_organization",
        "inventors.inventor_first_name", "inventors.inventor_last_name",
    ]
    try:
        r = requests.get(
            PATENTSVIEW,
            params={
                "q": json.dumps(q),
                "f": json.dumps(f),
                "o": json.dumps({"per_page": 25}),
            },
            headers={"User-Agent": "patent-monitor/1.0"},
            timeout=20,
        )
        if r.status_code == 429:
            print("[PatentsView] rate limited — disabling for this run")
            _pv_disabled = True
            return []
        r.raise_for_status()

        out = []
        for p in (r.json().get("patents") or []):
            pat_id        = (p.get("patent_id") or "").strip()
            patent_number = f"US{pat_id}B2" if pat_id else ""

            assignees = p.get("assignees") or []
            asgn = "; ".join(
                (a.get("assignee_organization") or "").strip()
                for a in assignees[:3]
                if a.get("assignee_organization")
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

            pub_date   = (p.get("patent_date") or "")[:10]
            year       = pub_date[:4] if pub_date else ""
            google_url = f"https://patents.google.com/patent/{patent_number}/en" if patent_number else ""

            out.append({
                "patent_number": patent_number,
                "lens_id":       "",
                "title":         (p.get("patent_title") or "").strip(),
                "abstract":      (p.get("patent_abstract") or "").strip(),
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
    except Exception as e:
        print(f"  [PatentsView] '{query}': {e}")
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
    print(f"Sources: EPO OPS  |  WIPO PATENTSCOPE  |  USPTO PatentsView\n")
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

            # WIPO PATENTSCOPE: PCT / WO publications (supplementary)
            for p in search_wipo(query, DAYS_BACK):
                nid = _norm_id(p.get("patent_number", ""))
                synthetic = nid.startswith("WO-")
                if synthetic or nid not in seen_ids:
                    if nid and not synthetic:
                        seen_ids.add(nid)
                    batch.append(p)
            time.sleep(DELAY)

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
