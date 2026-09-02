from __future__ import annotations

import argparse
from pathlib import Path

TOKEN_PLACEHOLDER = "const GITHUB_TOKEN='__GITHUB_TOKEN__';"
GITHUB_CONFIG = "const GH_OWNER='Alex19011901',GH_REPO='lead-control',GH_WORKFLOW='lead-control.yml',GH_REF='main',GH_DATA_REF='data';"
PAGES_DATA_CONFIG = "const DASHBOARD_DATA_URL='./dashboard_view.json';"
PUBLIC_REFRESH_CONFIG = "const PUBLIC_REFRESH_TOKEN='__PUBLIC_REFRESH_TOKEN__',GH_OWNER='Alex19011901',GH_REPO='lead-control-pages',GH_WORKFLOW='lead-control-public.yml',GH_REF='main';"
PAGES_REFRESH_BLOCK = r"""async function requestJson(url,options){options=options||{};if(typeof fetch==='function')return fetch(url,options).then(function(res){if(!res.ok)throw new Error('request_'+res.status);return res.status===204?null:res.json()});return new Promise(function(resolve,reject){var x=new XMLHttpRequest();x.open(options.method||'GET',url,true);var hs=options.headers||{};Object.keys(hs).forEach(function(k){x.setRequestHeader(k,hs[k])});x.onload=function(){if(x.status<200||x.status>=300){reject(new Error('request_'+x.status));return}try{resolve(x.status===204?null:JSON.parse(x.responseText))}catch(e){reject(new Error('request_invalid_json'))}};x.onerror=function(){reject(new Error('request_network'))};x.send(options.body||null)})}
function dashboardDataUrl(){return DASHBOARD_DATA_URL+(DASHBOARD_DATA_URL.indexOf('?')>=0?'&':'?')+'_lc_cb='+encodeURIComponent(Date.now()+'-'+Math.random().toString(36).slice(2))}
async function loadDashboardPayload(){return requestJson(dashboardDataUrl(),{cache:'no-store'})}
function gh(path,options){options=options||{};var method=String(options.method||'GET').toUpperCase();if(method==='GET'){path+=(path.indexOf('?')>=0?'&':'?')+'_lc_cb='+encodeURIComponent(Date.now()+'-'+Math.random().toString(36).slice(2));options.cache='no-store'}var headers={Authorization:'Bearer '+PUBLIC_REFRESH_TOKEN,Accept:'application/vnd.github+json','X-GitHub-Api-Version':'2022-11-28'};options.headers=Object.assign(headers,options.headers||{});return requestJson('https://api.github.com/repos/'+GH_OWNER+'/'+GH_REPO+path,options)}
function sleep(ms){return new Promise(function(resolve){setTimeout(resolve,ms)})}
function snapshotValue(payload){return String((payload&&payload.snapshot_generated_at)||payload.snapshot_at||payload.generated_at||'')}
function snapshotIsNewer(snap,previous){snap=String(snap||'');previous=String(previous||'');if(!snap)return false;if(!previous)return true;var a=Date.parse(snap),b=Date.parse(previous);if(!isNaN(a)&&!isNaN(b))return a>b;return snap>previous}
async function dispatchPublicWorkflow(){var created=new Date().toISOString();await gh('/actions/workflows/'+encodeURIComponent(GH_WORKFLOW)+'/dispatches',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({ref:GH_REF})});return {created:created,runId:null,reused:false}}
async function listPublicRuns(){var data=await gh('/actions/workflows/'+encodeURIComponent(GH_WORKFLOW)+'/runs?branch='+encodeURIComponent(GH_REF)+'&per_page=20');return data.workflow_runs||[]}
async function findActivePublicRun(){var runs=await listPublicRuns(),active={'queued':1,'pending':1,'in_progress':1,'waiting':1,'requested':1},i;for(i=0;i<runs.length;i++)if(active[String(runs[i].status||'')])return runs[i];return null}
async function ensurePublicWorkflow(){var active=await findActivePublicRun();if(active)return {created:active.created_at||new Date().toISOString(),runId:active.id,reused:true};return dispatchPublicWorkflow()}
async function findPublicRun(created,runId){var runs=await listPublicRuns(),after=Date.parse(created)-120000,candidate=null,c,i;for(i=0;i<runs.length;i++){if(runId&&String(runs[i].id)===String(runId))return runs[i];c=Date.parse(runs[i].created_at||'');if(runs[i].event==='workflow_dispatch'&&!isNaN(c)&&c>=after&&!candidate)candidate=runs[i]}return candidate}
async function waitForPublicRefresh(created,previous,serial,runId){var deadline=Date.now()+20*60*1000,lastError=null,run=runId?{id:runId}:null,workflowDone=false,payload=null,snap='';while(Date.now()<deadline){if(serial!==refreshSerial)throw new Error('refresh_cancelled');try{run=await findPublicRun(created,run&&run.id);if(run){if(run.status==='queued'||run.status==='pending'||run.status==='waiting'||run.status==='requested')progress(1,'Проверка системы…');else if(run.status==='in_progress')progress(2,'Сбор Telegram/MAX + amoCRM…');else if(run.status==='completed'){if(run.conclusion!=='success')throw new Error('workflow_failed');workflowDone=true;progress(3,'Сборка дашборда…')}}}catch(e){lastError=e;if(String(e.message||e)==='workflow_failed')throw e}try{payload=await loadDashboardPayload();snap=snapshotValue(payload);if(snapshotIsNewer(snap,previous)){progress(4,'Сохранение данных…');return payload}if(workflowDone&&payload){progress(4,'Сохранение данных…');return payload}}catch(e){lastError=e}await sleep(5000)}throw lastError||new Error('refresh_timeout')}
async function refreshDashboard(){if(refreshInProgress)return;refreshInProgress=true;var btn=id('refreshBtn'),previous=currentSnapshot,serial=++refreshSerial;btn.disabled=true;btn.textContent='Обновление…';progressStart();try{if(!previous){try{previous=snapshotValue(await loadDashboardPayload())||previous}catch(e){}}progress(1,'Проверка системы…');var start=await ensurePublicWorkflow();if(start.reused)progress(1,'Обновление уже запущено…');var payload=await waitForPublicRefresh(start.created,previous,serial,start.runId);if(serial!==refreshSerial)throw new Error('refresh_cancelled');if(!applyDashboard(payload))throw new Error('render_failed');setRefreshState('Обновлено '+new Date().toLocaleTimeString('ru-RU',{timeZone:'Europe/Moscow',hour:'2-digit',minute:'2-digit'}),false);progressStop(true)}catch(e){setRefreshState('Ошибка обновления',true);progressStop(false)}finally{refreshSerial++;btn.disabled=false;btn.textContent='Обновить данные';refreshInProgress=false}}
"""


