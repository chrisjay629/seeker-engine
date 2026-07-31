"""Auto-map generator (integration #27 capstone) — Seeker produces its OWN shareable map.

Turns a director dossier dict into a self-contained, theme-aware HTML investigation map — the thing
that used to be hand-crafted every time. Now the flagship run emits it. Pure templating (no LLM);
every piece of finding text is html.escaped (Ghost: no injection). Leads with Quill's narrative, then
the structured evidence, and — for honesty — shows the CONTRIBUTION LEDGER so a reader can see which
organs actually fired.
"""
from __future__ import annotations

import html
import os

_CSS = """
:root{--ink:#0E1116;--panel:#161B22;--panel2:#1C2430;--line:#26303F;--text:#E7ECF3;--muted:#8B98AB;
--faint:#5E6B7E;--signal:#E0A22E;--ok:#3FB37F;--warn:#E0A22E;--bad:#E0574B;--blue:#5B8DEF;
--sans:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
--mono:ui-monospace,"SF Mono",Menlo,Consolas,monospace;--serif:"Iowan Old Style",Palatino,Georgia,serif;}
:root[data-theme="light"]{--ink:#F3F1EA;--panel:#FBFAF6;--panel2:#F0EDE3;--line:#D9D4C6;--text:#1A1D22;
--muted:#5C6470;--faint:#8A8577;--blue:#2C5FC7;}
@media (prefers-color-scheme:light){:root:not([data-theme="dark"]){--ink:#F3F1EA;--panel:#FBFAF6;
--panel2:#F0EDE3;--line:#D9D4C6;--text:#1A1D22;--muted:#5C6470;--faint:#8A8577;--blue:#2C5FC7;}}
*{box-sizing:border-box}body{margin:0}
.wrap{background:var(--ink);color:var(--text);font-family:var(--sans);line-height:1.65;padding:0 0 4rem;-webkit-font-smoothing:antialiased}
.inner{max-width:820px;margin:0 auto;padding:0 24px}
h1,h2{font-weight:600;margin:0;text-wrap:balance}
header{border-bottom:1px solid var(--line);padding:2.4rem 0 1.6rem;margin-bottom:1.8rem}
.eyebrow{font-family:var(--mono);font-size:11.5px;letter-spacing:.18em;text-transform:uppercase;color:var(--signal)}
h1.t{font-size:clamp(26px,5vw,40px);line-height:1.1;margin-top:.7rem}
.report{font-family:var(--serif);font-size:18px;line-height:1.7;white-space:pre-wrap;margin:1.5rem 0}
section{margin:2.4rem 0}
.sh{font-family:var(--mono);font-size:12px;letter-spacing:.14em;text-transform:uppercase;color:var(--signal);margin-bottom:1rem}
.row{background:var(--panel);border:1px solid var(--line);border-radius:9px;padding:10px 13px;margin-bottom:7px;display:flex;justify-content:space-between;gap:12px;align-items:baseline}
.row .m{font-size:14px}.row .tag{font-family:var(--mono);font-size:10px;letter-spacing:.08em;text-transform:uppercase;padding:3px 8px;border-radius:3px;white-space:nowrap}
.ok{color:var(--ok);border:1px solid var(--ok)}.warn{color:var(--warn);border:1px solid var(--warn)}
.bad{color:var(--bad);border:1px solid var(--bad)}.blue{color:var(--blue);border:1px solid var(--blue)}
.thread{font-size:13.5px;color:var(--text);padding-left:16px;position:relative;margin:5px 0}
.thread::before{content:"?";position:absolute;left:0;color:var(--signal);font-family:var(--mono)}
.conn{font-size:13.5px;margin:5px 0}.conn .e{color:var(--blue)}
footer{border-top:1px solid var(--line);margin-top:2.5rem;padding-top:1.4rem;font-family:var(--mono);font-size:11px;color:var(--faint);line-height:1.7}
.led{font-family:var(--mono);font-size:11.5px;color:var(--muted)}
.led .d{color:var(--bad)}.led .a{color:var(--faint)}
.prof{background:var(--panel);border:1px solid var(--line);border-radius:9px;padding:11px 14px;margin-bottom:8px}
.prof-h{display:flex;gap:10px;align-items:baseline;flex-wrap:wrap}.prof-h .m{font-size:14.5px;font-weight:600}
.prof-h .e{color:var(--muted);font-size:12.5px}
.prof-d{font-size:13px;color:var(--muted);margin-top:5px;line-height:1.55}
"""


