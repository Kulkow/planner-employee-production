"""Statistics UI: duration and worker RSS from archived PostgreSQL jobs."""

STATISTICS_PAGE = r'''<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Статистика расчётов</title>
<style>
*{box-sizing:border-box}body{margin:0;background:#f5f7fb;color:#182230;font:14px system-ui,sans-serif}header{padding:24px 5vw;background:#101828;color:white}h1{margin:12px 0 6px;font-size:26px}header a{color:#cbd5e1}main{padding:24px 5vw}button,select{padding:9px 14px;border:1px solid #cfd6e2;border-radius:7px;background:white;font:inherit}button{cursor:pointer}button:disabled{opacity:.5;cursor:default}.toolbar,.pagination{display:flex;gap:12px;align-items:center;flex-wrap:wrap;margin:18px 0}.cards{display:grid;grid-template-columns:repeat(4,minmax(130px,1fr));gap:12px}.card{padding:18px;background:white;border:1px solid #e5e9f0;border-radius:10px}.card span{color:#667085;font-size:12px}.card b{display:block;font-size:24px;margin-top:8px}.table-wrap{overflow:auto;background:white;border:1px solid #e5e9f0;border-radius:10px}table{border-collapse:collapse;width:100%;min-width:1050px}th,td{text-align:left;padding:14px;border-bottom:1px solid #e5e9f0;vertical-align:top}th{font-size:12px;color:#667085;background:#f9fafb}td small{display:block;color:#667085;margin-top:5px}td a{color:#2563eb}meter{display:block;width:110px;height:7px;margin-top:7px}.note{color:#667085;line-height:1.6;max-width:1000px}.status{padding:3px 8px;border-radius:6px;display:inline-block;background:#ecfdf3;color:#027a48}.status.failed{background:#fef3f2;color:#b42318}#message{padding:16px 0;color:#667085}@media(max-width:700px){.cards{grid-template-columns:repeat(2,1fr)}main,header{padding-left:16px;padding-right:16px}}
</style></head><body>
<header><a href="/">← Планировщик</a><h1>Статистика расчётов</h1><div>Сохранённые задания · PostgreSQL</div></header>
<main><section class="cards" id="cards"></section>
<div class="toolbar"><label>Статус <select id="status"><option value="">Все</option><option value="completed">Завершено</option><option value="failed">Ошибка</option></select></label><button id="reload">Обновить</button></div>
<p class="note">Время расчёта — длительность работы worker над заданием, включая сценарии всех бригад. Срок плана — интервал от первой операции до завершения выбранного плана, включая перерывы. Память — наблюдаемый пик суммарного RSS worker и дочерних процессов с замером каждые 50 мс; прирост считается от начала этого расчёта. Общие страницы памяти могут учитываться несколько раз. Для прежних замеров одного worker указан отдельный тип измерения. Для старых расчётов без замеров показано «нет данных».</p>
<div class="table-wrap"><table><thead><tr><th>Задание / завершено</th><th>Изделие</th><th>Результат</th><th>Расчёт</th><th>Пик RSS</th><th>Прирост RSS</th><th>Срок плана</th><th>Работа по плану</th></tr></thead><tbody id="rows"></tbody></table></div>
<div id="message" role="status"></div><div class="pagination"><button id="prev">← Назад</button><span id="page"></span><button id="next">Далее →</button></div>
</main><script>
const $=id=>document.getElementById(id),limit=25;let offset=0,total=0,loading=false;
const duration=value=>value===null?'нет данных':value<60?value.toFixed(2)+' сек':value<3600?Math.floor(value/60)+' мин '+Math.floor(value%60)+' сек':Math.floor(value/3600)+' ч '+Math.floor(value%3600/60)+' мин';
const memory=value=>value===null?'нет данных':(value/1024/1024).toFixed(1)+' МиБ';
function cell(row,text){const td=document.createElement('td');td.textContent=text;row.append(td);return td}
function small(parent,text){const node=document.createElement('small');node.textContent=text;parent.append(node)}
function gauge(parent,value,max){if(value===null)return;const node=document.createElement('meter');node.min=0;node.max=Math.max(max,1);node.value=value;node.setAttribute('aria-label','Значение относительно максимума на странице');parent.append(node)}
async function load(){
 if(loading)return;loading=true;$('reload').disabled=true;$('prev').disabled=true;$('next').disabled=true;$('status').disabled=true;$('message').textContent='Загружаем сохранённые расчёты…';
 try{
  const query=new URLSearchParams({limit,offset});if($('status').value)query.set('status',$('status').value);
  const response=await fetch('/api/statistics?'+query),data=await response.json();if(!response.ok)throw Error(typeof data.detail==='string'?data.detail:'Не удалось загрузить статистику');
  total=data.summary.total;$('cards').replaceChildren();
  for(const [label,value] of [['Завершено',data.summary.completed],['Ошибок',data.summary.failed],['Средний расчёт',duration(data.summary.average_calculation_seconds)],['Максимум RSS',memory(data.summary.maximum_peak_rss_bytes)]]){
   const card=document.createElement('div'),caption=document.createElement('span'),number=document.createElement('b');card.className='card';caption.textContent=label;number.textContent=value;card.append(caption,number);$('cards').append(card);
  }
  $('rows').replaceChildren();const maxTime=Math.max(...data.items.map(i=>i.calculation_seconds||0),1),maxMemory=Math.max(...data.items.map(i=>i.peak_rss_bytes||0),1);
  for(const item of data.items){
   const row=document.createElement('tr'),job=cell(row,'');const link=document.createElement('a');link.href='/?job='+encodeURIComponent(item.id);link.textContent=item.id.slice(0,8);job.append(link);small(job,new Date(item.finished_at).toLocaleString('ru-RU'));
   const product=cell(row,'№'+item.product_card_id);small(product,item.quantity+' шт.');
   const result=cell(row,''),badge=document.createElement('span');badge.className='status '+item.status;badge.textContent=item.status==='completed'?'Завершено':'Ошибка';result.append(badge);small(result,item.selected_department||'—');small(result,item.department_count+' сценариев · '+item.operation_count+' операций');
   const time=cell(row,duration(item.calculation_seconds));gauge(time,item.calculation_seconds,maxTime);
   const peak=cell(row,memory(item.peak_rss_bytes));gauge(peak,item.peak_rss_bytes,maxMemory);if(item.peak_rss_bytes!==null)small(peak,item.memory_scope==='process_tree'?'Worker + дочерние процессы':'Один worker');
   cell(row,memory(item.memory_growth_bytes));cell(row,duration(item.plan_makespan_seconds));cell(row,duration(item.plan_work_seconds));$('rows').append(row);
  }
  $('message').textContent=total?'':'Пока нет сохранённых расчётов.';$('page').textContent=total?`${offset+1}–${Math.min(offset+limit,total)} из ${total}`:'0 расчётов';
 }catch(error){$('message').textContent=error.message}
 finally{loading=false;$('reload').disabled=false;$('status').disabled=false;$('prev').disabled=offset===0;$('next').disabled=offset+limit>=total}
}
$('status').addEventListener('change',()=>{offset=0;load()});$('reload').addEventListener('click',load);$('prev').addEventListener('click',()=>{offset=Math.max(0,offset-limit);load()});$('next').addEventListener('click',()=>{offset+=limit;load()});load();
</script></body></html>'''
