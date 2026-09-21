from __future__ import annotations

import argparse
from pathlib import Path


CARD = '''<div class="card section-gap" id="closedNotRealizedCard"><div class="feedback-head"><div style="flex:1;min-width:0"><div class="title" style="margin-bottom:3px">Закрыто и не реализовано — 5 дней</div><div class="note">История за последние 5 календарных дней МСК. Дата перевода берётся из closed_at amoCRM, причина — из причины отказа сделки.</div></div><div class="feedback-kpi"><span class="note">Закрыто</span><b id="closedNotRealizedCount">0</b></div></div><div class="desktop" style="margin-top:10px"><table><thead><tr><th>Дата перевода</th><th>Источник</th><th>Имя</th><th>Контакт</th><th>Менеджер CRM</th><th>Причина</th><th>Последний комментарий</th><th>Карточка CRM</th></tr></thead><tbody id="closedNotRealizedTb"></tbody></table></div><div class="mobile" id="closedNotRealizedMob"></div><div class="feedback-empty" id="closedNotRealizedEmpty" style="display:none">За последние 5 дней нет лидов, переведённых в «Закрыто и не реализовано»</div></div>\n'''

OUTCOME_CARD = '''<div class="card" style="grid-column:1/-1"><div class="title">Результаты реализации</div><div class="note" style="margin-bottom:10px">Успешно реализовано и причины «Закрыто и не реализовано» за выбранный период.</div><div class="hbars" id="outcomes"></div></div>'''

OUTCOME_RENDER = r'''function renderOutcomes(){var a=R[currentRange],o={},i,x,d,k,reason;if(!a)return;for(i=0;i<O.length;i++){x=O[i];d=String(x.date||x.ts||'').slice(0,10);if(!d||d<a.s||d>a.e)continue;if(x.result==='SUCCESS'){k='Успешно реализовано'}else if(x.result==='LOST'){reason=String(x.reason||'Не указана').trim()||'Не указана';k='Отказ: '+reason}else continue;o[k]=(o[k]||0)+1}bars('outcomes',o)}
'''

RENDER = r'''function renderClosedNotRealized(){var s='',m='',shown=0,i,x;for(i=0;i<C.length;i++){x=C[i];if(currentManager!=='all'&&norm(x.manager)!==currentManager)continue;shown++;var href=crmHref(x),link=href?'<a class="crm-link" href="'+href+'" target="_blank" rel="noopener noreferrer">Открыть лид</a>':'—';s+='<tr><td>'+esc(fmtTs(x.closed_at))+'</td><td><span class="badge src">'+esc(norm(x.source))+'</span></td><td>'+esc(norm(x.name))+'</td><td>'+esc(norm(x.identifier))+'</td><td>'+esc(norm(x.manager))+'</td><td>'+esc(norm(x.reason))+'</td><td>'+esc(norm(x.last_comment))+'</td><td>'+link+'</td></tr>';m+='<div class="lead"><div class="leadhead"><span>'+esc(norm(x.name))+' · '+esc(norm(x.identifier))+'</span><span class="badge alarm">Закрыто</span></div><div class="leadmeta">Переведён: '+esc(fmtTs(x.closed_at))+' · '+esc(norm(x.source))+'<br>Менеджер CRM: '+esc(norm(x.manager))+'<br>Причина: '+esc(norm(x.reason))+'<br>Последний комментарий: '+esc(norm(x.last_comment))+(href?'<br><a class="crm-link" href="'+href+'" target="_blank" rel="noopener noreferrer">Открыть лид</a>':'')+'</div></div>'}id('closedNotRealizedCount').textContent=shown;id('closedNotRealizedTb').innerHTML=s;id('closedNotRealizedMob').innerHTML=m;id('closedNotRealizedEmpty').style.display=shown?'none':'block'}
'''


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if text.count(old) != 1:
        raise ValueError(f"Expected exactly one {label} marker, found {text.count(old)}")
    return text.replace(old, new, 1)


def inject(html: str) -> str:
    if 'id="closedNotRealizedCard"' in html:
        return html

    html = replace_once(
        html,
        '<div class="card section-gap" id="waitingStageCard"',
        CARD + '<div class="card section-gap" id="waitingStageCard"',
        "widget card",
    )
    html = replace_once(
        html,
        '<div class="card"><div class="title">Тип мероприятия</div><div class="hbars" id="events"></div></div></div>\n<div class="card section-gap"><div class="title">Последние лиды</div>',
        '<div class="card"><div class="title">Тип мероприятия</div><div class="hbars" id="events"></div></div>' + OUTCOME_CARD + '</div>\n<div class="card section-gap"><div class="title">Последние лиды</div>',
        "outcome analytics card",
    )
    html = replace_once(
        html,
        "var R={},DY=[],L=[],N=[],F=[],FS={},W=[],currentRange=",
        "var R={},DY=[],L=[],N=[],F=[],FS={},W=[],C=[],CS={},O=[],currentRange=",
        "dashboard state",
    )
    html = replace_once(
        html,
        "function renderWaitingStage(){",
        OUTCOME_RENDER + RENDER + "function renderWaitingStage(){",
        "render functions",
    )
    html = replace_once(
        html,
        "id('notCount').textContent=nr.length;renderFeedback()}",
        "id('notCount').textContent=nr.length;renderFeedback();renderOutcomes();renderClosedNotRealized()}",
        "range render hook",
    )
    html = replace_once(
        html,
        "W=view.waiting_stage||[];return {snapshot:",
        "W=view.waiting_stage||[];C=view.closed_not_realized||[];CS=view.closed_not_realized_summary||{};O=view.outcomes||[];return {snapshot:",
        "view state hook",
    )
    html = replace_once(
        html,
        "renderFeedback();renderWaitingStage()}",
        "renderFeedback();renderClosedNotRealized();renderWaitingStage()}",
        "manager render hook",
    )
    return html


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--path", required=True)
    args = parser.parse_args()
    path = Path(args.path)
    html = path.read_text(encoding="utf-8")
    path.write_text(inject(html), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
