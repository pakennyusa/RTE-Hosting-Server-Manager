"""Generate a self-contained, clearly labeled UI preview (simulated server data)."""
import base64
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent
static=ROOT/'rte_hosting/static'
css=(static/'styles.css').read_text()
logo='data:image/png;base64,'+base64.b64encode((static/'logo.png').read_bytes()).decode()
bg='data:image/jpeg;base64,'+base64.b64encode((static/'brand-bg.jpg').read_bytes()).decode()
css=css.replace("url('/brand-bg.jpg')", f"url('{bg}')")
js=(static/'app.js').read_text()
js=js.replace("location.port||'80'", "'8080'")
js=js.replace('src="/logo.png"',f'src="{logo}"')
mock=r'''(function(){
const now='2026-10-19T13:00:00+00:00';
let users=[{id:'u1',username:'hostadmin',role:'admin',created_at:now},{id:'u2',username:'captain_red',role:'customer',created_at:now},{id:'u3',username:'tech_operator',role:'staff',created_at:now}];
let servers=[{id:'11111111-1111-1111-1111-111111111111',name:'Trident Community SMP',framework:'Paper',version:'1.21.8',min_ram:2048,max_ram:6144,port:25565,launch_mode:'jar',jar:'paper.jar',java_path:'java',eula_accepted:1,running:true,can_control:true}, {id:'22222222-2222-2222-2222-222222222222',name:'Modded Adventure Hub',framework:'Fabric',version:'1.20.1',min_ram:4096,max_ram:8192,port:25566,launch_mode:'jar',jar:'fabric-server.jar',java_path:'java',eula_accepted:1,running:true,can_control:true},{id:'33333333-3333-3333-3333-333333333333',name:'Escape Rod Creative',framework:'Purpur',version:'1.21.8',min_ram:1024,max_ram:4096,port:25567,launch_mode:'jar',jar:'server.jar',java_path:'java',eula_accepted:0,running:false,can_control:true}];
let assignments=[{user_id:'u2',server_id:servers[0].id,can_control:1,can_console:0,can_files:1},{user_id:'u3',server_id:servers[1].id,can_control:1,can_console:1,can_files:1}];
const urlpath = (v)=>new URL(v,'http://127.0.0.1:8080');
window.fetch=async function(raw,opts={}){
const u=urlpath(raw),path=u.pathname,m=opts.method||'GET';let body={};try{if(opts.body&&typeof opts.body==='string')body=JSON.parse(opts.body)}catch(e){}
const sub=path.split('/'); const sid=sub[3];let payload={ok:true};let status=200;
if(path==='/api/bootstrap/status')payload={needs_setup:false,version:'0.1.0',frameworks:['Vanilla','Paper','Spigot','Purpur','Bukkit','Fabric','Forge','NeoForge','Quilt','Mohist','Arclight','Other']};
else if(path==='/api/me')payload={user:users[0],csrf:'demopreviewtoken',version:'0.1.0'};
else if(path==='/api/servers'&&m==='GET')payload={servers};
else if(path==='/api/servers'&&m==='POST'){const id=(Math.random()+'-demo-server').replace('0.','');servers.unshift({...body,id,running:false,eula_accepted:0,can_control:true});payload={id};}
else if(path==='/api/admin/users'&&m==='GET')payload={users};
else if(path==='/api/admin/users'&&m==='POST'){users.push({...body,id:'u'+(users.length+1),created_at:now});payload={ok:true}}
else if(path==='/api/admin/assignments'&&m==='GET')payload={assignments};
else if(path==='/api/admin/assignments'&&m==='POST'){assignments=assignments.filter(a=>a.user_id!==body.user_id||a.server_id!==body.server_id);assignments.push(body);}
else if(path==='/api/admin/assignments'&&m==='DELETE'){assignments=assignments.filter(a=>a.user_id!==u.searchParams.get('user_id')||a.server_id!==u.searchParams.get('server_id'))}
else if(path==='/api/admin/audit')payload={events:[{created_at:now,actor:'hostadmin',event:'server_created',detail:'Trident Community SMP'},{created_at:now,actor:'hostadmin',event:'assignment_updated',detail:'captain_red → Trident Community SMP'},{created_at:now,actor:'tech_operator',event:'backup_created',detail:'Modded Adventure Hub'}]};
else if(sub.length>=4&&sub[2]==='servers'){
const srv=servers.find(s=>s.id===sid);
if(!srv){payload={error:'Server not found'};status=404;}
else if(path.endsWith('/console'))payload={lines:['[13:47:02] [Server thread/INFO]: Starting Minecraft server on *:'+srv.port,'[13:47:03] [Server thread/INFO]: Preparing spawn area: 100%','[13:47:04] [Server thread/INFO]: Done (5.113s)! For help, type "help"','[13:49:22] [Server thread/INFO]: Player connected to world'],running:srv.running};
else if(path.endsWith('/start'))srv.running=true;
else if(path.endsWith('/stop'))srv.running=false;
else if(path.endsWith('/eula'))srv.eula_accepted=1;
else if(path.endsWith('/files'))payload={path:u.searchParams.get('path')||'',files:[{name:'world',directory:true,size:0,path:'world'},{name:'plugins',directory:true,size:0,path:'plugins'},{name:'server.properties',directory:false,size:2243,path:'server.properties'},{name:'paper.jar',directory:false,size:1965842,path:'paper.jar'}]};
else if(path.endsWith('/text'))payload={content:'motd=Welcome to RTE Hosting!\\nmax-players=20\\nonline-mode=true\\n'};
else if(path.endsWith('/properties'))payload={properties:{motd:'Welcome to RTE Hosting!', 'max-players':'20', 'online-mode':'true',pvp:'true',difficulty:'normal'}};
else if(path.endsWith('/backups')&&m==='GET')payload={backups:[{name:'20261019-130000-a1b2c3.zip',size:53456234}]};
else if(path.endsWith('/backups')&&m==='POST')payload={backup:{name:'20261019-140000-f4f4f4.zip',size:12000000}};
else if(!path.endsWith('/file'))payload={server:srv,permissions:{can_control:1,can_console:1,can_files:1},properties:{}};
}
return {ok:status>=200&&status<300,status,headers:{get:()=> 'application/json'},json:async()=>payload};
}
})();'''
html='''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>RTE Hosting — Interactive UI Concept (Simulated)</title><style>'''+css+'''body::before{content:'UI DEMO · SIMULATED SERVERS';position:fixed;right:10px;bottom:8px;background:#167bc9;color:white;z-index:99;padding:7px 10px;border-radius:8px;font-size:10px;letter-spacing:.05em;pointer-events:none;box-shadow:0 3px 16px #0008;}</style></head><body><div id="app"></div><input type="file" id="filePicker" hidden><script>'''+mock+'</script><script>'+js+'</script></body></html>'
html=html.replace('src="/logo.png"',f'src="{logo}"')
out=ROOT/'RTE_Hosting_UI_Demo.html';out.write_text(html)
print(out,round(out.stat().st_size/1024),'KiB')
