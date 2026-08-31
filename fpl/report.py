"""Rendering the scout's findings as a self-contained page.

The output is one HTML file with no external dependencies beyond web fonts:
open it in a browser, or hand it to anyone, and it works. The design borrows
from the things an FPL manager already reads - a team sheet, a tactics board,
a fixture ticker - rather than inventing new furniture for familiar ideas.
"""

from __future__ import annotations

import html

from . import rules
from .analysis.transfers import DIFFERENTIAL_OWNERSHIP
from .scout import ScoutReport

CSS = """
:root{
  --ink:#12211F; --ink-2:#1B2E2B; --ink-3:#26403C;
  --chalk:#EDF1EE; --chalk-2:#FFFFFF; --chalk-3:#DDE5E0;
  --bg:var(--chalk); --surface:var(--chalk-2); --surface-2:#E3EAE5;
  --text:#12211F; --text-dim:#4E635E; --text-faint:#7B8F89;
  --line:#CBD6D0;
  --accent:#B4700A; --accent-soft:#F5E4C4; --accent-ink:#FFFFFF;
  --good:#1F7A50; --good-soft:#D6EBDF;
  --warn:#9A5B10; --warn-soft:#F7E6CC;
  --bad:#A63A28; --bad-soft:#F6DAD4;
  --shadow:0 1px 2px rgba(18,33,31,.08), 0 8px 24px rgba(18,33,31,.06);
  --radius:10px;
  --display:"Anton", "Haettenschweiler", Impact, sans-serif;
  --body:"Archivo", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  --mono:"IBM Plex Mono", ui-monospace, "SFMono-Regular", Menlo, monospace;
}
@media (prefers-color-scheme: dark){
  :root:not([data-theme="light"]){
    --bg:#0E1917; --surface:#162624; --surface-2:#1D322E;
    --text:#E6EDE9; --text-dim:#9DB2AC; --text-faint:#728884;
    --line:#2A423D;
    --accent:#E8A33D; --accent-soft:#3A2E17; --accent-ink:#12211F;
    --good:#4FBE87; --good-soft:#163324;
    --warn:#E0A052; --warn-soft:#33260F;
    --bad:#E4705B; --bad-soft:#371914;
    --shadow:0 1px 2px rgba(0,0,0,.4), 0 10px 30px rgba(0,0,0,.3);
  }
}
:root[data-theme="dark"]{
  --bg:#0E1917; --surface:#162624; --surface-2:#1D322E;
  --text:#E6EDE9; --text-dim:#9DB2AC; --text-faint:#728884;
  --line:#2A423D;
  --accent:#E8A33D; --accent-soft:#3A2E17; --accent-ink:#12211F;
  --good:#4FBE87; --good-soft:#163324;
  --warn:#E0A052; --warn-soft:#33260F;
  --bad:#E4705B; --bad-soft:#371914;
  --shadow:0 1px 2px rgba(0,0,0,.4), 0 10px 30px rgba(0,0,0,.3);
}

*{box-sizing:border-box}
body{
  margin:0; background:var(--bg); color:var(--text);
  font-family:var(--body); font-size:15px; line-height:1.55;
  -webkit-font-smoothing:antialiased;
}
h1,h2,h3{text-wrap:balance; margin:0}
a{color:var(--accent)}

.wrap{max-width:1180px; margin:0 auto; padding:0 20px 80px}

/* --- team sheet strip -------------------------------------------------- */
.sheet{
  position:sticky; top:0; z-index:20;
  background:var(--ink); color:var(--chalk);
  border-bottom:3px solid var(--accent);
}
:root[data-theme="dark"] .sheet, :root:not([data-theme="light"]) .sheet{background:#0A1413}
.sheet-in{
  max-width:1180px; margin:0 auto; padding:14px 20px;
  display:flex; flex-wrap:wrap; align-items:center; gap:12px 28px;
}
.crest{
  font-family:var(--display); font-size:26px; letter-spacing:.04em;
  text-transform:uppercase; line-height:1; color:var(--chalk);
}
.crest span{color:var(--accent)}
.sheet-meta{font-family:var(--mono); font-size:11.5px; color:#9DB2AC; letter-spacing:.03em}
.stats{display:flex; gap:22px; margin-left:auto; flex-wrap:wrap}
.stat{text-align:right}
.stat b{
  display:block; font-family:var(--display); font-size:21px; line-height:1;
  color:var(--chalk); font-variant-numeric:tabular-nums; letter-spacing:.02em;
}
.stat i{
  font-style:normal; font-family:var(--mono); font-size:10px;
  text-transform:uppercase; letter-spacing:.09em; color:#7B8F89;
}

/* --- tabs -------------------------------------------------------------- */
.tabs{
  display:flex; gap:2px; overflow-x:auto; margin:0 0 26px;
  border-bottom:1px solid var(--line); padding-top:22px;
}
.tab{
  appearance:none; border:0; background:none; cursor:pointer;
  font-family:var(--mono); font-size:11.5px; letter-spacing:.1em;
  text-transform:uppercase; color:var(--text-faint);
  padding:9px 15px; border-bottom:2px solid transparent; white-space:nowrap;
}
.tab:hover{color:var(--text)}
.tab[aria-selected="true"]{color:var(--text); border-bottom-color:var(--accent)}
.tab:focus-visible{outline:2px solid var(--accent); outline-offset:-2px}

/* --- generic blocks ---------------------------------------------------- */
.eyebrow{
  font-family:var(--mono); font-size:10.5px; letter-spacing:.14em;
  text-transform:uppercase; color:var(--text-faint); margin:0 0 6px;
}
h2.sec{
  font-family:var(--display); font-size:clamp(24px,3.2vw,34px);
  letter-spacing:.01em; text-transform:uppercase; margin:0 0 4px;
}
.sec-note{color:var(--text-dim); max-width:66ch; margin:0 0 22px}
.block{margin:0 0 44px}
.card{
  background:var(--surface); border:1px solid var(--line);
  border-radius:var(--radius); padding:18px; box-shadow:var(--shadow);
}
.grid{display:grid; gap:14px}
.g3{grid-template-columns:repeat(auto-fit,minmax(280px,1fr))}
.g2{grid-template-columns:repeat(auto-fit,minmax(320px,1fr))}

/* --- pitch ------------------------------------------------------------- */
.pitch{
  background:
    linear-gradient(180deg, rgba(255,255,255,.05) 0 50%, rgba(0,0,0,.05) 50% 100%),
    repeating-linear-gradient(180deg,#1E3A32 0 46px,#224037 46px 92px);
  border:2px solid rgba(255,255,255,.18); border-radius:var(--radius);
  padding:22px 14px; display:grid; gap:16px; position:relative; overflow:hidden;
}
.pitch::before{
  content:""; position:absolute; left:50%; top:50%;
  width:96px; height:96px; margin:-48px 0 0 -48px;
  border:2px solid rgba(255,255,255,.16); border-radius:50%;
}
.pitch-row{display:flex; justify-content:center; gap:10px; flex-wrap:wrap; position:relative}
.chip-player{
  width:124px; background:rgba(9,20,18,.82); color:#E6EDE9;
  border:1px solid rgba(255,255,255,.16); border-radius:8px;
  padding:7px 6px; text-align:center; backdrop-filter:blur(2px);
}
.chip-player .nm{
  font-size:12px; font-weight:600; line-height:1.2;
  white-space:nowrap; overflow:hidden; text-overflow:ellipsis;
}
.chip-player .pr{
  font-family:var(--mono); font-size:10px; color:#9DB2AC;
  font-variant-numeric:tabular-nums;
}
.chip-player .xp{
  font-family:var(--display); font-size:17px; line-height:1.1; color:#E8A33D;
  font-variant-numeric:tabular-nums;
}
.chip-player.cap{border-color:#E8A33D; box-shadow:0 0 0 1px #E8A33D inset}
.armband{
  display:inline-block; background:#E8A33D; color:#12211F;
  font-family:var(--mono); font-size:9px; font-weight:700;
  padding:0 4px; border-radius:3px; letter-spacing:.05em;
}
.dot{width:7px; height:7px; border-radius:50%; display:inline-block}
.dot.ok{background:#4FBE87} .dot.warn{background:#E0A052} .dot.bad{background:#E4705B}

.bench{margin-top:14px; padding-top:14px; border-top:1px dashed var(--line)}
.bench-label{
  font-family:var(--mono); font-size:10px; letter-spacing:.11em; text-transform:uppercase;
  color:var(--text-faint); margin:0 0 9px;
}
.bench-row{display:flex; gap:10px; flex-wrap:wrap}
.bench-row .chip-player{position:relative}
.bench-row .chip-player::after{
  content:attr(data-order); position:absolute; top:-7px; left:-7px;
  width:18px; height:18px; border-radius:50%; background:var(--ink); color:var(--chalk);
  font-family:var(--mono); font-size:10px; line-height:18px; text-align:center;
}
.bench .chip-player{background:var(--surface-2); color:var(--text); border-color:var(--line)}
.bench .chip-player .pr{color:var(--text-faint)}
.bench .chip-player .xp{color:var(--accent)}

/* --- tiered option cards ---------------------------------------------- */
.opt{border-left:4px solid var(--line); background:var(--surface);
  border-radius:var(--radius); border-top:1px solid var(--line);
  border-right:1px solid var(--line); border-bottom:1px solid var(--line);
  padding:16px 18px; box-shadow:var(--shadow); display:flex; flex-direction:column; gap:9px}
.opt.safe{border-left-color:var(--good)}
.opt.balanced{border-left-color:var(--accent)}
.opt.risky{border-left-color:var(--bad)}
.opt h3{font-family:var(--display); font-size:20px; letter-spacing:.01em; text-transform:uppercase}
.tier-tag{
  font-family:var(--mono); font-size:10px; letter-spacing:.11em; text-transform:uppercase;
  padding:2px 8px; border-radius:20px; align-self:flex-start;
}
.tier-tag.safe{background:var(--good-soft); color:var(--good)}
.tier-tag.balanced{background:var(--accent-soft); color:var(--accent)}
.tier-tag.risky{background:var(--bad-soft); color:var(--bad)}
.why{color:var(--text-dim); font-size:14px; margin:0}
.metrics{display:flex; gap:16px; flex-wrap:wrap; font-family:var(--mono); font-size:11.5px;
  color:var(--text-dim); font-variant-numeric:tabular-nums}
.metrics b{color:var(--text); font-weight:600}

/* --- tables ------------------------------------------------------------ */
.scroll{overflow-x:auto; border:1px solid var(--line); border-radius:var(--radius); background:var(--surface)}
table{border-collapse:collapse; width:100%; font-size:13.5px}
th,td{padding:9px 12px; text-align:left; border-bottom:1px solid var(--line); white-space:nowrap}
th{
  font-family:var(--mono); font-size:10px; letter-spacing:.1em; text-transform:uppercase;
  color:var(--text-faint); background:var(--surface-2); position:sticky; top:0;
}
td.num{font-family:var(--mono); font-variant-numeric:tabular-nums; text-align:right}
tbody tr:last-child td{border-bottom:0}
tbody tr:hover{background:var(--surface-2)}

.pill{
  font-family:var(--mono); font-size:10px; padding:2px 7px; border-radius:20px;
  letter-spacing:.05em; text-transform:uppercase;
}
.pill.keep{background:var(--good-soft); color:var(--good)}
.pill.hold{background:var(--surface-2); color:var(--text-dim)}
.pill.watch{background:var(--warn-soft); color:var(--warn)}
.pill.sell{background:var(--bad-soft); color:var(--bad)}
.pill.safe{background:var(--good-soft); color:var(--good)}
.pill.balanced{background:var(--accent-soft); color:var(--accent)}
.pill.risky{background:var(--bad-soft); color:var(--bad)}

/* --- fixture ticker ---------------------------------------------------- */
.tick td, .tick th{padding:5px 7px; text-align:center; font-size:12px}
.tick td:first-child, .tick th:first-child{
  text-align:left; font-family:var(--mono); font-weight:600; position:sticky; left:0;
  background:var(--surface); z-index:1;
}
.fd{display:block; border-radius:4px; padding:3px 4px; font-family:var(--mono); font-size:10.5px}
.fd1{background:#1F7A50; color:#fff} .fd2{background:#5AA06E; color:#fff}
.fd3{background:#B8B0A0; color:#1A1A1A} .fd4{background:#C4623F; color:#fff}
.fd5{background:#9E2B20; color:#fff}
.fd-none{background:var(--surface-2); color:var(--text-faint)}
.fd-dgw{outline:2px solid var(--accent); outline-offset:-2px}

/* --- chips ------------------------------------------------------------- */
.chip-card{display:flex; gap:14px; align-items:flex-start; padding:15px 16px;
  border:1px solid var(--line); border-radius:var(--radius); background:var(--surface)}
.chip-card.spent{opacity:.5}
.chip-badge{
  font-family:var(--display); font-size:12px; letter-spacing:.06em; text-transform:uppercase;
  background:var(--ink); color:var(--chalk); padding:7px 9px; border-radius:6px;
  min-width:72px; text-align:center; line-height:1.2;
}
:root[data-theme="dark"] .chip-badge, :root:not([data-theme="light"]) .chip-badge{
  background:var(--surface-2); color:var(--text);
}
.urg{font-family:var(--mono); font-size:10px; letter-spacing:.09em; text-transform:uppercase}
.urg.Expiring{color:var(--bad)} .urg.Use{color:var(--warn)}
.urg.Plan{color:var(--accent)} .urg.Hold{color:var(--text-faint)}

/* --- strategy ---------------------------------------------------------- */
.horizon{display:grid; gap:12px; padding:20px; border-radius:var(--radius);
  background:var(--surface); border:1px solid var(--line); box-shadow:var(--shadow)}
.horizon ul{margin:0; padding-left:19px; display:grid; gap:9px}
.horizon li{color:var(--text-dim)}
.horizon li::marker{color:var(--accent)}

.flag{font-size:12.5px; color:var(--warn); display:flex; gap:7px; align-items:baseline}
.flag.bad{color:var(--bad)}
.note{
  background:var(--accent-soft); border-left:3px solid var(--accent);
  padding:13px 16px; border-radius:0 var(--radius) var(--radius) 0;
  font-size:13.5px; color:var(--text);
}
footer{margin-top:50px; padding-top:20px; border-top:1px solid var(--line);
  font-family:var(--mono); font-size:11px; color:var(--text-faint); line-height:1.7}
@media (prefers-reduced-motion:reduce){*{animation:none!important; transition:none!important}}
@media (max-width:640px){
  .stats{width:100%; margin-left:0; justify-content:space-between; gap:12px}
  .chip-player{width:100px}
}
"""


