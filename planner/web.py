"""FastAPI HTTP API and Redis Pub/Sub backed SSE."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import date
import json
from uuid import UUID

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from redis import Redis
from redis.asyncio import Redis as AsyncRedis
from redis.exceptions import RedisError

from planner.application.jobs import SubmitPlanningJob
from planner.domain.jobs import JobStatus
from planner.infrastructure.redis_jobs import RedisPlanningJobs, redis_url
from planner.infrastructure.test_data import DEFAULT_PLANNING_DAY, generate_test_data
from planner.presentation import job_payload, plan_payload


@asynccontextmanager
async def lifespan(app: FastAPI):
    client = Redis.from_url(redis_url(), decode_responses=True, socket_connect_timeout=5, socket_timeout=10)
    events = AsyncRedis.from_url(redis_url(), decode_responses=True, socket_connect_timeout=5, socket_timeout=20)
    app.state.jobs = RedisPlanningJobs(client)
    app.state.events = events
    try:
        await events.ping()
        yield
    finally:
        await events.aclose()
        await asyncio.to_thread(client.close)


app = FastAPI(title='Производственный планировщик', lifespan=lifespan)


@app.exception_handler(RedisError)
async def redis_error(request: Request, error: RedisError):
    return JSONResponse(status_code=503, content={'detail': 'Очередь заданий временно недоступна. Повторите попытку позже.'})


class CreateJob(BaseModel):
    model_config = ConfigDict(extra='forbid')
    count: int = Field(default=1, ge=1, le=30, strict=True)
    planning_day: date = DEFAULT_PLANNING_DAY
    horizon_days: int = Field(default=14, ge=1, le=60, strict=True)
    compare_departments: bool = True


@app.get('/', response_class=HTMLResponse)
async def index():
    return PAGE


@app.post('/api/jobs', status_code=202)
def create_job(body: CreateJob, request: Request):
    data = generate_test_data(planning_day=body.planning_day).request
    data = replace(data, task=replace(data.task, count=body.count),
                   horizon_days=body.horizon_days, compare_departments=body.compare_departments)
    job = SubmitPlanningJob(request.app.state.jobs).submit(data)
    return {'job': job_payload(job), 'eventsUrl': f'/api/jobs/{job.id}/events', 'resultUrl': f'/api/jobs/{job.id}'}


@app.get('/api/jobs')
def list_jobs(request: Request):
    return [job_payload(job) for job in request.app.state.jobs.list()]


def snapshot(store: RedisPlanningJobs, job_id: str):
    job = store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail='Задание не найдено')
    return plan_payload(job, store.get_request(job_id))


@app.get('/api/jobs/{job_id}')
def get_job(job_id: UUID, request: Request):
    return snapshot(request.app.state.jobs, str(job_id))


@app.get('/api/jobs/{job_id}/events')
async def job_events(job_id: UUID, request: Request):
    store = request.app.state.jobs
    key = str(job_id)
    if await asyncio.to_thread(store.get, key) is None:
        raise HTTPException(status_code=404, detail='Задание не найдено')

    async def stream():
        try:
            async with request.app.state.events.pubsub() as pubsub:
                await pubsub.subscribe(store.channel(key))
                # Wait for subscribe acknowledgement before reading the snapshot.
                # A completion between subscribe and snapshot is then never lost.
                while True:
                    acknowledgement = await pubsub.get_message(ignore_subscribe_messages=False, timeout=5)
                    if acknowledgement and acknowledgement['type'] == 'subscribe':
                        break
                    if await request.is_disconnected():
                        return
                last_state = None
                while not await request.is_disconnected():
                    payload = await asyncio.to_thread(snapshot, store, key)
                    status = payload['job']['status']
                    state = (status, payload['completedDepartments'])
                    if state != last_state:
                        yield 'event: job\ndata: ' + json.dumps(payload, ensure_ascii=False) + '\n\n'
                        last_state = state
                    if status in (JobStatus.COMPLETED.value, JobStatus.FAILED.value):
                        return
                    # Pub/Sub wakes the stream immediately; heartbeat also repairs
                    # notifications missed during a transient connection failure.
                    message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=15)
                    if message is None:
                        yield ': heartbeat\n\n'
        except RedisError:
            yield 'event: unavailable\ndata: {"detail":"Связь с Redis прервана. Переподключаемся…"}\n\n'

    return StreamingResponse(stream(), media_type='text/event-stream', headers={
        'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no',
    })


PAGE = r'''<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Производственный планировщик</title>
<style>
:root{--ink:#182230;--muted:#667085;--line:#e5e9f0;--paper:#fff;--bg:#f5f7fb;--blue:#2563eb}*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:14px Inter,system-ui,sans-serif}.top{padding:28px 5vw 24px;background:#101828;color:#fff}.top h1{margin:0;font-size:25px}.top p{margin:7px 0 0;color:#cbd5e1}.controls{display:flex;flex-wrap:wrap;gap:14px;align-items:end;padding:18px 5vw;background:var(--paper);border-bottom:1px solid var(--line)}label{display:grid;gap:6px;color:var(--muted);font-weight:600}input,select,button{height:38px;border-radius:8px;border:1px solid #cfd6e2;background:#fff;padding:0 10px;font:inherit;color:var(--ink)}button{background:var(--blue);border:0;color:#fff;font-weight:700;cursor:pointer;padding:0 18px}.wrap{padding:22px 5vw}.cards{display:grid;grid-template-columns:repeat(4,minmax(120px,1fr));gap:12px;margin-bottom:20px}.card{background:#fff;border:1px solid var(--line);border-radius:10px;padding:14px}.card b{display:block;font-size:20px;margin-top:4px}.caption{color:var(--muted);font-size:12px}.chart{background:#fff;border:1px solid var(--line);border-radius:10px;overflow:auto}.axis,.row{min-width:850px;display:grid;grid-template-columns:220px 1fr}.axis{position:sticky;top:0;background:#fff;z-index:2;border-bottom:1px solid var(--line);height:42px}.axis-name{padding:13px 15px;font-weight:700}.scale{position:relative;border-left:1px solid var(--line)}.tick{position:absolute;top:0;height:100%;border-left:1px solid var(--line);padding:12px 0 0 5px;color:var(--muted);font-size:11px}.row{min-height:58px;border-bottom:1px solid var(--line)}.label{padding:10px 15px;line-height:19px}.label small{display:block;color:var(--muted)}.lane{position:relative;border-left:1px solid var(--line);background:repeating-linear-gradient(90deg,#fff 0,#fff calc(25% - 1px),#f4f6f9 calc(25% - 1px),#f4f6f9 25%)}.bar{position:absolute;top:12px;height:34px;border-radius:6px;color:#fff;padding:8px 9px;font-size:11px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;cursor:help;box-shadow:0 2px 4px #10182822}.empty,.error{padding:40px;text-align:center;color:var(--muted)}.legend{display:flex;gap:14px;flex-wrap:wrap;margin:0 0 10px;color:var(--muted)}.dot{display:inline-block;width:10px;height:10px;border-radius:3px;margin-right:4px}@media(max-width:650px){.cards{grid-template-columns:repeat(2,1fr)}.top,.controls,.wrap{padding-left:16px;padding-right:16px}}
.tech-process{margin-top:24px}.tech-process h2{font-size:20px}.process-tree{margin:0;padding:16px;background:#fff;border:1px solid var(--line);border-radius:10px}.process-tree,.process-tree ul{list-style:none}.process-tree ul{margin:10px 0 0 8px;padding-left:22px;border-left:1px solid #cfd6e2}.process-tree li{position:relative;margin:10px 0}.process-tree ul>li:before{content:"";position:absolute;left:-22px;top:12px;width:16px;border-top:1px solid #cfd6e2}.process-tree summary{cursor:pointer;font-weight:600;line-height:24px;overflow-wrap:anywhere}.process-tree summary:focus-visible{outline:2px solid var(--blue);outline-offset:3px;border-radius:3px}.process-tree .operation-name{display:block;line-height:24px;font-weight:600;overflow-wrap:anywhere}.process-tree .operation-info{display:block;color:var(--muted);font-size:12px;line-height:20px;overflow-wrap:anywhere}@media(max-width:650px){.process-tree{padding:10px}.process-tree ul{padding-left:16px;margin-left:4px}.process-tree ul>li:before{left:-16px;width:10px}}
.comparison{margin-top:24px}.comparison h2{font-size:20px;margin-top:0}.comparison select{width:100%;max-width:650px}.comparison-row{display:grid;grid-template-columns:220px 1fr;align-items:center;gap:12px;padding:12px 0;border-top:1px solid var(--line)}.comparison-track{height:30px;background:#f2f4f7;border-radius:5px;overflow:hidden}.comparison-fill{height:100%;background:#98a2b3;border-radius:5px}.comparison-row.selected .comparison-fill{background:var(--blue)}.comparison-row small{display:block;color:var(--muted);line-height:20px}.bar:focus-visible{outline:3px solid var(--ink);outline-offset:2px}button:disabled{opacity:.6;cursor:wait}@media(max-width:650px){.comparison-row{grid-template-columns:140px 1fr}}
</style></head><body>
<header class="top"><h1>Производственный планировщик</h1><p>CP-SAT · минимизация срока заказа · диаграмма Ганта по сотрудникам</p></header>
<form class="controls" id="form"><label>Изделий в заказе<input id="count" type="number" min="1" max="30" value="1"></label><label>Дата планирования<input id="date" type="date" value="2026-10-05"></label><label>Горизонт, дней<input id="horizon" type="number" min="1" max="60" value="14"></label><label>Бригада (подразделение)<select id="department"><option value="">Все бригады</option></select></label><button>Сравнить бригады</button></form>
<main class="wrap"><section class="cards" id="cards"></section><section class="card" id="job" style="margin-bottom:20px"></section><div class="legend" id="legend"></div><section class="chart"><div class="axis"><div class="axis-name">Бригада (Department)</div><div class="scale" id="scale"></div></div><div id="rows"><div class="empty">Рассчитываем оптимальный план…</div></div></section><section class="comparison card" id="comparison" hidden aria-labelledby="comparison-title"><h2 id="comparison-title">Сравнение выполнения всего задания</h2><p class="caption">Каждая бригада выполняет весь заказ самостоятельно. Все сценарии используют одну дату начала и одинаковый горизонт. Расчёты выполняются последовательно, результаты показаны на общей шкале времени.</p><div id="comparison-rows"></div></section><section class="tech-process" aria-labelledby="process-title"><h2 id="process-title">Техпроцесс изделия</h2><p class="caption">Операции и нормативное время на одно изделие</p><ul class="process-tree" id="process-tree"></ul></section></main>
<script>
const colors=['#2563eb','#9333ea','#db2777','#ea580c','#16a34a','#0891b2','#4f46e5'];let current,renderedProcessKey;
const fmtTime=d=>new Date(d).toLocaleString('ru-RU',{day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit'});
const fmtDur=s=>s<60?s+' сек':s<3600?Math.floor(s/60)+' мин '+s%60+' сек':Math.floor(s/3600)+' ч '+Math.floor(s%3600/60)+' мин';
const statusLabels={FEASIBLE:'План найден',OPTIMAL:'Найден оптимальный план',INFEASIBLE:'Нет допустимого плана',MODEL_INVALID:'Ошибка модели',UNKNOWN:'Результат не определён'};
function renderTechProcess(process){
 const key=JSON.stringify(process);if(renderedProcessKey===key)return;
 renderedProcessKey=key;
 document.querySelector('#process-title').textContent=`Техпроцесс №${process.id} · Изделие №${process.productCardId}`;
 const tree=document.querySelector('#process-tree');tree.replaceChildren();
 function branch(parent,title){
  const item=document.createElement('li'),details=document.createElement('details'),summary=document.createElement('summary'),children=document.createElement('ul');
  details.open=true;summary.textContent=title;details.append(summary,children);item.append(details);parent.append(item);return children;
 }
 for(const stage of process.stages){
  const groups=branch(tree,`Этап ${stage.stage} · Групп: ${stage.groups.length}`);
  for(const group of stage.groups){
   const operations=branch(groups,`${group.name} · Операций: ${group.operations.length}`);
   for(const operation of group.operations){
    const item=document.createElement('li'),name=document.createElement('span'),info=document.createElement('span');
    name.className='operation-name';name.textContent=`#${operation.id} · ${operation.name}`;
    info.className='operation-info';info.textContent=`${operation.equipment} (${operation.equipmentCode}) · Норма на изделие: ${fmtDur(operation.normSec)}`;
    item.append(name,info);operations.append(item);
   }
  }
 }
}
function render(data){
 renderTechProcess(data.techProcess);renderJob(data.job);current=data;
 const dept=document.querySelector('#department'),saved=dept.value;dept.replaceChildren();
 for(const name of ['',...data.departments]){const option=document.createElement('option');option.value=name;option.textContent=name||'Все бригады';dept.append(option)}dept.value=saved;
 const scenarios=data.comparisonMode?data.departmentComparison:[{department:'План',status:data.job.status,operations:data.operations,error:data.job.error,end:data.operations.at(-1)?.end,selected:false}];
 const successful=scenarios.filter(s=>s.status==='completed'&&s.operations.length);
 const best=successful.find(s=>s.selected)||[...successful].sort((a,b)=>+new Date(a.end)-+new Date(b.end))[0];
 const origin=+new Date(data.planningOrigin),ends=successful.map(s=>+new Date(s.end));
 const min=origin,max=Math.max(origin+3600000,...ends),span=(max-min)*1.03;
 const cards=document.querySelector('#cards');cards.replaceChildren();
 for(const [caption,value] of [['Рассчитано бригад',`${data.completedDepartments} / ${data.departments.length}`],['Раньше завершает',best?.department||'—'],['Окончание задания',best?.end?fmtTime(best.end):'—'],['Операций в задании',successful[0]?.operations.length??'—']]){
  const card=document.createElement('div'),label=document.createElement('span'),text=document.createElement('b');card.className='card';label.className='caption';label.textContent=caption;text.textContent=value;card.append(label,text);cards.append(card);
 }
 const legend=document.querySelector('#legend');legend.textContent=`Общее начало: ${fmtTime(data.planningOrigin)} · Горизонт: ${data.horizonDays} дн. · Каждая строка — отдельный полный план задания`;
 const scale=document.querySelector('#scale');scale.replaceChildren();
 for(const fraction of [0,.25,.5,.75,1]){const tick=document.createElement('span');tick.className='tick';tick.style.left=fraction*100+'%';tick.textContent=fmtTime(min+span*fraction);scale.append(tick)}
 const rows=document.querySelector('#rows');rows.replaceChildren();
 for(const [index,scenario] of scenarios.entries()){
  if(dept.value&&scenario.department!==dept.value)continue;
  const row=document.createElement('div'),label=document.createElement('div'),name=document.createElement('b'),info=document.createElement('small'),lane=document.createElement('div');
  row.className='row';label.className='label';lane.className='lane';name.textContent=scenario.department+(scenario.selected?' · Раньше всех':'');
  info.textContent=scenario.end?`Конец: ${fmtTime(scenario.end)}`:jobLabels[scenario.status]||scenario.status;
  label.append(name,info);
  for(const operation of scenario.operations){
   const bar=document.createElement('div');bar.className='bar';bar.style.left=(+new Date(operation.start)-min)/span*100+'%';bar.style.width=(+new Date(operation.end)-+new Date(operation.start))/span*100+'%';bar.style.background=colors[index%colors.length];
   bar.textContent=`#${operation.operationId} · изд. ${operation.unit}`;
   bar.title=`${scenario.department} · ${operation.employee} · Изделие ${operation.unit} · Этап ${operation.stage}\n${operation.equipment} · ${fmtTime(operation.start)} — ${fmtTime(operation.end)} (${fmtDur(operation.duration)})`;
   lane.append(bar);
  }
  if(!scenario.operations.length){const note=document.createElement('div');note.className=scenario.status==='failed'?'error':'empty';note.textContent=scenario.error||jobLabels[scenario.status]||scenario.status;lane.append(note)}
  row.append(label,lane);rows.append(row);
 }
 renderComparison(data);
}
function renderComparison(data){
 const panel=document.querySelector('#comparison');panel.hidden=!data.comparisonMode;if(panel.hidden)return;
 const rows=document.querySelector('#comparison-rows');rows.replaceChildren();
 const scenarios=[...data.departmentComparison].sort((a,b)=>a.end&&b.end?+new Date(a.end)-+new Date(b.end):a.end?-1:b.end?1:0);
 for(const scenario of scenarios){
  const row=document.createElement('div'),name=document.createElement('b'),info=document.createElement('div');row.className='comparison-row';name.textContent=scenario.department+(scenario.selected?' · Раньше всех':'');
  info.textContent=scenario.end?`Завершение: ${fmtTime(scenario.end)} · От общего начала: ${fmtDur(scenario.elapsedSec)} · Работы: ${fmtDur(scenario.workSec)} · Операций: ${scenario.operations.length} · ${statusLabels[scenario.solverStatus]||scenario.solverStatus}`:scenario.error||jobLabels[scenario.status]||scenario.status;
  row.append(name,info);rows.append(row);
 }
}
const formEl=document.querySelector('#form'),countEl=document.querySelector('#count'),dateEl=document.querySelector('#date'),departmentEl=document.querySelector('#department');
let eventSource;
const button=formEl.querySelector('button');
const jobLabels={pending:'В очереди',running:'Рассчитывается',completed:'Завершено',failed:'Ошибка'};
function renderJob(job){
 const date=value=>value?new Date(value).toLocaleString('ru-RU'):'—';
 document.querySelector('#job').textContent=`Задание ${job.id} · ${jobLabels[job.status]} · Изделие №${job.productCardId} · Количество: ${job.count} · Дата плана: ${job.planningDay} · Начало: ${date(job.startedAt)} · Конец: ${date(job.finishedAt)} · Время расчёта: ${job.durationSec===null?'—':job.durationSec.toFixed(3)+' сек'}`;
}
function message(text,isError=false){const rows=document.querySelector('#rows');rows.replaceChildren();const node=document.createElement('div');node.className=isError?'error':'empty';node.textContent=text;rows.append(node)}
function applySnapshot(data){
 renderJob(data.job);renderTechProcess(data.techProcess);
 if(data.comparisonMode)render(data);
 if(data.job.status==='completed'){
  render(data);button.disabled=false;if(eventSource)eventSource.close();
 }else if(data.job.status==='failed'){
  if(!data.comparisonMode)message(data.job.error||'Не удалось построить план',true);button.disabled=false;if(eventSource)eventSource.close();
 }else if(!data.comparisonMode){message(data.job.status==='pending'?'Задание в очереди…':'Рассчитываем план…')}
}
function subscribe(url){
 eventSource=new EventSource(url);
 eventSource.addEventListener('job',event=>applySnapshot(JSON.parse(event.data)));
 eventSource.addEventListener('unavailable',()=>message('Связь с Redis прервана. Переподключаемся…'));
 eventSource.onerror=()=>message('Связь с сервером прервана. Переподключаемся…');
}
async function load(e){
 if(e)e.preventDefault();if(eventSource)eventSource.close();button.disabled=true;current=null;
 document.querySelector('#comparison').hidden=true;document.querySelector('#cards').replaceChildren();document.querySelector('#legend').replaceChildren();document.querySelector('#scale').replaceChildren();document.querySelector('#process-tree').replaceChildren();renderedProcessKey=null;document.querySelector('#job').textContent='Создаём задание…';
 message('Отправляем задание в очередь…');
 try{
  const res=await fetch('/api/jobs',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({count:Number(countEl.value),planning_day:dateEl.value,horizon_days:Number(document.querySelector('#horizon').value),compare_departments:true})});
  const data=await res.json();if(!res.ok)throw Error(typeof data.detail==='string'?data.detail:'Проверьте количество изделий и дату планирования');
  renderJob(data.job);message('Задание в очереди…');subscribe(data.eventsUrl);
 }catch(err){message(err.message,true);button.disabled=false}
}
formEl.addEventListener('submit',load);departmentEl.addEventListener('change',()=>current&&render(current));load();
</script></body></html>'''



def main() -> None:
    import uvicorn
    uvicorn.run('planner.web:app', host='0.0.0.0', port=8096)


if __name__ == '__main__':
    main()