def _e(x) -> str:
    return html.escape(str(x or ""))


def _verdict_class(v: str) -> str:
    v = (v or "").lower()
    return "ok" if v in ("verified", "well-supported") else \
        "bad" if v in ("debunked", "refuted", "disproven") else \
        "blue" if v == "survives" else "warn"


def _status_class(s: str) -> str:
    """Badge color for an entity's status: deceased=bad, found-safe=ok, missing/investigating=warn."""
    s = (s or "").lower()
    return "bad" if "deceas" in s or "dead" in s else \
        "ok" if "found" in s or "safe" in s else \
        "blue" if "dispute" in s else "warn"


def build_map(d: dict) -> str:
    """Render a dossier dict to a self-contained HTML map (theme-aware, escaped). Returns the HTML."""
    subject = _e(d.get("subject", "Investigation"))
    parts = [f'<style>{_CSS}</style>', '<div class="wrap"><div class="inner">']
    parts.append(f'<header><div class="eyebrow">Seeker // Investigation Map</div>'
                 f'<h1 class="t">{subject}</h1></header>')

    rep = (d.get("report") or {}).get("report", "")
    if rep:
        parts.append(f'<div class="report">{_e(rep)}</div>')

    ents = d.get("entities", []) or []
    profiles = {p.get("name", ""): p for p in (d.get("entity_profiles", []) or [])}
    if ents:
        parts.append('<section><div class="sh">Entities investigated</div>')
        for e in ents[:30]:
            p = profiles.get(e)
            if p:
                status = _e(p.get("status", "unknown"))
                cause = _e(p.get("cause", ""))
                detail = _e(p.get("detail", ""))
                cause_html = (f'<span class="e"> · {cause}</span>' if cause else "")
                parts.append(
                    f'<div class="prof"><div class="prof-h"><span class="m">{_e(e)}</span>'
                    f'<span class="tag {_status_class(p.get("status",""))}">{status.upper()}</span>'
                    f'{cause_html}</div>'
                    f'<div class="prof-d">{detail}</div></div>')
            else:
                parts.append(f'<div class="row"><span class="m">{_e(e)}</span></div>')
        parts.append('</section>')

    ach = d.get("ach", []) or []
    if ach:
        parts.append('<section><div class="sh">Competing hypotheses (ACH)</div>')
        for a in ach:
            v = a.get("verdict", "")
            parts.append(f'<div class="row"><span class="m">{_e(a.get("hypothesis",""))}</span>'
                         f'<span class="tag {_verdict_class(v)}">{_e(v).upper()}</span></div>')
        parts.append('</section>')

    ledger = d.get("claim_ledger", []) or []
    if ledger:
        parts.append('<section><div class="sh">Claim ledger — verdict &amp; directional lean</div>')
        for c in ledger:
            lean = c.get("lean", "balanced")
            tilt = "—" if lean == "balanced" else f'{_e(c.get("magnitude",""))} {_e(lean)}'
            parts.append(f'<div class="row"><span class="m">{_e(c.get("claim",""))} '
                         f'<span class="led">· lean: {tilt}</span></span>'
                         f'<span class="tag {_verdict_class(c.get("verdict",""))}">'
                         f'{_e(c.get("verdict","")).upper()}</span></div>')
        parts.append('</section>')

    conns = d.get("connections", {}) or {}
    if conns.get("connections") or conns.get("non_connections"):
        parts.append('<section><div class="sh">Connections — Seeker\'s own cross-entity analysis</div>')
        for c in conns.get("connections", [])[:8]:
            parts.append(f'<div class="conn"><span class="e">↔ {_e(", ".join(c.get("entities",[])))}</span>'
                         f' — {_e(c.get("link",""))}</div>')
        for n in conns.get("non_connections", [])[:8]:
            parts.append(f'<div class="conn" style="color:var(--muted)">✗ {_e(n)}</div>')
        parts.append('</section>')

    pc = d.get("pattern_claims", {}) or {}
    pats = pc.get("claimed_patterns", [])
    if pats:
        parts.append('<section><div class="sh">Claimed patterns — who says they found a pattern, '
                     'and does it hold up?</div>')
        for p in pats[:12]:
            v = p.get("verdict", "unverified")
            parts.append(f'<div class="row"><span class="m">{_e(p.get("pattern",""))}</span>'
                         f'<span class="tag {_verdict_class(v)}">{_e(v).upper()}</span></div>')
            who = ", ".join(f'{c.get("who","")} ({c.get("credibility","")})'
                            for c in p.get("claimants", [])[:3])
            if who:
                parts.append(f'<div class="conn" style="color:var(--muted)">claimed by: {_e(who)}</div>')
            for a in p.get("atomic_links", [])[:5]:
                parts.append(f'<div class="conn">• <b>{_e(a.get("verdict",""))}</b> — '
                             f'{_e(a.get("link",""))}</div>')
            if v == "unresolved-notable":
                if p.get("why_notable"):
                    parts.append(f'<div class="conn">↳ why notable: {_e(p["why_notable"])}</div>')
                if p.get("why_unproven"):
                    parts.append(f'<div class="conn">↳ why unproven: {_e(p["why_unproven"])}</div>')
            if p.get("connects_to_factual"):
                parts.append(f'<div class="conn" style="color:var(--accent)">↳ touches real '
                             f'connective tissue: {_e(p["connects_to_factual"])}</div>')
        if pc.get("folded_count"):
            parts.append(f'<div class="conn" style="color:var(--muted)">… {int(pc["folded_count"])} '
                         f'low-credibility fringe variants folded (noise, not listed)</div>')
        for b in pc.get("selection_bias_flags", [])[:3]:
            parts.append(f'<div class="conn" style="color:var(--muted)">⚠ selection bias: {_e(b)}</div>')
        parts.append('</section>')

    threads = d.get("open_threads", []) or []
    if threads:
        parts.append('<section><div class="sh">Open threads</div>')
        for t in threads[:12]:
            parts.append(f'<div class="thread">{_e(t)}</div>')
        parts.append('</section>')

    # honesty layer: show what actually fired
    contrib = d.get("contribution", []) or []
    if contrib:
        parts.append('<footer><div style="margin-bottom:.6rem">ORGAN CONTRIBUTION — what actually fired this run:</div>')
        for r in contrib:
            st = r.get("status", "")
            cls = "d" if ("DEAD" in st or "ABSENT" in st) else "a"
            parts.append(f'<div class="led"><span class="{cls}">{_e(r.get("organ",""))}: '
                         f'{_e(r.get("added",""))} [{_e(st)}]</span></div>')
        parts.append('<div style="margin-top:1rem">Compiled by Seeker · podcast discovery via '
                     '<a href="https://podcastindex.org" style="color:var(--signal)">Podcast Index</a> '
                     '· Gambit / Christopher Jauregui</div></footer>')
    parts.append('</div></div>')
    return "\n".join(parts)


def write_map(d: dict, *, branch_id: str = "main", out_dir: str = "runs/maps") -> str:
    """Build the map and write it to out_dir/<branch>.html. Returns the path (or '' on failure)."""
    try:
        os.makedirs(out_dir, exist_ok=True)
        path = os.path.join(out_dir, f"{branch_id}.html")
        with open(path, "w") as f:
            f.write("<!doctype html><meta charset='utf-8'><title>" +
                    _e(d.get("subject", "Seeker map"))[:80] + "</title>" + build_map(d))
        return path
    except Exception:
        return ""
