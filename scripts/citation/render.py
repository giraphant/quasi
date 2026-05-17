#!/usr/bin/env python3
"""Render manifest.json (+ optional verdicts/) into review-pass1.html.

Two input shapes:

    render --pass 1 manifest.json [--verdicts <dir>] -o review-pass1.html

If verdicts/ given, each `verdicts/batch-NNN.json` carries:
    {"batch_id": "001", "verdicts": [{"key": ..., "verdict": ..., ...}, ...]}
and they get merged onto manifest entries by `key` before render.

The HTML has:
    - top banner: missing-from-vault + maybe-vault-typo lists with copy-paste
      command snippets to fix
    - per-row single decision (accept agent suggestion?  ✓ ✗ ?)
    - per-row bib chooser (radio: which biblio entry feeds references.bib)
    - groups by verdict status; `ok` collapsed by default
    - export decisions.json button

verdict values (Pass 1 = mode=vault-fit):
    ok                  - 主题契合 + 引用准确, 默认放行
    context-mismatch    - 主题不契合, agent 给 draft_suggestion
    maybe-vault-typo    - vault 里可能有但 slug 漂了, agent 给 hint
    missing-from-vault  - 真 missing, 需要补
"""
from __future__ import annotations

import html
import json
import sys
from pathlib import Path


# ---- styling -----------------------------------------------------------------

