from __future__ import annotations

import argparse
from pathlib import Path


CARD = '''<div class="card section-gap" id="closedNotRealizedCard"><div class="feedback-head"><div style="flex:1;min-width:0"><div class="title" style="margin-bottom:3px">Закрыто и не реализовано — 5 дней</div><div class="note">История за последние 5 календарных дней МСК. Дата перевода берётся из closed_at amoCRM, причина — из причины отказа сделки.</div></div><div class="feedback-kpi"><span class="note">Закрыто</span><b id="closedNotRealizedCount">0</b></div></div><div class="desktop" style="margin-top:10px"><table><thead><tr><th>Дата перевода</th><th>Источник</th><th>Имя</th><th>Контакт</th><th>Менеджер CRM</th><th>Причина</th><th>Последний комментарий</th><th>Карточка CRM</th></tr></thead><tbody id="closedNotRealizedTb"></tbody></table></div><div class="mobile" id="closedNotRealizedMob"></div><div class="feedback-empty" id="closedNotRealizedEmpty" style="display:none">За последние 5 дней нет лидов, переведённых в «Закрыто и не реализовано»</div></div>\n'''

OUTCOME_CARD = '''<div class="card" style="grid-column:1/-1"><div class="title">Результаты реализации</div><div class="note" style="margin-bottom:10px">Успешно реализовано и причины «Закрыто и не реализовано» за выбранный период.</div><div class="hbars" id="outcomes"></div></div>'''

PIPELINE_ACTIVITY_CARD = '''<div class="card" id="pipelineActivityCard" style="grid-column:1/-1"><div class="pipeline-activity-head"><div style="flex:1;min-width:0"><div class="title" style="margin-bottom:3px">Активность по этапам воронки</div><div class="note">Каждый реальный перевод существующей заявки в новый этап amoCRM. Блок живёт отдельно от верхнего выбора периода.</div></div><label class="pipeline-week-control"><span>Неделя</span><select id="pipelineWeekSelect" aria-label="Выбор недели"></select></label></div><div class="pipeline-activity-scroll"><div class="pipeline-activity-grid" id="pipelineActivityGrid"></div></div><div class="feedback-empty" id="pipelineActivityEmpty" style="display:none">За выбранную неделю перемещений нет</div></div>'''

PIPELINE_ACTIVITY_CSS = r'''
#pipelineActivityCard{padding:8px;justify-self:start;width:max-content;max-width:100%}
#pipelineActivityCard .title{font-size:14px;margin-bottom:2px}
#pipelineActivityCard .note{font-size:10px}
.pipeline-activity-head{display:flex;align-items:flex-start;justify-content:space-between;gap:8px;flex-wrap:wrap}
.pipeline-week-control{display:flex;align-items:center;gap:5px;color:#c4cfdb;font-size:10px;font-weight:700}
.pipeline-week-control select{background:#111d2c;color:#fff;border:1px solid #2a3b50;border-radius:7px;padding:5px 7px;font-size:10px;font-weight:700;outline:none}
.pipeline-activity-scroll{overflow-x:auto;padding-bottom:2px;margin-top:7px}
.pipeline-activity-grid{display:grid;grid-template-columns:118px repeat(7,28px) 36px;gap:2px;width:max-content;min-width:0;align-items:stretch}
.pa-head,.pa-label,.pa-cell,.pa-total{border:1px solid #223146;border-radius:5px;min-height:23px;display:flex;align-items:center}
.pa-head{justify-content:center;text-align:center;background:#0d1825;color:#aebdd0;font-size:8px;padding:2px 1px;line-height:1}
.pa-head:first-child{justify-content:flex-start;padding-left:6px}
.pa-head.today{outline:1px solid #7d5cff88;color:#fff}
.pa-label{justify-content:flex-start;background:#0d1825;padding:3px 4px;font-size:9px;font-weight:700;line-height:1.02}
.pa-label .dot{width:5px;height:5px;border-radius:50%;margin-right:4px;flex:0 0 auto}
.pa-cell,.pa-total{justify-content:center;font-size:9px;font-weight:800;padding:1px}
.pa-cell.zero{background:#0d1825;color:#718196}
.pa-total{background:#151f2f}
.pa-subtoday{display:block;color:#9bb8ff;font-size:7px;margin-top:1px}
@media(max-width:760px){#pipelineActivityCard{padding:7px;width:100%}.pipeline-activity-head{gap:5px}.pipeline-week-control{width:100%;justify-content:space-between}.pipeline-week-control select{flex:0 1 170px;max-width:170px}.pipeline-activity-grid{grid-template-columns:105px repeat(7,27px) 34px;gap:2px}.pa-head,.pa-label,.pa-cell,.pa-total{min-height:22px;border-radius:4px}.pa-label{font-size:8px;padding:2px 4px}.pa-cell,.pa-total{font-size:9px}}
'''