def esc(value) -> str:
    return html.escape(str(value), quote=True)


def _tier_class(tier: str) -> str:
    return tier.lower().replace(" ", "-")


def _status_dot(review) -> str:
    player = review.player
    if not player.available:
        return '<span class="dot bad" title="Unavailable"></span>'
    if player.status == "d" or review.projection.expected_minutes < 45:
        return '<span class="dot warn" title="Doubt over minutes"></span>'
    return '<span class="dot ok" title="Expected to start"></span>'


def _player_chip(review, captain_id: int | None, gameweek: int) -> str:
    player = review.player
    is_captain = captain_id is not None and player.id == captain_id
    next_gw = review.projection.per_gameweek.get(gameweek, 0.0)
    armband = ' <span class="armband">C</span>' if is_captain else ""
    return f"""<div class="chip-player{' cap' if is_captain else ''}">
  <div class="nm">{_status_dot(review)} {esc(player.name)}{armband}</div>
  <div class="pr">{esc(player.position_name)} · £{player.price:.1f}m</div>
  <div class="xp">{next_gw:.1f}</div>
</div>"""


def _pitch(review, gameweek: int) -> str:
    captain = max(
        (r for r in review.best_xi if r.player.position != 1),
        key=lambda r: r.projection.per_match,
        default=None,
    )
    captain_id = captain.player.id if captain else None

    rows = []
    for position in (1, 2, 3, 4):
        line = [r for r in review.best_xi if r.player.position == position]
        if line:
            chips = "\n".join(_player_chip(r, captain_id, gameweek) for r in line)
            rows.append(f'<div class="pitch-row">{chips}</div>')

    bench_chips = []
    for order, item in enumerate(review.bench_order, start=1):
        chip = _player_chip(item, None, gameweek)
        bench_chips.append(chip.replace('<div class="chip-player', f'<div data-order="{order}" class="chip-player', 1))
    bench = "\n".join(bench_chips)
    return f"""<div class="pitch">{''.join(rows)}</div>
<div class="bench">
  <p class="bench-label">Bench — in the order autosubs will use them</p>
  <div class="bench-row">{bench}</div>
</div>"""


