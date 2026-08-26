from __future__ import annotations

import argparse
from pathlib import Path

TOKEN_PLACEHOLDER = "const GITHUB_TOKEN='__GITHUB_TOKEN__';"
GITHUB_CONFIG = "const GH_OWNER='Alex19011901',GH_REPO='lead-control',GH_WORKFLOW='lead-control.yml',GH_REF='main',GH_DATA_REF='data';"
PAGES_DATA_CONFIG = "const DASHBOARD_DATA_URL='./dashboard_view.json';"
PAGES_REFRESH_BLOCK = r"""async function requestJson(url,options){options=options||{};if(typeof fetch==='function')return fetch(url,options).then(function(res){if(!res.ok)throw new Error('dashboard_'+res.status);return res.json()});return new Promise(function(resolve,reject){var x=new XMLHttpRequest();x.open(options.method||'GET',url,true);x.onload=function(){if(x.status<200||x.status>=300){reject(new Error('dashboard_'+x.status));return}try{resolve(JSON.parse(x.responseText))}catch(e){reject(new Error('dashboard_invalid_json'))}};x.onerror=function(){reject(new Error('dashboard_network'))};x.send(null)})}
function dashboardDataUrl(){return DASHBOARD_DATA_URL+(DASHBOARD_DATA_URL.indexOf('?')>=0?'&':'?')+'_lc_cb='+encodeURIComponent(Date.now()+'-'+Math.random().toString(36).slice(2))}
async function loadDashboardPayload(){return requestJson(dashboardDataUrl(),{cache:'no-store'})}
function sleep(ms){return new Promise(function(resolve){setTimeout(resolve,ms)})}
function snapshotValue(payload){return String((payload&&payload.snapshot_generated_at)||payload.snapshot_at||payload.generated_at||'')}
function snapshotIsNewer(snap,previous){snap=String(snap||'');previous=String(previous||'');if(!snap)return false;if(!previous)return true;var a=Date.parse(snap),b=Date.parse(previous);if(!isNaN(a)&&!isNaN(b))return a>b;return snap>previous}
async function waitForPublicRefresh(previous,serial){var deadline=Date.now()+20*60*1000,lastError=null;while(Date.now()<deadline){if(serial!==refreshSerial)throw new Error('refresh_cancelled');try{var payload=await loadDashboardPayload(),snap=snapshotValue(payload);if(snapshotIsNewer(snap,previous)){progress(4,'Сохранение данных…');return payload}}catch(e){lastError=e}progress(2,'Сбор Telegram/MAX + amoCRM…');await sleep(5000)}throw lastError||new Error('refresh_timeout')}
async function refreshDashboard(){if(refreshInProgress)return;refreshInProgress=true;var btn=id('refreshBtn'),previous=currentSnapshot,serial=++refreshSerial;btn.disabled=true;btn.textContent='Обновление…';progressStart();try{if(!previous){try{previous=snapshotValue(await loadDashboardPayload())||previous}catch(e){}}progress(1,'Ожидание обновления системы…');var payload=await waitForPublicRefresh(previous,serial);if(serial!==refreshSerial)throw new Error('refresh_cancelled');if(!applyDashboard(payload))throw new Error('render_failed');setRefreshState('Обновлено '+new Date().toLocaleTimeString('ru-RU',{timeZone:'Europe/Moscow',hour:'2-digit',minute:'2-digit'}),false);progressStop(true)}catch(e){setRefreshState('Ошибка обновления',true);progressStop(false)}finally{refreshSerial++;btn.disabled=false;btn.textContent='Обновить данные';refreshInProgress=false}}"""


def build_mirror(html: str) -> str:
    """Build the public GitHub Pages shell from the approved PageShare template.

    The production PageShare template is left untouched. The public Pages build
    never embeds a GitHub token and never calls the private GitHub API from the
    browser. It reads the exported dashboard payload from ./dashboard_view.json
    and waits for the public collector to publish a newer snapshot on refresh.
    """
    if html.count(TOKEN_PLACEHOLDER) != 1:
        raise ValueError("Expected exactly one GitHub token placeholder")
    if html.count(GITHUB_CONFIG) != 1:
        raise ValueError("Expected exactly one GitHub config line")

    result = html.replace(TOKEN_PLACEHOLDER, PAGES_DATA_CONFIG, 1)
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
        "Bearer",
        "Authorization",
        "api.github.com",
        "actions/workflows",
        "dispatchWorkflow",
        "findRun",
        "GH_ACCESS_STORAGE",
        "GH_OWNER",
        "GH_REPO",
        "GH_WORKFLOW",
        "GH_REF",
        "GH_DATA_REF",
    )
    found = [value for value in forbidden if value in result]
    if found:
        raise ValueError("A GitHub token-like value must never be embedded in mirror output")
    if "./dashboard_view.json" not in result:
        raise ValueError("Public dashboard must read local dashboard_view.json")
    if "waitForPublicRefresh" not in result:
        raise ValueError("Public dashboard refresh must wait for a newer snapshot")

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
