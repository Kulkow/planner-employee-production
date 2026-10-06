"""Small dependency-free web UI for the production planner.

Run with ``python -m planner.web`` and open http://localhost:8096.
"""

from __future__ import annotations

from datetime import date
import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from planner.application import ProductionPlanningService
from planner.infrastructure.cp_sat_planner import CpSatProductionPlanner
from planner.infrastructure.test_data import DEFAULT_PLANNING_DAY, generate_test_data


def _make_payload(count: int, planning_day: date) -> dict[str, object]:
    """Calculate a plan and turn domain values into JSON-safe presentation data."""
    if not 1 <= count <= 30:
        raise ValueError("Количество изделий должно быть от 1 до 30")

    data = generate_test_data(planning_day=planning_day)
    request = data.request
    request = request.__class__(
        task=request.task.__class__(
            product_card_id=request.task.product_card_id,
            count=count,
            tech_process=request.task.tech_process,
        ),
        departments=request.departments,
        employees=request.employees,
        efficiencies=request.efficiencies,
        work_schedules=request.work_schedules,
        planning_day=request.planning_day,
    )
    plan = ProductionPlanningService(CpSatProductionPlanner()).create_plan(request)
    operations = [
        {
            "unit": item.unit_number,
            "stage": item.stage,
            "group": item.group_name,
            "operationId": item.operation_id,
            "employeeId": item.employee_id,
            "employee": item.employee_name,
            "department": item.department_name,
            "equipment": item.equipment_code,
            "efficiency": item.efficiency_percent,
            "duration": item.duration_sec,
            "start": item.starts_at.isoformat(),
            "end": item.ends_at.isoformat(),
        }
        for item in plan.operations
    ]
    return {
        "status": plan.status,
        "productCardId": plan.product_card_id,
        "count": plan.count,
        "planningDay": planning_day.isoformat(),
        "makespan": plan.makespan_sec,
        "operations": operations,
        "departments": [item.name for item in request.departments],
        "employeeCount": len(request.employees),
    }


class PlannerHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 - HTTP handler convention
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self._send(HTTPStatus.OK, "text/html; charset=utf-8", PAGE.encode())
            return
        if parsed.path == "/api/plan":
            self._send_plan(parsed.query)
            return
        self._send(HTTPStatus.NOT_FOUND, "text/plain; charset=utf-8", b"Not found")

    def _send_plan(self, query: str) -> None:
        params = parse_qs(query)
        try:
            count = int(params.get("count", ["1"])[0])
            day = date.fromisoformat(params.get("date", [DEFAULT_PLANNING_DAY.isoformat()])[0])
            payload = _make_payload(count, day)
            self._send(HTTPStatus.OK, "application/json; charset=utf-8", json.dumps(payload, ensure_ascii=False).encode())
        except (ValueError, RuntimeError) as error:
            self._send(HTTPStatus.BAD_REQUEST, "application/json; charset=utf-8", json.dumps({"error": str(error)}, ensure_ascii=False).encode())

    def _send(self, status: HTTPStatus, content_type: str, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:  # noqa: A003
        return


PAGE = r'''<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Производственный планировщик</title>
<style>
:root{--ink:#182230;--muted:#667085;--line:#e5e9f0;--paper:#fff;--bg:#f5f7fb;--blue:#2563eb}*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:14px Inter,system-ui,sans-serif}.top{padding:28px 5vw 24px;background:#101828;color:#fff}.top h1{margin:0;font-size:25px}.top p{margin:7px 0 0;color:#cbd5e1}.controls{display:flex;flex-wrap:wrap;gap:14px;align-items:end;padding:18px 5vw;background:var(--paper);border-bottom:1px solid var(--line)}label{display:grid;gap:6px;color:var(--muted);font-weight:600}input,select,button{height:38px;border-radius:8px;border:1px solid #cfd6e2;background:#fff;padding:0 10px;font:inherit;color:var(--ink)}button{background:var(--blue);border:0;color:#fff;font-weight:700;cursor:pointer;padding:0 18px}.wrap{padding:22px 5vw}.cards{display:grid;grid-template-columns:repeat(4,minmax(120px,1fr));gap:12px;margin-bottom:20px}.card{background:#fff;border:1px solid var(--line);border-radius:10px;padding:14px}.card b{display:block;font-size:20px;margin-top:4px}.caption{color:var(--muted);font-size:12px}.chart{background:#fff;border:1px solid var(--line);border-radius:10px;overflow:auto}.axis,.row{min-width:850px;display:grid;grid-template-columns:220px 1fr}.axis{position:sticky;top:0;background:#fff;z-index:2;border-bottom:1px solid var(--line);height:42px}.axis-name{padding:13px 15px;font-weight:700}.scale{position:relative;border-left:1px solid var(--line)}.tick{position:absolute;top:0;height:100%;border-left:1px solid var(--line);padding:12px 0 0 5px;color:var(--muted);font-size:11px}.row{min-height:58px;border-bottom:1px solid var(--line)}.label{padding:10px 15px;line-height:19px}.label small{display:block;color:var(--muted)}.lane{position:relative;border-left:1px solid var(--line);background:repeating-linear-gradient(90deg,#fff 0,#fff calc(25% - 1px),#f4f6f9 calc(25% - 1px),#f4f6f9 25%)}.bar{position:absolute;top:12px;height:34px;border-radius:6px;color:#fff;padding:8px 9px;font-size:11px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;cursor:help;box-shadow:0 2px 4px #10182822}.empty,.error{padding:40px;text-align:center;color:var(--muted)}.legend{display:flex;gap:14px;flex-wrap:wrap;margin:0 0 10px;color:var(--muted)}.dot{display:inline-block;width:10px;height:10px;border-radius:3px;margin-right:4px}@media(max-width:650px){.cards{grid-template-columns:repeat(2,1fr)}.top,.controls,.wrap{padding-left:16px;padding-right:16px}}
</style></head><body>
<header class="top"><h1>Производственный планировщик</h1><p>CP-SAT · минимизация срока заказа · диаграмма Ганта по сотрудникам</p></header>
<form class="controls" id="form"><label>Изделий в заказе<input id="count" type="number" min="1" max="30" value="1"></label><label>Дата планирования<input id="date" type="date" value="2026-10-05"></label><label>Подразделение<select id="department"><option value="">Все подразделения</option></select></label><button>Построить план</button></form>
<main class="wrap"><section class="cards" id="cards"></section><div class="legend" id="legend"></div><section class="chart"><div class="axis"><div class="axis-name">Сотрудник / бригада</div><div class="scale" id="scale"></div></div><div id="rows"><div class="empty">Рассчитываем оптимальный план…</div></div></section></main>
<script>
const colors=['#2563eb','#9333ea','#db2777','#ea580c','#16a34a','#0891b2','#4f46e5'];let current;
const fmtTime=d=>new Date(d).toLocaleTimeString('ru-RU',{hour:'2-digit',minute:'2-digit',second:'2-digit'});
const fmtDur=s=>s<60?s+' сек':Math.floor(s/60)+' мин '+s%60+' сек';
function render(data){current=data;const dept=document.querySelector('#department'), saved=dept.value;dept.innerHTML='<option value="">Все подразделения</option>'+data.departments.map(x=>`<option>${x}</option>`).join('');dept.value=saved;
 const ops=data.operations, starts=ops.map(x=>+new Date(x.start)), ends=ops.map(x=>+new Date(x.end));let min=Math.min(...starts),max=Math.max(...ends);const pad=Math.max((max-min)*.07,1000);min-=pad;max+=pad;const span=max-min;
 document.querySelector('#cards').innerHTML=`<div class="card"><span class="caption">Статус решателя</span><b>${data.status}</b></div><div class="card"><span class="caption">Срок заказа</span><b>${fmtDur(data.makespan)}</b></div><div class="card"><span class="caption">Операций</span><b>${ops.length}</b></div><div class="card"><span class="caption">Ресурсов в модели</span><b>${data.employeeCount} сотрудников</b></div>`;
 const departments=[...new Set(ops.map(x=>x.department))];document.querySelector('#legend').innerHTML=departments.map((x,i)=>`<span><i class="dot" style="background:${colors[i%colors.length]}"></i>${x}</span>`).join('');
 const scale=document.querySelector('#scale');scale.innerHTML=[0,.25,.5,.75,1].map(p=>`<span class="tick" style="left:${p*100}%">${fmtTime(min+span*p)}</span>`).join('');
 const filter=dept.value;const groups={};ops.filter(x=>!filter||x.department===filter).forEach(x=>{const k=x.employeeId;if(!groups[k])groups[k]=[];groups[k].push(x)});const rows=document.querySelector('#rows');const palette=Object.fromEntries(departments.map((x,i)=>[x,colors[i%colors.length]]));
 rows.innerHTML=Object.values(groups).sort((a,b)=>a[0].employee.localeCompare(b[0].employee,'ru')).map(items=>{const x=items[0];return `<div class="row"><div class="label"><b>${x.employee}</b><small>${x.department}</small></div><div class="lane">${items.map(o=>{const left=(+new Date(o.start)-min)/span*100,width=Math.max((+new Date(o.end)-+new Date(o.start))/span*100,1.8);return `<div class="bar" style="left:${left}%;width:${width}%;background:${palette[o.department]}" title="Изделие ${o.unit} · этап ${o.stage} · ${o.group}\nОперация ${o.operationId}; ${o.equipment}; эффективность ${o.efficiency}%\n${fmtTime(o.start)} — ${fmtTime(o.end)} (${o.duration} сек)">#${o.operationId} · изд. ${o.unit}</div>`}).join('')}</div></div>`}).join('')||'<div class="empty">Нет операций для выбранного подразделения</div>';
}
const formEl=document.querySelector('#form'),countEl=document.querySelector('#count'),dateEl=document.querySelector('#date'),departmentEl=document.querySelector('#department');
async function load(e){if(e)e.preventDefault();const rows=document.querySelector('#rows');rows.innerHTML='<div class="empty">Рассчитываем оптимальный план…</div>';try{const q=new URLSearchParams({count:countEl.value,date:dateEl.value});const res=await fetch('/api/plan?'+q);const data=await res.json();if(!res.ok)throw Error(data.error);render(data)}catch(err){rows.innerHTML='<div class="error">'+err.message+'</div>'}}
formEl.addEventListener('submit',load);departmentEl.addEventListener('change',()=>current&&render(current));load();
</script></body></html>'''


def main() -> None:
    server = ThreadingHTTPServer(("0.0.0.0", 8096), PlannerHandler)
    print("Production planner UI: http://localhost:8096")
    server.serve_forever()


if __name__ == "__main__":
    main()