_CSS = """
body{font-family:"PingFang SC","Hiragino Sans GB","Microsoft YaHei","Noto Sans CJK SC","Source Han Sans SC",sans-serif;font-size:14px;line-height:1.55;color:#1a1a1a;margin:0;padding:0;background:#fafafa}
.wrap{max-width:1200px;margin:0 auto;padding:1rem 1.5rem 4rem}
.toolbar{position:sticky;top:0;background:#fff;border-bottom:1px solid #ddd;padding:10px 16px;z-index:10;display:flex;gap:14px;align-items:center;font-size:13px;box-shadow:0 1px 3px rgba(0,0,0,.04)}
.toolbar .title{color:#888;font-weight:500}
.filters{display:flex;gap:6px;margin-left:auto}
.filter-btn{background:#f0f0f0;border:1px solid #ddd;padding:4px 10px;border-radius:14px;cursor:pointer;font-family:inherit;font-size:12px;color:#555}
.filter-btn.active{background:#1a4f8a;color:#fff;border-color:#1a4f8a}
button.export{background:#1d6b3a;color:#fff;border:0;padding:6px 14px;border-radius:4px;cursor:pointer;font-family:inherit;margin-left:8px}
.banner{background:#fde2e2;border-left:4px solid #b01010;padding:12px 16px;margin:14px 0;border-radius:4px;font-size:13px;line-height:1.7;color:#5a1010}
.banner h3{margin:0 0 6px;font-size:13px;color:#8a1010}
.banner ul{margin:6px 0;padding-left:20px}
.banner code{background:#fff5f5;padding:1px 5px;border-radius:3px;color:#8a1010;font-size:12.5px}
.banner-warn{background:#fff4d4;border-left-color:#b08000;color:#5a4500}
.banner-warn h3{color:#7a5a00}
.banner-warn code{background:#fffbe6;color:#7a5a00}
table.main{width:100%;border-collapse:collapse;background:#fff;font-size:13px;margin-top:8px}
table.main thead th{background:#f5f7fa;color:#555;font-weight:600;text-align:left;padding:8px 10px;font-size:12px;border-bottom:1px solid #ddd;white-space:nowrap}
table.main tbody tr.row{border-bottom:1px solid #f0f0f0;cursor:pointer;transition:background .12s}
table.main tbody tr.row:hover{background:#fafbfd}
table.main tbody tr.row td{padding:7px 10px;vertical-align:middle}
.caret{color:#bbb;font-size:11px}
.cell-status{white-space:nowrap}
.cell-ctx{max-width:340px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.cell-note input{width:90%;border:1px solid #e0e0e0;background:#fff;padding:3px 6px;border-radius:3px;font-size:12px;font-family:inherit}
.dec-grp{display:inline-flex;border:1px solid #ddd;border-radius:4px;overflow:hidden;background:#fff}
.dec-btn{background:#fff;border:0;padding:3px 9px;cursor:pointer;font-size:13px;color:#aaa;font-family:inherit;border-right:1px solid #eee;font-weight:600}
.dec-btn:last-child{border-right:0}
.dec-btn:hover{background:#fafafa}
.dec-btn.ok.active{background:#1d6b3a;color:#fff}
.dec-btn.no.active{background:#8a1010;color:#fff}
.dec-btn.pd.active{background:#888;color:#fff}
.action-grp{display:inline-flex;border:1px solid #ddd;border-radius:4px;overflow:hidden;background:#fff;white-space:nowrap}
.act-btn{background:#fff;border:0;padding:4px 11px;cursor:pointer;font-size:12.5px;color:#888;font-family:inherit;border-right:1px solid #eee;font-weight:600}
.act-btn:last-child{border-right:0}
.act-btn:hover{background:#fafafa;color:#333}
.act-btn.act-yes.active{background:#1d6b3a;color:#fff}
.act-btn.act-no.active{background:#888;color:#fff}
.action-badge{display:inline-block;padding:3px 10px;border-radius:14px;font-size:11.5px;white-space:nowrap}
.action-ok{background:#e7f5ec;color:#1d6b3a}
.action-pending{background:#eee;color:#888}
.action-multi{background:#e5f0ff;color:#0a4a6e;font-size:11px}
.tabs{display:flex;gap:4px;flex-wrap:wrap;padding:8px 0;margin-top:6px;border-bottom:1px solid #e0e0e0}
.tab-btn{background:#f0f0f0;border:1px solid #ddd;padding:5px 12px;border-radius:14px;cursor:pointer;font-family:inherit;font-size:12.5px;color:#555}
.tab-btn:hover{background:#e8e8e8}
.tab-btn.active{background:#1a4f8a;color:#fff;border-color:#1a4f8a}
.tab-btn .count{background:rgba(255,255,255,0.3);padding:1px 7px;border-radius:10px;margin-left:5px;font-size:11px;color:inherit}
.tab-btn:not(.active) .count{background:#fff;color:#777}
.apply-bar{background:#fff;border:2px solid #1d6b3a;border-radius:6px;padding:14px 18px;margin:16px 0;font-size:13px}
.apply-bar h3{margin:0 0 8px;color:#1d6b3a;font-size:14px}
.apply-bar code{background:#f3f7f4;padding:2px 7px;border-radius:3px;font-size:12px;color:#333}
.apply-bar button.execute{background:#1d6b3a;color:#fff;border:0;padding:8px 18px;border-radius:4px;cursor:pointer;font-family:inherit;font-size:13px;font-weight:600;margin-right:8px}
.apply-bar button.execute:hover{background:#155028}
.detail-row td{font-size:13px;line-height:1.7}
table.dtable{width:100%;border-collapse:collapse;margin:8px 0;font-size:12.5px}
table.dtable th{background:#fff;color:#666;text-align:left;padding:4px 8px;font-weight:600;border-bottom:1px solid #ddd;font-size:11.5px}
table.dtable td{padding:4px 8px;border-bottom:1px solid #f0f0f0;vertical-align:top}
table.dtable code{background:#f5f5f5;padding:1px 5px;border-radius:2px;font-size:11.5px;color:#666}
.cite-status-ok{background:#e7f5ec;color:#1d6b3a}
.cite-status-context-mismatch{background:#fff4d4;color:#7a5a00}
.cite-status-maybe-vault-typo{background:#ffe9d4;color:#8a4500}
.cite-status-missing-from-vault{background:#fde2e2;color:#8a1010}
.cite-status-multi-hit{background:#e5f0ff;color:#0a4a6e}
.cite-status-pending{background:#eee;color:#666}
.pill{padding:2px 8px;border-radius:10px;font-size:11.5px;white-space:nowrap}
#progress{color:#666;font-size:12.5px}
#progress span{margin-right:8px}
label.bib-opt{display:flex;gap:8px;align-items:flex-start;padding:6px 8px;border-radius:4px;cursor:pointer}
label.bib-opt:hover{background:#f3f7f4}
label.bib-opt input{cursor:pointer;margin-top:3px}
.propose-block{border:1px solid;border-radius:6px;padding:10px 14px;margin:10px 0;font-size:13px}
.propose-draft{background:#fffbe6;border-color:#f0d878}
.propose-draft h4{color:#7a5a00;margin:0 0 6px;font-size:13px}
.propose-hint{background:#eef6ff;border-color:#a8c8e8}
.propose-hint h4{color:#1a4f8a;margin:0 0 6px;font-size:13px}
.propose-recovery{background:#f5efff;border-color:#c8b0e8}
.propose-recovery h4{color:#5a1080;margin:0 0 6px;font-size:13px}
.propose-recovery code{background:rgba(90,16,128,0.08);padding:1px 5px;border-radius:3px;font-size:12px}
"""


# ---- helpers -----------------------------------------------------------------

def _esc(s) -> str:
    return html.escape(str(s) if s is not None else "", quote=False)


# verdict status taxonomy (Pass 1):
#   ok                  - 主题契合, 引用准确
#   context-mismatch    - 机械 hit 但主题不契合, 建议改 draft
#   maybe-vault-typo    - 机械 miss 但 vault 可能有, slug 漂了
#   missing-from-vault  - 真 missing
#
# fallback (no verdict yet — agent hasn't run):
#   multi-hit           - 机械多候选, 等 agent 消歧
#   pending             - 机械 single-hit, 等 agent 验证主题

STATUS_LABEL = {
    "ok": "通过",
    "context-mismatch": "主题不契合",
    "maybe-vault-typo": "vault 疑似 slug 漂",
    "missing-from-vault": "vault 缺",
    "multi-hit": "多候选(待 agent)",
    "pending": "待 agent 验证",
}


# ---- merge verdicts ----------------------------------------------------------

