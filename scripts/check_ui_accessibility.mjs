// Local browser evidence only. Start Chrome with remote-debugging-port=9235
// and a temporary profile. Set AXE_CORE_PATH to an axe-core 4.10.3 installation.
// UI_*_TOKEN values belong in the environment, never command-line arguments.
// This creates/remediates/deletes only its own fresh workbook. It is not a
// substitute for the required human keyboard and screen-reader walkthrough.
import fs from 'node:fs';
const root=process.cwd(), base=process.env.UI_BASE_URL||'http://127.0.0.1:8016';
const roles={owner:process.env.UI_OWNER_TOKEN,reviewer:process.env.UI_REVIEWER_TOKEN,foreign:process.env.UI_FOREIGN_TOKEN};
if(Object.values(roles).some(v=>!v))throw new Error('Set UI_OWNER_TOKEN, UI_REVIEWER_TOKEN and UI_FOREIGN_TOKEN privately.');
const tab=await (await fetch('http://127.0.0.1:9235/json/new?'+encodeURIComponent(base+'/'),{method:'PUT'})).json();
const ws=new WebSocket(tab.webSocketDebuggerUrl); await new Promise((ok,no)=>{ws.onopen=ok;ws.onerror=no;});
let seq=0;const waiting=new Map(),failures=[];
ws.onmessage=e=>{const m=JSON.parse(e.data);if(m.id){const p=waiting.get(m.id);if(!p)return;waiting.delete(m.id);m.error?p.reject(m.error):p.resolve(m.result);}else if(m.method==='Runtime.exceptionThrown')failures.push(m.params.exceptionDetails.text);};
function send(method,params={}){return new Promise((resolve,reject)=>{const id=++seq;waiting.set(id,{resolve,reject});ws.send(JSON.stringify({id,method,params}));});}
async function js(expression){const r=await send('Runtime.evaluate',{expression,awaitPromise:true,returnByValue:true});if(r.exceptionDetails)throw new Error(JSON.stringify(r.exceptionDetails));return r.result.value;}
async function chooseRole(role,workbook){await js("el('token').value="+JSON.stringify(roles[role])+";el('token').dispatchEvent(new Event('input'))"+(workbook?";el('workbook-id').value="+JSON.stringify(workbook):''));}
async function until(expression,ms=30000){const end=Date.now()+ms;while(Date.now()<end){if(await js(expression))return;await new Promise(r=>setTimeout(r,100));}throw new Error('Timed out: '+expression+' '+await js("document.getElementById('error').textContent"));}
async function enter(id){
 await send('Page.bringToFront');
 await js(`(()=>{const element=document.getElementById(${JSON.stringify(id)}),button=element.tagName==='FORM'?element.querySelector('button'):element;button.focus();})()`);
 await send('Input.dispatchKeyEvent',{type:'keyDown',key:'Enter',code:'Enter',text:'\r',unmodifiedText:'\r',windowsVirtualKeyCode:13,nativeVirtualKeyCode:13});
 await send('Input.dispatchKeyEvent',{type:'keyUp',key:'Enter',code:'Enter',windowsVirtualKeyCode:13,nativeVirtualKeyCode:13});
}

const axe=fs.readFileSync(process.env.AXE_CORE_PATH||root+'/data/phase5-implementation/axe.min.js','utf8'),scans=[];
async function scan(name){await js(axe);const result=await js("axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21a','wcag21aa']}}).then(r=>({violations:r.violations.map(v=>({id:v.id,impact:v.impact,nodes:v.nodes.map(n=>n.target)})),passes:r.passes.length}))");scans.push({name,...result});console.log(name,JSON.stringify(result));}
try{
 await send('Runtime.enable');await until("typeof safe==='function'");await scan('initial');
 await chooseRole('owner');
 const dom=await send('DOM.getDocument');const f=await send('DOM.querySelector',{nodeId:dom.root.nodeId,selector:'#file'});
 await send('DOM.setFileInputFiles',{nodeId:f.nodeId,files:[root+'/tests/fixtures/deployment/seeded_all_six.xlsx']});
 await enter('upload-new');await until("!busy && !el('workspace').hidden && editors.length>0",60000);
 const workbook=await js('state.workbookId');await scan('findings-and-history');
 await js("el('schedule-enabled').checked=true;el('interval').value='7';el('deadline').value='2028-01-01'");await enter('save-schedule');await until("!busy && el('schedule-state').textContent.includes('7')");await scan('saved-schedule');
 await enter('delete');await until("!busy && !el('delete-confirmation').hidden");
 if(await js('document.activeElement.id')!=='delete-cancel')throw new Error('Confirmation focus not on Cancel');await scan('delete-confirmation');await enter('delete-cancel');
 if(await js('document.activeElement.id')!=='delete')throw new Error('Cancel did not restore focus');
 await js("editors[0].select.value='DECLINE';editors[0].select.dispatchEvent(new Event('change'))");await enter('submit-decisions');await until("!busy && !el('output').hidden",60000);await scan('corrected-copy');
 await chooseRole('reviewer',workbook);
 await enter('open-workbook');await until("!busy && !el('workspace').hidden");
 if(!await js("el('schedule-form').hidden && el('delete').hidden && el('reaudit').hidden && el('submit-decisions').hidden"))throw new Error('Reviewer sees owner controls');await scan('reviewer');
 await chooseRole('foreign',workbook);await enter('open-workbook');await until("!busy && !!el('error').textContent");await scan('access-denied');
 await chooseRole('owner',workbook);await enter('open-workbook');await until("!busy && !el('workspace').hidden");await enter('delete');await until('!busy');await enter('delete-confirm');await until("!busy && el('workspace').hidden && el('status').textContent.includes('deleted')");await scan('deleted');
 if(failures.length)throw new Error('Browser exceptions: '+JSON.stringify(failures));
 fs.writeFileSync(root+'/data/phase5-implementation/ui-keyboard-scan.json',JSON.stringify({date:new Date().toISOString(),scans,failures},null,2));
 if(scans.some(s=>s.violations.length))process.exitCode=1;
}finally{ws.close();await fetch('http://127.0.0.1:9235/json/close/'+tab.id);}