def _captain_cards(review) -> str:
    if not review.captains:
        return '<p class="why">No captaincy options could be projected.</p>'
    cards = []
    for option in review.captains:
        tier = _tier_class(option.tier)
        cards.append(f"""<div class="opt {tier}">
  <span class="tier-tag {tier}">{esc(option.tier)}</span>
  <h3>{esc(option.player_name)}</h3>
  <div class="metrics">
    <span>Projected <b>{option.projection:.1f}</b>/match</span>
    <span>Owned <b>{option.ownership:.1f}%</b></span>
    <span>{esc(option.team)}</span>
  </div>
  <p class="why">{esc(option.rationale)}</p>
  <div class="metrics"><span>Next: <b>{esc(option.fixtures)}</b></span></div>
</div>""")
    return f'<div class="grid g3">{"".join(cards)}</div>'


def _squad_table(review, gameweek: int, state) -> str:
    rows = []
    for item in sorted(review.reviews, key=lambda r: (r.player.position, -r.score)):
        player = item.player
        projection = item.projection
        flags = "<br>".join(esc(f) for f in item.flags) or '<span style="color:var(--text-faint)">—</span>'
        defcon = (
            f"{projection.defcon_chance*100:.0f}%"
            if player.position in rules.DEFCON_ELIGIBLE else "—"
        )
        rows.append(f"""<tr>
  <td>{_status_dot(item)} <b>{esc(player.name)}</b></td>
  <td>{esc(player.position_name)}</td>
  <td>{esc(state.team(player.team_id).short_name)}</td>
  <td class="num">£{player.price:.1f}</td>
  <td class="num">{projection.per_gameweek.get(gameweek, 0.0):.1f}</td>
  <td class="num">{projection.total:.1f}</td>
  <td class="num">{player.xgi90:.2f}</td>
  <td class="num">{defcon}</td>
  <td class="num">{player.selected_by:.1f}%</td>
  <td><span class="pill {item.verdict.lower()}">{esc(item.verdict)}</span></td>
  <td style="white-space:normal;min-width:220px;font-size:12.5px;color:var(--text-dim)">{flags}</td>
</tr>""")
    return f"""<div class="scroll"><table>
<thead><tr>
  <th>Player</th><th>Pos</th><th>Club</th><th>Price</th>
  <th>GW{gameweek}</th><th>Horizon</th><th>xGI/90</th><th>DefCon</th>
  <th>Owned</th><th>Verdict</th><th>Notes</th>
</tr></thead>
<tbody>{''.join(rows)}</tbody></table></div>"""