def _load_verdicts(verdicts_dir: Path | None) -> dict[str, dict]:
    """Read all batch-*.json and recovery-*.json files in verdicts_dir.

    batch-*.json: citation-agent offline verdicts (Phase 2)
    recovery-*.json: discover-agent online recovery for missing entries (Phase 2.5)

    Merge shape: {key: verdict_dict} where verdict_dict may also include
    an "online_recovery" field if Phase 2.5 ran for that key.
    """
    out: dict[str, dict] = {}
    if not verdicts_dir or not verdicts_dir.is_dir():
        return out

    # Phase 2: offline citation-agent verdicts
    for f in sorted(verdicts_dir.glob("batch-*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            print(f"warn: {f.name} broken JSON ({e.msg} at line {e.lineno})",
                  file=sys.stderr)
            continue
        for v in data.get("verdicts", []):
            out[v["key"]] = v

    # Phase 2.5: online discover-agent recovery (overlays online_recovery field)
    for f in sorted(verdicts_dir.glob("recovery-*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            print(f"warn: {f.name} broken JSON ({e.msg} at line {e.lineno})",
                  file=sys.stderr)
            continue
        key = data.get("key")
        if not key:
            continue
        recovery = data.get("online_recovery")
        if recovery is None:
            continue
        if key in out:
            out[key]["online_recovery"] = recovery
        else:
            # No batch verdict but recovery exists — synthesize a minimal verdict.
            out[key] = {
                "key": key,
                "verdict": "missing-from-vault",
                "confidence": "medium",
                "online_recovery": recovery,
            }
    return out


def _merge_status(entry: dict, verdict: dict | None) -> str:
    """Derive display status from manifest entry + optional verdict."""
    if verdict:
        v = verdict.get("verdict", "")
        if v in STATUS_LABEL:
            return v
    m = entry.get("status", "")
    if m == "single-hit":
        return "pending"
    if m == "multi-hit":
        return "multi-hit"
    if m == "miss":
        return "missing-from-vault"
    return "pending"


def _default_decision(display_status: str) -> str:
    """Default for the 'accept agent suggestion?' radio."""
    if display_status == "ok":
        return "keep"          # ✗ 不改 (引用对)
    if display_status in ("context-mismatch", "missing-from-vault",
                          "maybe-vault-typo"):
        return "modify"        # ✓ 接受 agent 建议
    return "pending"


# ---- bib chooser -------------------------------------------------------------

def _bib_options(entry: dict, verdict: dict | None) -> list[dict]:
    """Choices for which biblio entry feeds references.bib."""
    out = []
    for c in entry.get("candidates", []) or []:
        sub_bits = []
        if c.get("author"):
            sub_bits.append(c["author"])
        if c.get("year"):
            sub_bits.append(str(c["year"]))
        if c.get("year_offset"):
            sub_bits.append(f"年份差 {c['year_offset']}")
        if c.get("edit_distance"):
            sub_bits.append(f"author 模糊 dist={c['edit_distance']}")
        if c.get("issues"):
            sub_bits.append(f"vault 有 {len(c['issues'])} 个 issue")
        out.append({
            "value": f"vault:{c['slug']}",
            "kind": "vault",
            "label": f"[vault] {c.get('title') or '(无标题)'}",
            "sub": " · ".join(sub_bits) + (f" · {c.get('path','')}" if c.get('path') else ""),
        })

    if verdict and verdict.get("verdict") == "missing-from-vault":
        sug = verdict.get("draft_suggestion") or {}
        proposed_slug = sug.get("proposed_slug") or ""
        if proposed_slug:
            out.append({
                "value": f"new:{proposed_slug}",
                "kind": "new",
                "label": f"[新增 vault] {proposed_slug}",
                "sub": "用 /quasi:process-book 补完后 vault 自然就有",
            })

    return out


def _default_bib(options: list[dict], display_status: str, entry: dict,
                 verdict: dict | None) -> str:
    if not options:
        return ""
    # missing → prefer new entry suggestion if available
    if display_status == "missing-from-vault":
        for o in options:
            if o["kind"] == "new":
                return o["value"]
    # if verdict picked a slug, prefer that
    if verdict and verdict.get("picked_slug"):
        for o in options:
            if o["value"] == f"vault:{verdict['picked_slug']}":
                return o["value"]
    # single candidate → that one
    vault_opts = [o for o in options if o["kind"] == "vault"]
    if vault_opts:
        return vault_opts[0]["value"]
    return options[0]["value"]


# ---- row rendering -----------------------------------------------------------

def _status_pill(display_status: str) -> str:
    label = STATUS_LABEL.get(display_status, display_status)
    return (f'<span class="pill cite-status-{display_status}">'
            f'{_esc(label)}</span>')


def _propose_block_draft(verdict: dict | None) -> str:
    if not verdict:
        return ""
    sug = verdict.get("draft_suggestion") or {}
    if not sug:
        return ""
    proposed = _esc(sug.get("proposed") or "")
    why = _esc(sug.get("why") or "")
    parts = ['<div class="propose-block propose-draft">',
             '<h4>✏️ agent 对草稿的建议</h4>']
    if proposed:
        parts.append(f'<div><b>建议改成:</b> {proposed}</div>')
    if why:
        parts.append(f'<div style="margin-top:4px;color:#666"><b>原因:</b> {why}</div>')
    parts.append('</div>')
    return "".join(parts)


def _propose_block_hint(verdict: dict | None) -> str:
    """For maybe-vault-typo: agent hint pointing to existing vault entry."""
    if not verdict:
        return ""
    if verdict.get("verdict") != "maybe-vault-typo":
        return ""
    hint = verdict.get("vault_typo_hint") or {}
    if not hint:
        return ""
    parts = ['<div class="propose-block propose-hint">',
             '<h4>💡 agent 推测:vault 里可能有但 slug 漂了</h4>']
    if hint.get("target_slug"):
        parts.append(f'<div><b>疑似指向:</b> '
                     f'<code>{_esc(hint["target_slug"])}</code></div>')
    if hint.get("why"):
        parts.append(f'<div style="margin-top:4px;color:#666">'
                     f'<b>理由:</b> {_esc(hint["why"])}</div>')
    if hint.get("suggested_action"):
        parts.append(f'<div style="margin-top:4px"><b>建议操作:</b> '
                     f'<code>{_esc(hint["suggested_action"])}</code></div>')
    parts.append('</div>')
    return "".join(parts)


def _propose_block_recovery(verdict: dict | None) -> str:
    """For missing-from-vault: Phase 2.5 discover-agent online recovery result."""
    if not verdict:
        return ""
    recovery = verdict.get("online_recovery") or {}
    if not recovery:
        return ""

    confidence = recovery.get("confidence", "unknown")
    if confidence == "miss":
        searched = ", ".join(recovery.get("searched") or [])
        notes = _esc(recovery.get("notes") or "")
        return ('<div class="propose-block propose-recovery" '
                'style="border-color:#caa">'
                '<h4>🔍 在线 recover — <span style="color:#a00">未找到</span></h4>'
                f'<div style="color:#666">已查 {_esc(searched)}。{notes}</div>'
                '</div>')

    conf_color = {"high": "#1d6b3a", "medium": "#7a5a00", "low": "#8a4500"}.get(
        confidence, "#666")
    title = _esc(recovery.get("title") or "")
    author = _esc(recovery.get("author") or "")
    year = _esc(str(recovery.get("year") or ""))
    publisher = _esc(recovery.get("publisher") or "")
    isbn = _esc(recovery.get("isbn") or "")
    doi = _esc(recovery.get("doi") or "")
    sources = ", ".join(recovery.get("sources") or [])
    cmd = recovery.get("process_book_cmd") or ""

    bits = []
    if title:
        bits.append(f'<div><b>{title}</b></div>')
    meta_bits = []
    if author:
        meta_bits.append(author)
    if year:
        meta_bits.append(year)
    if publisher:
        meta_bits.append(publisher)
    if meta_bits:
        bits.append(f'<div style="color:#666;font-size:12.5px">'
                    f'{_esc(" · ".join(meta_bits))}</div>')
    id_bits = []
    if isbn:
        id_bits.append(f'ISBN {isbn}')
    if doi:
        id_bits.append(f'DOI {doi}')
    if id_bits:
        bits.append(f'<div style="color:#888;font-size:11.5px;margin-top:2px">'
                    f'{_esc(" · ".join(id_bits))}</div>')
    if cmd:
        bits.append(f'<div style="margin-top:6px"><b>建议:</b> '
                    f'<code>{_esc(cmd)}</code></div>')

    return (
        f'<div class="propose-block propose-recovery">'
        f'<h4>🔍 在线 recover '
        f'<span style="color:{conf_color};font-weight:600">'
        f'[{confidence} confidence]</span> '
        f'<span style="color:#888;font-size:11.5px">来源: {_esc(sources)}</span>'
        f'</h4>'
        + "".join(bits) +
        '</div>'
    )


def _candidates_table(entry: dict) -> str:
    cands = entry.get("candidates") or []
    if not cands:
        return ""
    rows = []
    for c in cands:
        kind = c.get("kind", "")
        rows.append(
            f'<tr><td><code>{_esc(c.get("slug",""))}</code></td>'
            f'<td>{_esc(kind)}</td>'
            f'<td>{_esc(c.get("title",""))}</td>'
            f'<td>{_esc(c.get("year","") or "")}</td>'
            f'<td>tier {c.get("tier","?")}</td></tr>')
    return ('<table class="dtable"><thead><tr><th>vault slug</th><th>kind</th>'
            '<th>title</th><th>year</th><th>命中层</th></tr></thead>'
            f'<tbody>{"".join(rows)}</tbody></table>')


def _bib_chooser(entry: dict, verdict: dict | None,
                 display_status: str) -> str:
    options = _bib_options(entry, verdict)
    if not options:
        return ""
    default = _default_bib(options, display_status, entry, verdict)
    rows = []
    for o in options:
        checked = "checked" if o["value"] == default else ""
        kind_color = {"vault": "#5a1080", "new": "#1d6b3a"}.get(o["kind"], "#666")
        rows.append(
            f'<label class="bib-opt">'
            f'<input type="radio" name="bib::{_esc(entry["key"])}" '
            f'value="{_esc(o["value"])}" data-key="{_esc(entry["key"])}" {checked}>'
            f'<span style="flex:1">'
            f'<span style="color:{kind_color};font-weight:600">'
            f'{_esc(o["label"])}</span>'
            f'<div style="color:#888;font-size:11.5px;margin-top:2px">'
            f'{_esc(o["sub"])}</div>'
            f'</span></label>')
    return ('<div class="propose-block" style="background:#f3f7f4;border-color:#b8d4c0">'
            '<h4 style="color:#1d6b3a">📚 参考文献条目(进 .bib)</h4>'
            '<div style="font-size:11.5px;color:#666;margin-bottom:4px">'
            '选一个作为这个 citation key 在 .bib 输出里的来源</div>'
            + "".join(rows) + '</div>')


def _row_html(entry: dict, verdict: dict | None) -> str:
    key = entry["key"]
    display_status = _merge_status(entry, verdict)
    default_dec = _default_decision(display_status)
    mentions = entry.get("mentions") or []
    first_mention = mentions[0] if mentions else {}
    line = first_mention.get("line", "")
    context = (first_mention.get("context") or "").replace("\n", " ")
    if len(context) > 90:
        context = context[:90] + "…"

    authors_raw = entry.get("authors_raw") or entry.get("first_surname", "")
    cite_str = f"{authors_raw}, {entry.get('year','')}"

    # main row
    out = [
        f'<tr class="row" data-key="{_esc(key)}" data-status="{_esc(display_status)}">',
        '<td><span class="caret">▸</span></td>',
        f'<td>{_status_pill(display_status)}</td>',
        f'<td><b>{_esc(key)}</b></td>',
        f'<td style="color:#888;font-size:12.5px">{_esc(cite_str)}</td>',
        f'<td class="cell-ctx"><span style="color:#aaa">L{_esc(line)}</span> '
        f'<span style="color:#666">{_esc(context)}</span></td>',
        '<td>',
        _action_widget(key, display_status, verdict),
        '</td>',
        f'<td class="cell-note"><input type="text" class="user-note" '
        f'data-key="{_esc(key)}" placeholder="…"></td>',
        '</tr>',
    ]

    # detail row
    detail = [
        f'<tr class="detail-row" data-key="{_esc(key)}" style="display:none">',
        '<td colspan="7" style="background:#fafbfd;padding:14px 16px;'
        'border-bottom:2px solid #e0e0e0">',
    ]
    for m in mentions:
        detail.append(
            f'<div style="font-size:12.5px;color:#555;margin:3px 0;'
            f'padding-left:8px;border-left:2px solid #eee">'
            f'<b style="color:#aaa">L{_esc(m.get("line",""))}</b> '
            f'{_esc(m.get("context",""))}</div>')

    detail.append(_candidates_table(entry))
    detail.append(_propose_block_draft(verdict))
    detail.append(_propose_block_hint(verdict))
    detail.append(_propose_block_recovery(verdict))

    if verdict and verdict.get("rationale"):
        detail.append(
            f'<div style="font-size:12.5px;color:#444;margin:6px 0;'
            f'padding:6px 10px;background:#fafafa;border-left:3px solid #c8b078">'
            f'<b>agent 判断理由:</b> {_esc(verdict["rationale"])}</div>')

    detail.append(_bib_chooser(entry, verdict, display_status))

    detail.extend(['</td></tr>'])
    return "\n".join(out + detail)


def _decision_group(key: str, default: str) -> str:
    """Legacy 3-state widget (kept for 全部 view compatibility). Most tabs
    use _action_widget() below to render dimension-specific actions."""
    return (
        f'<div class="dec-grp" data-decision="accept" '
        f'data-key="{_esc(key)}" data-default="{default}">'
        f'<button class="dec-btn ok" data-val="modify" title="接受 agent 建议">✓</button>'
        f'<button class="dec-btn no" data-val="keep" title="拒绝">✗</button>'
        f'<button class="dec-btn pd" data-val="pending" title="待定">?</button>'
        f'</div>')


# ---- per-dimension action widgets -------------------------------------------
#
# Each dimension (display_status) has its own action set with its own
# side-effect target:
#
#   dim                  → action values        side-effect target
#   ok                   → (read-only badge)    none
#   context-mismatch     → apply | keep         draft text (rewrite)
#   maybe-vault-typo     → rename | skip        vault filesystem (mv)
#   missing-from-vault   → todo | skip          vault-todo.md
#   multi-hit            → pick {slug}          bib output (which entry)
#   pending              → (read-only badge)    none (agent not run yet)
#
# JS export groups these into 4 decision buckets:
#   draft_rewrites   (from context-mismatch where action=apply)
#   vault_renames    (from maybe-vault-typo where action=rename)
#   vault_todo       (from missing-from-vault where action=todo)
#   multi_hit_picks  (from multi-hit, picked slug)

ACTION_DIMS = {
    "context-mismatch":   "draft_rewrite",
    "maybe-vault-typo":   "vault_rename",
    "missing-from-vault": "vault_todo",
    "multi-hit":          "multi_pick",
}


def _action_widget(key: str, display_status: str, verdict: dict | None) -> str:
    """Render the per-row decision widget based on dimension."""
    dim = ACTION_DIMS.get(display_status)

    if display_status == "ok":
        return ('<span class="action-badge action-ok" '
                'data-key="{k}" data-dim="ok" data-action="approved">'
                '✓ 通过</span>').format(k=_esc(key))

    if display_status == "pending":
        return ('<span class="action-badge action-pending" '
                'data-key="{k}" data-dim="pending" data-action="pending">'
                '⏳ 等 agent</span>').format(k=_esc(key))

    if display_status == "context-mismatch":
        # default: apply suggested rewrite
        return _two_button_widget(key, dim, "draft_rewrite",
                                  "✓ 应用", "draft_rewrite",
                                  "✗ 保留原引", "skip",
                                  default="draft_rewrite")

    if display_status == "maybe-vault-typo":
        # default: skip (rename is destructive)
        return _two_button_widget(key, dim, "vault_rename",
                                  "✓ 执行 rename", "vault_rename",
                                  "✗ 忽略", "skip",
                                  default="skip")

    if display_status == "missing-from-vault":
        # default: add to todo if Phase 2.5 recovery succeeded (high confidence)
        recovery = (verdict or {}).get("online_recovery") or {}
        rec_conf = recovery.get("confidence", "")
        default = "vault_todo" if rec_conf in ("high", "medium") else "skip"
        return _two_button_widget(key, dim, "vault_todo",
                                  "✓ 加待跑", "vault_todo",
                                  "✗ 忽略", "skip",
                                  default=default)

    if display_status == "multi-hit":
        # render a hint pointing to the bib chooser in detail row
        return ('<span class="action-badge action-multi" '
                'data-key="{k}" data-dim="multi-hit" data-action="pick">'
                '→ 展开,在 "📚 参考文献条目" 里选'
                '</span>').format(k=_esc(key))

    # Fallback (shouldn't happen)
    return _decision_group(key, "pending")


def _two_button_widget(key: str, dim: str, primary_val: str,
                       yes_label: str, yes_val: str,
                       no_label: str, no_val: str,
                       default: str) -> str:
    return (
        f'<div class="action-grp" data-key="{_esc(key)}" '
        f'data-dim="{_esc(dim or "")}" data-default="{_esc(default)}">'
        f'<button class="act-btn act-yes" data-val="{_esc(yes_val)}">'
        f'{_esc(yes_label)}</button>'
        f'<button class="act-btn act-no" data-val="{_esc(no_val)}">'
        f'{_esc(no_label)}</button>'
        f'</div>'
    )


# ---- top banner --------------------------------------------------------------

def _banner_missing(entries: list[dict], verdicts_by_key: dict) -> str:
    miss = []
    for e in entries:
        v = verdicts_by_key.get(e["key"])
        ds = _merge_status(e, v)
        if ds == "missing-from-vault":
            miss.append((e, v))
    if not miss:
        return ""

    items = []
    for e, v in miss:
        cmd_hint = ""
        if v:
            sug = v.get("draft_suggestion") or {}
            if sug.get("hint_command"):
                cmd_hint = f' &mdash; 建议: <code>{_esc(sug["hint_command"])}</code>'
        items.append(
            f'<li><code>{_esc(e["key"])}</code> '
            f'({_esc(e.get("authors_raw",""))}, {_esc(e.get("year",""))})'
            f'{cmd_hint}</li>')

    return (f'<div class="banner">'
            f'<h3>⛔ {len(miss)} 条引用 vault 里没找到,补完再重跑 wrap-up</h3>'
            f'<ul>{"".join(items)}</ul>'
            f'</div>')


def _banner_typo(entries: list[dict], verdicts_by_key: dict) -> str:
    typo = []
    for e in entries:
        v = verdicts_by_key.get(e["key"])
        if v and v.get("verdict") == "maybe-vault-typo":
            typo.append((e, v))
    if not typo:
        return ""
    items = []
    for e, v in typo:
        hint = v.get("vault_typo_hint") or {}
        target = hint.get("target_slug", "")
        action = hint.get("suggested_action", "")
        items.append(
            f'<li><code>{_esc(e["key"])}</code> → vault 里疑似 '
            f'<code>{_esc(target)}</code>'
            + (f' &mdash; <code>{_esc(action)}</code>' if action else '')
            + '</li>')
    return (f'<div class="banner banner-warn">'
            f'<h3>⚠ {len(typo)} 条引用 vault 可能有但 slug 漂了</h3>'
            f'<ul>{"".join(items)}</ul></div>')


# ---- main render -------------------------------------------------------------

def render_html(manifest: dict, verdicts_dir: Path | None,
                source_label: str) -> str:
    verdicts_by_key = _load_verdicts(verdicts_dir)
    entries = manifest["entries"]

    # bucket by display status
    buckets: dict[str, list[tuple[dict, dict | None]]] = {}
    for e in entries:
        v = verdicts_by_key.get(e["key"])
        ds = _merge_status(e, v)
        buckets.setdefault(ds, []).append((e, v))

    # group order: surface non-ok first
    group_order = ["missing-from-vault", "maybe-vault-typo", "context-mismatch",
                   "multi-hit", "pending", "ok"]

    rows = []
    for status in group_order:
        for e, v in buckets.get(status, []):
            rows.append(_row_html(e, v))

    banner_html = (_banner_missing(entries, verdicts_by_key)
                   + _banner_typo(entries, verdicts_by_key))

    # tab nav: 6 tabs with counts
    tabs_html = _tabs_html(buckets, len(entries))

    return _HEAD_TMPL.format(
        css=_CSS,
        label=_esc(source_label),
        n_done=len(verdicts_by_key),
        total=len(entries),
        banner=banner_html,
        tabs=tabs_html,
    ) + "\n".join(rows) + _TAIL_TMPL


def _tabs_html(buckets: dict, total: int) -> str:
    """Per-dimension tab nav with counters."""
    n_ok = len(buckets.get("ok", []))
    n_multi = len(buckets.get("multi-hit", []))
    n_ctx = len(buckets.get("context-mismatch", []))
    n_typo = len(buckets.get("maybe-vault-typo", []))
    n_miss = len(buckets.get("missing-from-vault", []))
    n_pend = len(buckets.get("pending", []))
    return (
        '<div class="tabs">'
        f'<button class="tab-btn active" data-tab="all" onclick="applyTab(\'all\')">'
        f'全部 <span class="count">{total}</span></button>'
        f'<button class="tab-btn" data-tab="multi-hit" onclick="applyTab(\'multi-hit\')">'
        f'挑候选 <span class="count">{n_multi}</span></button>'
        f'<button class="tab-btn" data-tab="context-mismatch" onclick="applyTab(\'context-mismatch\')">'
        f'修 draft <span class="count">{n_ctx}</span></button>'
        f'<button class="tab-btn" data-tab="maybe-vault-typo" onclick="applyTab(\'maybe-vault-typo\')">'
        f'修 vault <span class="count">{n_typo}</span></button>'
        f'<button class="tab-btn" data-tab="missing-from-vault" onclick="applyTab(\'missing-from-vault\')">'
        f'补 vault <span class="count">{n_miss}</span></button>'
        f'<button class="tab-btn" data-tab="pending" onclick="applyTab(\'pending\')">'
        f'等 agent <span class="count">{n_pend}</span></button>'
        f'<button class="tab-btn" data-tab="ok" onclick="applyTab(\'ok\')">'
        f'✓ 通过 <span class="count">{n_ok}</span></button>'
        '</div>'
    )


_HEAD_TMPL = """<!doctype html><html lang="zh"><head><meta charset="utf-8">
<title>引用审稿 · {label}</title>
<style>{css}</style></head><body>
<div class="toolbar">
  <span class="title">引用审稿 · {label} · {n_done}/{total} verdict</span>
  <span id="progress"></span>
  <button class="export" onclick="exportDecisions()">⚙ 导出 decisions.json</button>
</div>
<div class="wrap">
{banner}
{tabs}
<div class="apply-bar" id="apply-bar">
  <h3>⚙ 全部审完后:导出 decisions + 跑 apply</h3>
  <div>review 各 tab 后,点 <button class="execute" onclick="exportDecisions()">⚙ 导出 decisions.json</button> 拿到分组好的 4 类决策。</div>
  <div style="margin-top:8px;color:#666;font-size:12px">然后跑:</div>
  <div style="margin-top:4px"><code>quasi-helpers citation apply decisions.json --draft &lt;draft.md&gt; --ct-dir &lt;processing/citation/{{stem}}/&gt;</code></div>
  <div style="margin-top:6px;color:#666;font-size:12px">apply 命令会按 4 个 group 派生产物:</div>
  <ul style="margin:4px 0 0 22px;color:#444;font-size:12px;line-height:1.7">
    <li><code>draft_rewrites</code> → 改 draft 文本 (context-mismatch 已勾"应用")</li>
    <li><code>vault_renames</code> → 输出 <code>vault-renames.sh</code> (用户 review 后 bash)</li>
    <li><code>vault_todo</code> → 输出 <code>vault-todo.md</code> (待跑 process-book 清单)</li>
    <li><code>multi_hit_picks</code> + 上述 → 重出 <code>references.bib</code></li>
  </ul>
</div>
<table class="main">
<thead><tr><th style="width:18px"></th><th>状态</th><th>引用条目</th><th>(作者, 年份)</th><th>出处</th><th style="white-space:nowrap">决策</th><th>备注</th></tr></thead>
<tbody>
"""

_TAIL_TMPL = """</tbody></table>
</div>

<script>
function initDefaults() {
  // Legacy 3-state widget (for any fallback rows)
  document.querySelectorAll('.dec-grp').forEach(g => {
    const d = g.dataset.default;
    const b = g.querySelector(`[data-val="${d}"]`);
    if (b) b.classList.add('active');
  });
  // Per-dimension 2-button widgets
  document.querySelectorAll('.action-grp').forEach(g => {
    const d = g.dataset.default;
    const b = g.querySelector(`[data-val="${d}"]`);
    if (b) b.classList.add('active');
  });
  updateProgress();
}
function setAction(btn) {
  const grp = btn.closest('.action-grp, .dec-grp');
  if (!grp) return;
  const sel = grp.classList.contains('action-grp') ? '.act-btn' : '.dec-btn';
  grp.querySelectorAll(sel).forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  updateProgress();
}
function toggleDetail(row) {
  const k = row.dataset.key;
  const det = document.querySelector(`.detail-row[data-key="${CSS.escape(k)}"]`);
  if (!det) return;
  const open = det.style.display !== 'none';
  det.style.display = open ? 'none' : '';
  row.querySelector('.caret').textContent = open ? '▸' : '▾';
}
function updateProgress() {
  // Count by dimension's chosen action
  let counts = {draft_rewrite:0, vault_rename:0, vault_todo:0, multi_pick:0, skip:0};
  document.querySelectorAll('.action-grp').forEach(g => {
    const a = g.querySelector('.act-btn.active');
    if (!a) return;
    const v = a.dataset.val;
    if (v in counts) counts[v]++;
  });
  document.getElementById('progress').innerHTML =
    `<span>改 draft:${counts.draft_rewrite}</span>` +
    `<span>vault rename:${counts.vault_rename}</span>` +
    `<span>vault todo:${counts.vault_todo}</span>` +
    `<span>跳过:${counts.skip}</span>`;
}
function readNote(k) {
  const n = document.querySelector(`.user-note[data-key="${CSS.escape(k)}"]`);
  return n ? n.value.trim() : "";
}
function readBibPick(k) {
  const b = document.querySelector(`input[name="bib::${CSS.escape(k)}"]:checked`);
  return b ? b.value : null;
}
function exportDecisions() {
  // Group decisions into 4 buckets by dimension
  const out = {
    version: 1,
    generated_at: new Date().toISOString(),
    draft_rewrites: [],
    vault_renames: [],
    vault_todo: [],
    multi_hit_picks: [],
    skipped: [],
    by_key: {},  // backward-compat flat view
  };
  document.querySelectorAll('.row').forEach(r => {
    const k = r.dataset.key;
    const status = r.dataset.status;
    const dim = ACTION_DIM_MAP[status] || null;
    const grp = r.querySelector('.action-grp');
    const act = grp ? (grp.querySelector('.act-btn.active') || {}).dataset?.val : null;
    const bib = readBibPick(k);
    const note = readNote(k);

    out.by_key[k] = { status, dim, action: act, bib_source: bib, note };

    if (status === 'context-mismatch' && act === 'draft_rewrite') {
      out.draft_rewrites.push({ key: k, bib_source: bib, note });
    } else if (status === 'maybe-vault-typo' && act === 'vault_rename') {
      out.vault_renames.push({ key: k, note });
    } else if (status === 'missing-from-vault' && act === 'vault_todo') {
      out.vault_todo.push({ key: k, note });
    } else if (status === 'multi-hit' && bib) {
      out.multi_hit_picks.push({ key: k, picked_slug: bib.replace(/^vault:/,''), note });
    } else if (act === 'skip' || status === 'pending') {
      out.skipped.push({ key: k, status, note });
    }
  });
  const blob = new Blob([JSON.stringify(out, null, 2)], {type:'application/json'});
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob); a.download = 'decisions.json'; a.click();
}
const ACTION_DIM_MAP = {
  'context-mismatch':   'draft_rewrite',
  'maybe-vault-typo':   'vault_rename',
  'missing-from-vault': 'vault_todo',
  'multi-hit':          'multi_pick',
};
function applyTab(t) {
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  const tabBtn = document.querySelector(`.tab-btn[data-tab="${t}"]`);
  if (tabBtn) tabBtn.classList.add('active');
  document.querySelectorAll('.row').forEach(r => {
    const s = r.dataset.status;
    const show = (t === 'all') || (s === t);
    r.style.display = show ? '' : 'none';
    const det = document.querySelector(`.detail-row[data-key="${CSS.escape(r.dataset.key)}"]`);
    if (det && !show) {
      det.style.display = 'none';
      const c = r.querySelector('.caret');
      if (c) c.textContent = '▸';
    }
  });
}
window.addEventListener('load', () => {
  initDefaults();
  document.querySelectorAll('.dec-btn, .act-btn').forEach(b =>
    b.addEventListener('click', e => { e.stopPropagation(); setAction(b); }));
  document.querySelectorAll('.row').forEach(r => r.addEventListener('click', e => {
    if (e.target.closest('.dec-btn') || e.target.closest('.act-btn') ||
        e.target.closest('.user-note') || e.target.closest('label')) return;
    toggleDetail(r);
  }));
  document.querySelectorAll('.user-note').forEach(i =>
    i.addEventListener('click', e => e.stopPropagation()));
});
</script>
</body></html>
"""


# ---- entrypoint --------------------------------------------------------------

def main(argv: list[str]) -> int:
    import argparse
    ap = argparse.ArgumentParser(
        description="Render citation manifest (+ verdicts) into review HTML.")
    ap.add_argument("manifest", help="Output of resolve.py")
    ap.add_argument("--verdicts", help="Directory of batch-*.json verdicts (optional)")
    ap.add_argument("-o", "--output", required=True)
    ap.add_argument("--source-label", default="draft")
    args = ap.parse_args(argv)

    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    verdicts_dir = Path(args.verdicts) if args.verdicts else None
    html_str = render_html(manifest, verdicts_dir, args.source_label)
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html_str, encoding="utf-8")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