def build_mirror(html: str) -> str:
    """Build the public GitHub Pages shell from the approved PageShare template.

    The production PageShare template is left untouched. The public Pages build
    never embeds the private GitHub token and never calls the private GitHub API
    from the browser. It reads the exported dashboard payload from
    ./dashboard_view.json and uses the public refresh token placeholder to
    dispatch the public collector on refresh.
    """
    if html.count(TOKEN_PLACEHOLDER) != 1:
        raise ValueError("Expected exactly one GitHub token placeholder")
    if html.count(GITHUB_CONFIG) != 1:
        raise ValueError("Expected exactly one GitHub config line")

    result = html.replace(TOKEN_PLACEHOLDER, PUBLIC_REFRESH_CONFIG + "\n" + PAGES_DATA_CONFIG, 1)
    result = result.replace(GITHUB_CONFIG + "\n", "", 1)

    start = result.find("async function requestJson(")
    end = result.find("\nasync function initialLoad()", start)
    if start < 0 or end < 0:
        raise ValueError("Expected GitHub refresh block was not found")
    result = result[:start] + PAGES_REFRESH_BLOCK + result[end:]

    if TOKEN_PLACEHOLDER in result:
        raise ValueError("GitHub token placeholder remained in mirror output")
    forbidden = (
        "GITHUB_TOKEN",
        "github_pat_",
        "ghp_",
        "gho_",
        "lead-control.yml",
        "findRun",
        "GH_ACCESS_STORAGE",
        "GH_DATA_REF",
    )
    found = [value for value in forbidden if value in result]
    if found:
        raise ValueError("A GitHub token-like value must never be embedded in mirror output")
    if "./dashboard_view.json" not in result:
        raise ValueError("Public dashboard must read local dashboard_view.json")
    if "waitForPublicRefresh" not in result:
        raise ValueError("Public dashboard refresh must wait for a newer snapshot")
    if "dispatchPublicWorkflow" not in result:
        raise ValueError("Public dashboard refresh must dispatch the public workflow")
    if "__PUBLIC_REFRESH_TOKEN__" not in result:
        raise ValueError("Public refresh token placeholder must remain for workflow injection")

    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--input",
        default="dashboard/pageshare/index.html",
        help="Approved PageShare dashboard template",
    )
    parser.add_argument(
        "--output",
        default="dashboard/github-pages/index.html",
        help="Generated public GitHub Pages shell",
    )
    args = parser.parse_args()

    source = Path(args.input)
    output = Path(args.output)
    html = source.read_text(encoding="utf-8")
    rendered = build_mirror(html)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(rendered, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