def _transfer_plans(report: ScoutReport) -> str:
    if not report.plans:
        return """<div class="note">No transfer improves the squad by enough to be worth
        making. That is a real result, not a gap: hold the transfer, let it roll, and take
        two moves next week instead.</div>"""

    cards = []
    for plan in report.plans:
        tier = _tier_class(plan.tier)
        moves = []
        for move in plan.moves:
            reasons = "".join(f"<li>{esc(r)}</li>" for r in move.reasons[:5])
            moves.append(f"""<div style="padding:11px 0;border-top:1px solid var(--line)">
  <div style="font-weight:600;margin-bottom:5px">
    {esc(move.out_player.name)} → {esc(move.in_player.name)}
  </div>
  <div class="metrics">
    <span>Gain <b>{move.gain:+.1f}</b></span>
    <span>£{move.in_player.price:.1f}m in</span>
    <span>{'Frees' if move.cost_change < 0 else 'Costs'} <b>£{abs(move.cost_change):.1f}m</b></span>
    <span>Owned <b>{move.in_player.selected_by:.1f}%</b></span>
  </div>
  <ul style="margin:7px 0 0;padding-left:18px;font-size:12.5px;color:var(--text-dim)">{reasons}</ul>
</div>""")

        hit_note = (
            f'<span style="color:var(--bad)">−{plan.hit_cost} pts hit</span>'
            if plan.hits else '<span style="color:var(--good)">No hit</span>'
        )
        cards.append(f"""<div class="opt {tier}">
  <span class="tier-tag {tier}">{esc(plan.tier)}</span>
  <h3>{len(plan.moves)} transfer{'s' if len(plan.moves) != 1 else ''}</h3>
  <div class="metrics">
    <span>Net <b>{plan.net_gain:+.1f}</b> pts</span>
    {hit_note}
    <span>Bank after <b>£{plan.bank_after:.1f}m</b></span>
  </div>
  <p class="why">{esc(plan.explanation)}</p>
  {''.join(moves)}
</div>""")
    return f'<div class="grid g3">{"".join(cards)}</div>'