PIPELINE_ACTIVITY_RENDER = r'''function renderPipelineActivity(){var grid=id('pipelineActivityGrid'),sel=id('pipelineWeekSelect'),empty=id('pipelineActivityEmpty'),weeks=(PA&&PA.weeks)||[],stages=(PA&&PA.stages)||[],days=(PA&&PA.days)||{},active=[],i,j,week,dates,maxCount=0,count,total,html='',palette=['78,161,255','54,209,107','255,174,66','255,95,103','125,92,255','77,211,191','245,141,66','156,163,175'];if(!grid||!sel)return;if(!weeks.length){sel.innerHTML='<option>Нет данных</option>';grid.innerHTML='';empty.style.display='block';return}if(pipelineWeekIndex<0||pipelineWeekIndex>=weeks.length)pipelineWeekIndex=0;sel.innerHTML='';for(i=0;i<weeks.length;i++){var opt=document.createElement('option');opt.value=String(i);opt.textContent=weeks[i].label||('Неделя '+(i+1));sel.appendChild(opt)}sel.value=String(pipelineWeekIndex);sel.onchange=function(){pipelineWeekIndex=parseInt(this.value||'0',10)||0;renderPipelineActivity()};week=weeks[pipelineWeekIndex];dates=week.dates||[];for(i=0;i<stages.length;i++){total=0;for(j=0;j<dates.length;j++){count=parseInt(((days[dates[j]]||{})[String(stages[i].id)]||0),10)||0;total+=count;if(count>maxCount)maxCount=count}if(total>0)active.push(stages[i])}if(!active.length){grid.innerHTML='';empty.style.display='block';return}html+='<div class="pa-head">Этап</div>';for(j=0;j<dates.length;j++){var isToday=dates[j]===String(PA.today||'');html+='<div class="pa-head'+(isToday?' today':'')+'">'+esc(fd(dates[j]).slice(0,5))+(isToday?'<span class="pa-subtoday">Сегодня</span>':'')+'</div>'}html+='<div class="pa-head">Σ</div>';for(i=0;i<active.length;i++){var rgb=palette[i%palette.length];total=0;html+='<div class="pa-label"><span class="dot" style="background:rgb('+rgb+')"></span>'+esc(active[i].name)+'</div>';for(j=0;j<dates.length;j++){count=parseInt(((days[dates[j]]||{})[String(active[i].id)]||0),10)||0;total+=count;if(count){var alpha=.16+(maxCount?count/maxCount*.48:0);html+='<div class="pa-cell" style="background:rgba('+rgb+','+alpha.toFixed(2)+');border-color:rgba('+rgb+',.42)">'+count+'</div>'}else html+='<div class="pa-cell zero">0</div>'}html+='<div class="pa-total">'+total+'</div>'}grid.innerHTML=html;empty.style.display='none'}
'''

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
        '<div class="card"><div class="title">Тип мероприятия</div><div class="hbars" id="events"></div></div>' + OUTCOME_CARD + PIPELINE_ACTIVITY_CARD + '</div>\n<div class="card section-gap"><div class="title">Последние лиды</div>',
        "outcome analytics card",
    )
    html = replace_once(
        html,
        "</style>",
        PIPELINE_ACTIVITY_CSS + "</style>",
        "pipeline activity styles",
    )
    html = replace_once(
        html,
        "var R={},DY=[],L=[],N=[],F=[],FS={},W=[],currentRange=",
        "var R={},DY=[],L=[],N=[],F=[],FS={},W=[],C=[],CS={},O=[],PA={},pipelineWeekIndex=0,currentRange=",
        "dashboard state",
    )
    html = replace_once(
        html,
        "function renderWaitingStage(){",
        PIPELINE_ACTIVITY_RENDER + OUTCOME_RENDER + RENDER + "function renderWaitingStage(){",
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
        "W=view.waiting_stage||[];C=view.closed_not_realized||[];CS=view.closed_not_realized_summary||{};O=view.outcomes||[];PA=view.pipeline_activity||{};return {snapshot:",
        "view state hook",
    )
    html = replace_once(
        html,
        "renderFeedback();renderWaitingStage()}",
        "renderFeedback();renderClosedNotRealized();renderWaitingStage()}",
        "manager render hook",
    )
    html = replace_once(
        html,
        "render(currentRange);return true}",
        "render(currentRange);renderPipelineActivity();return true}",
        "pipeline activity apply hook",
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