def _chips(report: ScoutReport) -> str:
    if not report.chips:
        return '<p class="why">Load a team ID to see which chips you still hold.</p>'
    cards = []
    for chip in report.chips:
        target = f"GW{chip.recommended_gw}" if chip.recommended_gw else "No target yet"
        state = "" if chip.available else " spent"
        urgency_class = chip.urgency.split()[0]
        cards.append(f"""<div class="chip-card{state}">
  <div class="chip-badge">{esc(chip.label)}</div>
  <div style="flex:1">
    <div class="metrics" style="margin-bottom:5px">
      <span class="urg {esc(urgency_class)}">{esc(chip.urgency)}</span>
      <span>Target <b>{esc(target)}</b></span>
      <span>Confidence <b>{esc(chip.confidence)}</b></span>
      <span>{'Available' if chip.available else 'Already played'}</span>
    </div>
    <p class="why" style="margin:0">{esc(chip.rationale)}</p>
  </div>
</div>""")
    return f'<div class="grid" style="gap:11px">{"".join(cards)}</div>'


def _strategy(report: ScoutReport) -> str:
    blocks = []
    for note in report.strategy:
        items = "".join(f"<li>{esc(point)}</li>" for point in note.points)
        blocks.append(f"""<div class="horizon">
  <p class="eyebrow">{esc(note.horizon)}</p>
  <h3 style="font-family:var(--display);font-size:22px;text-transform:uppercase;
             letter-spacing:.01em">{esc(note.headline)}</h3>
  <ul>{items}</ul>
</div>""")
    return f'<div class="grid" style="gap:16px">{"".join(blocks)}</div>'


def _ticker(report: ScoutReport) -> str:
    """Fixture difficulty grid: every club across the coming gameweeks."""
    from .analysis.fixtures import FixtureModel

    model = FixtureModel(report.state)
    start = report.gameweek
    span = 8
    weeks = list(range(start, start + span))

    header = "".join(f"<th>GW{gw}</th>" for gw in weeks)
    rows = []
    outlooks = []
    for team_id, team in report.state.teams.items():
        outlook = model.outlook(team_id, start, span)
        outlooks.append((outlook.mean_difficulty, team, outlook, team_id))
    outlooks.sort(key=lambda item: item[0])

    for _, team, outlook, team_id in outlooks:
        cells = []
        for gw in weeks:
            matches = [f for f in outlook.fixtures if f.gameweek == gw]
            if not matches:
                cells.append('<td><span class="fd fd-none">—</span></td>')
                continue
            double = " fd-dgw" if len(matches) > 1 else ""
            label = " / ".join(f.label for f in matches)
            difficulty = round(sum(f.difficulty for f in matches) / len(matches))
            cells.append(
                f'<td><span class="fd fd{difficulty}{double}">{esc(label)}</span></td>'
            )
        rows.append(f"<tr><td>{esc(team.short_name)}</td>{''.join(cells)}</tr>")

    return f"""<div class="scroll"><table class="tick">
<thead><tr><th>Club</th>{header}</tr></thead>
<tbody>{''.join(rows)}</tbody></table></div>
<p class="why" style="margin-top:11px">Sorted easiest run first. Green is a favourable
fixture, red a hard one; an amber outline marks a double gameweek. Difficulty here is the
official rating — the projections themselves use the finer-grained attack and defence
strength model, which is why a mid-rated fixture can still produce a strong projection.</p>"""


def _candidate_table(candidates, empty: str) -> str:
    if not candidates:
        return f'<p class="why">{esc(empty)}</p>'
    rows = []
    for candidate in candidates:
        player = candidate.player
        defcon = (
            f"{candidate.projection.defcon_chance*100:.0f}%"
            if player.position in rules.DEFCON_ELIGIBLE else "—"
        )
        reasons = "; ".join(candidate.reasons()[:3])
        rows.append(f"""<tr>
  <td><b>{esc(player.name)}</b></td>
  <td>{esc(candidate.team)}</td>
  <td>{esc(player.position_name)}</td>
  <td class="num">£{player.price:.1f}</td>
  <td class="num">{candidate.projection.per_match:.1f}</td>
  <td class="num">{player.xgi90:.2f}</td>
  <td class="num">{defcon}</td>
  <td class="num">{candidate.ownership:.1f}%</td>
  <td><span class="pill {_tier_class(candidate.tier)}">{esc(candidate.tier)}</span></td>
  <td style="white-space:normal;min-width:260px;font-size:12.5px;color:var(--text-dim)">{esc(reasons)}</td>
</tr>""")
    return f"""<div class="scroll"><table>
<thead><tr>
  <th>Player</th><th>Club</th><th>Pos</th><th>Price</th><th>Pts/match</th>
  <th>xGI/90</th><th>DefCon</th><th>Owned</th><th>Risk</th><th>Why</th>
</tr></thead><tbody>{''.join(rows)}</tbody></table></div>"""


TABS = [
    ("squad", "Your squad"),
    ("transfers", "Transfers"),
    ("strategy", "Strategy"),
    ("watchlist", "Watchlist"),
    ("fixtures", "Fixture ticker"),
    ("method", "Method"),
]

SCRIPT = """
(function(){
  var tabs = Array.prototype.slice.call(document.querySelectorAll('.tab'));
  var panels = Array.prototype.slice.call(document.querySelectorAll('.panel'));
  function show(name){
    tabs.forEach(function(t){ t.setAttribute('aria-selected', String(t.dataset.tab === name)); });
    panels.forEach(function(p){ p.hidden = (p.id !== 'panel-' + name); });
    try { localStorage.setItem('fplscout.tab', name); } catch (e) {}
    if (location.hash.slice(1) !== name) {
      history.replaceState(null, '', '#' + name);
    }
  }
  tabs.forEach(function(t){
    t.addEventListener('click', function(){ show(t.dataset.tab); });
  });
  function valid(name){ return name && document.getElementById('panel-' + name); }
  var saved = null;
  try { saved = localStorage.getItem('fplscout.tab'); } catch (e) {}
  var fromHash = location.hash.slice(1);
  show(valid(fromHash) ? fromHash : (valid(saved) ? saved : tabs[0].dataset.tab));
  window.addEventListener('hashchange', function(){
    var name = location.hash.slice(1);
    if (valid(name)) { show(name); }
  });
})();
"""


def _sheet(report: ScoutReport) -> str:
    squad = report.squad
    if squad:
        rank = f"{squad.overall_rank:,}" if squad.overall_rank else "—"
        stats = f"""
      <div class="stat"><b>{squad.total_points}</b><i>Points</i></div>
      <div class="stat"><b>{rank}</b><i>Overall rank</i></div>
      <div class="stat"><b>£{squad.value_m:.1f}m</b><i>Squad value</i></div>
      <div class="stat"><b>£{squad.bank_m:.1f}m</b><i>In the bank</i></div>
      <div class="stat"><b>{squad.free_transfers}</b><i>Free transfers</i></div>"""
        title = esc(squad.team_name)
        meta = f"{esc(squad.manager_name)} · Gameweek {report.gameweek} · {rules.SEASON}"
    else:
        stats = f'<div class="stat"><b>GW{report.gameweek}</b><i>Next deadline</i></div>'
        title = "FPL Scout"
        meta = f"No team loaded · {rules.SEASON}"

    return f"""<header class="sheet"><div class="sheet-in">
  <div>
    <div class="crest">{title} <span>/</span> Scout</div>
    <div class="sheet-meta">{meta}</div>
  </div>
  <div class="stats">{stats}</div>
</div></header>"""


def _method(report: ScoutReport) -> str:
    enriched = report.enriched
    return f"""<div class="grid g2">
<div class="card">
  <p class="eyebrow">How players are rated</p>
  <p class="why">Points already scored tell you what happened; they are a poor guide to what
  happens next. Every projection here is built from underlying numbers instead — expected
  goals and assists per 90, opponent-adjusted clean sheet odds, defensive-action rates
  against the {rules.SEASON} thresholds, save volume for keepers, and each player's own rate
  of earning bonus points. Those are then scaled by the minutes we actually expect him to
  play, which is where most fantasy projections quietly go wrong.</p>
</div>
<div class="card">
  <p class="eyebrow">Defensive contributions</p>
  <p class="why">Two points for {rules.DEFCON_THRESHOLD[2]} clearances, blocks, interceptions
  and tackles as a defender; {rules.DEFCON_THRESHOLD[3]} for a midfielder or forward, with ball
  recoveries counting too. Capped at two a match — double the threshold is not double the
  points. The season averages hide the difference between a player who clears the bar most
  weeks and one who spiked once, so this run checked the match-by-match history of
  <b>{enriched}</b> players and blended what actually happened with the model.</p>
</div>
<div class="card">
  <p class="eyebrow">Fixture difficulty</p>
  <p class="why">Rather than lean on the official 1–5 rating, each fixture is scored twice:
  once for what it offers the attack, once for what it means defensively, using the attack
  and defence strength ratings that move with form. Clean sheet odds come from a Poisson
  model on the resulting expected goals against.</p>
</div>
<div class="card">
  <p class="eyebrow">What the model cannot see</p>
  <p class="why">It does not read press conferences, and it cannot know that a manager has
  hinted at rotation, that a player is being managed back from injury, or that a cup replay
  is about to be scheduled. Check team news before the deadline. Doubles and blanks only
  exist here once the fixture list actually shows them — an empty ticker means the calendar
  has not been redrawn yet, not that none are coming.</p>
</div>
</div>"""


def render(report: ScoutReport, fragment: bool = False) -> str:
    """Build the page.

    With `fragment` set, the document shell is left off and only the head
    contents and body markup are returned, for embedding in a host page.
    """
    review = report.review
    gameweek = report.gameweek

    if review:
        squad_panel = f"""
<div class="block">
  <p class="eyebrow">Gameweek {gameweek} · {esc(review.formation)}</p>
  <h2 class="sec">The team sheet</h2>
  <p class="sec-note">Your strongest legal eleven for this deadline, chosen on projected
  points rather than reputation. Numbers on each card are that player's projection for
  GW{gameweek} alone. Projected total: <b>{review.projected_next_gw:.0f}</b> points this
  gameweek including the captain, <b>{review.projected_horizon:.0f}</b> across
  GW{gameweek}–{gameweek + report.horizon - 1}.</p>
  {_pitch(review, gameweek)}
</div>

<div class="block">
  <h2 class="sec">Who takes the armband</h2>
  <p class="sec-note">Three ways to play it. The captain is the single biggest decision of
  your week — it is worth more than most transfers.</p>
  {_captain_cards(review)}
</div>

{'<div class="block"><div class="note"><b>Watch out:</b><br>' + '<br>'.join(esc(w) for w in review.warnings) + '</div></div>' if review.warnings else ''}

<div class="block">
  <h2 class="sec">All fifteen, assessed</h2>
  <p class="sec-note">Every player you own, with the underlying numbers behind the verdict.
  <b>Horizon</b> is projected points across GW{gameweek}–{gameweek + report.horizon - 1};
  <b>DefCon</b> is the chance of hitting the defensive-contribution threshold in a given match.</p>
  {_squad_table(review, gameweek, report.state)}
</div>"""
    else:
        squad_panel = """<div class="note">No team loaded. Run the scout with
        <code>--team-id YOUR_ID</code> to see your own squad assessed here.</div>"""

    transfers_panel = f"""
<div class="block">
  <h2 class="sec">Three ways to use your transfers</h2>
  <p class="sec-note">Play it safe, take a chance, or take a risk. Gains are projected across
  GW{gameweek}–{gameweek + report.horizon - 1} and already account for any points hit.</p>
  {_transfer_plans(report)}
</div>
<div class="block">
  <h2 class="sec">Chips</h2>
  <p class="sec-note">Two sets of four this season. The first set expires at the
  GW{rules.FIRST_HALF_LAST_GW} deadline and cannot be carried over — an unplayed chip is
  simply lost.</p>
  {_chips(report)}
</div>"""

    watchlist_panel = f"""
<div class="block">
  <h2 class="sec">Differentials</h2>
  <p class="sec-note">Strong projections the field has largely missed — under
  {DIFFERENTIAL_OWNERSHIP:.0f}% ownership. In a mini-league these are how you gain ground:
  matching the template can only hold your position.</p>
  {_candidate_table(report.differentials, "No differentials clear the bar this week.")}
</div>
<div class="block">
  <h2 class="sec">The risk you are already running</h2>
  <p class="sec-note">Heavily owned players you do not have. Every one of these is a week
  where a haul costs you ground without you doing anything wrong.</p>
  {_candidate_table(report.template_gaps, "You hold the core of the template.")}
</div>
{''.join(f'''<div class="block">
  <h2 class="sec">Best {name}s</h2>
  {_candidate_table(candidates, "Nothing to show.")}
</div>''' for name, candidates in report.best_by_position.items())}"""

    tabs = "".join(
        f'<button class="tab" role="tab" data-tab="{key}" aria-selected="false">{esc(label)}</button>'
        for key, label in TABS
    )

    panels = {
        "squad": squad_panel,
        "transfers": transfers_panel,
        "strategy": f'<div class="block"><h2 class="sec">The plan</h2>'
                    f'<p class="sec-note">What to do now, what to build towards, and what '
                    f'decides the season.</p>{_strategy(report)}</div>',
        "watchlist": watchlist_panel,
        "fixtures": f'<div class="block"><h2 class="sec">Fixture ticker</h2>'
                    f'<p class="sec-note">The next eight gameweeks for all twenty clubs.</p>'
                    f'{_ticker(report)}</div>',
        "method": f'<div class="block"><h2 class="sec">How this was worked out</h2>'
                  f'<p class="sec-note">The reasoning behind every number on this page, and '
                  f'its limits.</p>{_method(report)}</div>',
    }
    panel_html = "".join(
        f'<section class="panel" id="panel-{key}" role="tabpanel" hidden>{panels[key]}</section>'
        for key, _ in TABS
    )

    team_name = esc(report.squad.team_name) if report.squad else "FPL Scout"
    banner = ""
    if fragment and getattr(report, "is_sample", False):
        banner = """<div class="wrap" style="padding-top:18px;padding-bottom:0">
  <div class="note"><b>Sample data.</b> This page is running on a generated season —
  invented clubs, invented players, invented numbers — so you can see how the scout
  presents things. Run it against your own team ID for real analysis.</div>
</div>"""

    body = f"""{_sheet(report)}{banner}
<div class="wrap">
  <div class="tabs" role="tablist">{tabs}</div>
  {panel_html}
  <footer>
    Generated {esc(report.generated_at)} · Gameweek {gameweek} · {rules.SEASON} rules ·
    {report.enriched} players checked match by match<br>
    Projections are estimates built from public Fantasy Premier League data. Check team news
    before the deadline — the model cannot read a press conference.
  </footer>
</div>
<script>{SCRIPT}</script>"""

    head = (
        '<title>' + team_name + ' Scout Report</title>\n'
        '<link rel="preconnect" href="https://fonts.googleapis.com">\n'
        '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>\n'
        '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?'
        'family=Anton&family=Archivo:wght@400;500;600;700&'
        'family=IBM+Plex+Mono:wght@400;500;600&display=swap">\n'
        '<style>' + CSS + '</style>'
    )

    if fragment:
        return head + "\n" + body

    return (
        '<!doctype html>\n<html lang="en"><head>\n'
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        + head +
        '\n</head><body>\n' + body + '\n</body></html>'
    )
