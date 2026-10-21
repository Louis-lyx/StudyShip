const $=s=>document.querySelector(s), $$=s=>[...document.querySelectorAll(s)];
const state={token:localStorage.getItem('studyship_token')||'',user:null,courses:[],course:null,page:'dashboard',quiz:[],quizIndex:0,quizResults:{familiar:0,unfamiliar:0}};
const esc=s=>String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const pct=n=>`${Math.round((Number(n)||0)*100)}%`;
function toast(msg,error=false){const d=document.createElement('div');d.className=`toast ${error?'error':''}`;d.textContent=msg;$('#toast').append(d);setTimeout(()=>d.remove(),3600)}
async function api(path,opt={}){const headers={...(opt.headers||{})};if(state.token)headers.Authorization=`Bearer ${state.token}`;if(opt.body&&! (opt.body instanceof FormData)){headers['Content-Type']='application/json';opt.body=JSON.stringify(opt.body)}const r=await fetch(`/api${path}`,{...opt,headers});if(r.status===401){logout();throw new Error('登录已过期')}const data=await r.json().catch(()=>({}));if(!r.ok)throw new Error(data.detail||`请求失败 ${r.status}`);return data}
function modal(html){$('#modal-body').innerHTML=html;$('#modal').classList.remove('hidden')}
function closeModal(){$('#modal').classList.add('hidden')}
$('#modal-close').onclick=closeModal;$('#modal').onclick=e=>{if(e.target.id==='modal')closeModal()};

let registerMode=false;
$('#auth-switch').onclick=()=>{registerMode=!registerMode;$('#login-form').classList.toggle('hidden',registerMode);$('#register-form').classList.toggle('hidden',!registerMode);$('#auth-title').textContent=registerMode?'创建 StudyShip 账号':'欢迎回来';$('#auth-subtitle').textContent=registerMode?'选择身份并建立本地账号':'登录教师或学生工作台';$('#auth-switch').textContent=registerMode?'已有账号？返回登录':'没有账号？注册'};
$('#login-form').onsubmit=async e=>{e.preventDefault();try{const d=await api('/auth/login',{method:'POST',body:{username:$('#login-user').value,password:$('#login-pass').value}});startSession(d)}catch(x){toast(x.message,true)}};
$('#register-form').onsubmit=async e=>{e.preventDefault();try{const d=await api('/auth/register',{method:'POST',body:{username:$('#reg-user').value,password:$('#reg-pass').value,display_name:$('#reg-name').value,role:$('#reg-role').value,student_no:$('#reg-no').value||null}});startSession(d)}catch(x){toast(x.message,true)}};
function startSession(d){state.token=d.token;state.user=d.user;localStorage.setItem('studyship_token',d.token);boot()}
function logout(){state.token='';state.user=null;localStorage.removeItem('studyship_token');$('#app').classList.add('hidden');$('#auth').classList.remove('hidden')}
$('#logout').onclick=logout;

const teacherNav=[['dashboard','⌂','课程总览'],['knowledge','◇','教材知识库'],['resources','▤','教学资料'],['questionbank','✓','诊断题库'],['graph','⌘','知识关系图'],['students','◎','班级学情'],['course','⚙','课程设置']];
const studentNav=[['dashboard','⌂','学习总览'],['content','▤','课程理论'],['selfresources','⇧','自主学习资料上传'],['mastery','◉','我的掌握状态'],['plan','▦','复习计划'],['graph','⌘','知识地图'],['quiz','✓','诊断测验'],['course','＋','加入课程']];
const courseStorageKey=()=>`studyship_course_${state.user?.id||'guest'}`;
function resetCourseUi(){state.quiz=[];state.quizIndex=0;state.quizResults={correct:0,wrong:0}}
function activateCourse(courseId,rerender=true){const next=state.courses.find(c=>c.id===Number(courseId));if(!next)return;state.course=next;localStorage.setItem(courseStorageKey(),String(next.id));resetCourseUi();renderCourses();if(rerender)render()}
async function boot(){try{if(!state.user)state.user=await api('/auth/me');state.courses=await api('/courses');const saved=Number(localStorage.getItem(courseStorageKey())||localStorage.getItem('studyship_course'));state.course=state.courses.find(c=>c.id===saved)||state.courses[0]||null;$('#auth').classList.add('hidden');$('#app').classList.remove('hidden');$('#user-name').textContent=state.user.display_name;$('#user-role').textContent=state.user.role==='teacher'?'教师账号':'学生账号';$('#avatar').textContent=state.user.display_name.slice(0,1);renderNav();renderCourses();const health=await api('/health');$('#llm-status').textContent=health.llm_configured?'AI 已连接':'本地解析模式';$('#llm-status').className=`status-pill ${health.llm_configured?'ok':'warn'}`;await render()}catch(e){toast(e.message,true);if(!state.user)logout()}}
function renderNav(){const nav=state.user.role==='teacher'?teacherNav:studentNav;$('#nav').innerHTML=nav.map(([id,icon,name])=>`<button data-page="${id}" class="${state.page===id?'active':''}"><span class="nav-icon">${icon}</span><span>${name}</span></button>`).join('');$$('#nav button').forEach(b=>b.onclick=()=>{state.page=b.dataset.page;renderNav();render()})}
function renderCourses(){$('#course-select').innerHTML=state.courses.length?state.courses.map(c=>`<option value="${c.id}" ${state.course?.id===c.id?'selected':''}>${esc(c.name)}</option>`).join(''):'<option>暂无课程</option>';$('#course-select').disabled=!state.courses.length;$('#course-select').onchange=()=>activateCourse($('#course-select').value)}
$('#refresh').onclick=()=>render();
const pageTitles={dashboard:['OVERVIEW','课程总览'],knowledge:['KNOWLEDGE BASE','教材知识库'],resources:['EVIDENCE LAYER','教学资料'],questionbank:['QUESTION BANK','课程诊断题库'],graph:['KNOWLEDGE GRAPH','知识关系图'],students:['CLASS INSIGHT','班级学情'],course:['COURSE','课程设置'],content:['COURSE THEORY','课程理论'],selfresources:['PERSONAL MATERIALS','自主学习资料上传'],mastery:['MASTERY','我的掌握状态'],plan:['ADAPTIVE PLAN','个性化复习计划'],quiz:['DIAGNOSTIC','判断题诊断']};
async function render(){const [k,t]=pageTitles[state.page]||['STUDYSHIP','工作台'];$('#page-kicker').textContent=k;$('#page-title').textContent=t;$('#view').innerHTML='<div class="card"><div class="empty">正在加载…</div></div>';try{if(!state.course&&state.page!=='course'){$('#view').innerHTML='<div class="card"><div class="empty"><b>还没有课程</b>请先创建或加入一门课程。</div></div>';return}const role=state.user.role;const fn=(role==='teacher'?teacherPages:studentPages)[state.page]||(()=>{});await fn()}catch(e){$('#view').innerHTML=`<div class="card"><div class="empty"><b>加载失败</b>${esc(e.message)}</div></div>`;toast(e.message,true)}}

const teacherPages={
dashboard:async()=>{const o=await api(`/courses/${state.course.id}/teacher-overview`);const books=await api(`/courses/${state.course.id}/books`);const resources=await api(`/courses/${state.course.id}/resources`);$('#view').innerHTML=`<section class="hero"><div><h3>${esc(state.course.name)}</h3><p>${esc(state.course.description||'将教材、教学资料和学生学习状态汇聚为一张持续演化的课程知识地图。')}</p></div><button class="btn" id="hero-upload">上传教材目录</button></section><div class="stats"><div class="stat"><small>已审核知识点</small><strong>${o.knowledge_points}</strong><span>个</span></div><div class="stat"><small>课程学生</small><strong>${o.students}</strong><span>人</span></div><div class="stat"><small>班级平均掌握</small><strong>${pct(o.average_mastery)}</strong></div><div class="stat"><small>待审核证据</small><strong>${o.pending_evidence}</strong><span>条</span></div></div><div class="grid-2"><section class="card"><div class="card-head"><h3>薄弱知识点</h3><span class="badge amber">低掌握优先</span></div>${o.weak_points.length?o.weak_points.map(x=>`<div style="margin:14px 0"><div class="meter"><span style="min-width:130px">${esc(x.name)}</span><div class="progress"><span style="width:${pct(x.avg_mastery)}"></span></div><b>${pct(x.avg_mastery)}</b></div></div>`).join(''):'<div class="empty">学生完成诊断后显示班级学情</div>'}</section><section class="card"><div class="card-head"><h3>知识库状态</h3><span class="badge blue">本地保存</span></div><p>课程目录版本：<b>${books[0]?esc(books[0].title):'尚未上传'}</b></p><p>教学资料：<b>${resources.length} 份</b></p><p>课程状态：<b>${state.course.published?'已发布':'草稿'}</b></p><div class="notice">目录决定课程结构；OpenDSA 提供理论正文，PPT、考纲和作业只调整范围与权重。</div></section></div>`;$('#hero-upload').onclick=()=>{state.page='knowledge';renderNav();render()}}
,knowledge:async()=>{const [data,review,theory,templates]=await Promise.all([api(`/courses/${state.course.id}/knowledge`),api(`/courses/${state.course.id}/outline-review`),api('/theory/status'),api('/curriculum-templates')]);if(!review.template){$('#view').innerHTML=`<section class="card base-library-picker"><div class="card-head"><div><h3>选择基础知识库</h3><p class="muted">基础知识库提供成熟概念、理论正文与前置关系；本校教材目录决定本学期实际章节和考试范围。</p></div><span class="badge amber">课程初始化 0/5</span></div><div class="library-choice"><label>基础知识库<select id="template-select">${templates.map(t=>`<option value="${esc(t.code)}">${esc(t.name)} · ${esc(t.version)}</option>`).join('')}</select></label><div id="template-description" class="notice">${templates[0]?esc(templates[0].description||templates[0].source_note):'当前还没有可选基础知识库'}</div><button class="btn primary" id="init-template" ${templates.length?'':'disabled'}>使用所选基础知识库</button></div></section>`;const sel=$('#template-select');if(sel)sel.onchange=()=>{const t=templates.find(x=>x.code===sel.value);$('#template-description').textContent=t?.description||t?.source_note||''};$('#init-template').onclick=initializeCurriculum;return}const latest=review.outlines[0];$('#view').innerHTML=`<div class="grid-2"><section class="card"><div class="card-head"><div><h3>本校教材目录是课程主体</h3><p class="muted">目录决定章节目次、显示顺序和本学期内容</p></div><span class="badge ${theory.ready?'green':'amber'}">OpenDSA ${theory.modules||0} 个理论模块</span></div><div class="notice">流程：上传本校教材目录 → 生成课程层级 → 自动挂接 OpenDSA 理论知识点。目录之外的 OpenDSA 内容留在资源池，不进入学生课程。</div><form id="outline-form" class="upload-box"><label>教材目录名称<input name="title" value="本校数据结构教材目录" required></label><label>上传目录文件（PDF/TXT/Markdown，可选）<input name="file" type="file" accept=".pdf,.txt,.md"></label><label>或直接粘贴目录<textarea name="outline_text" rows="8" placeholder="第一章 绪论&#10;1.1 数据结构的基本概念&#10;1.2 算法和算法分析"></textarea></label><button class="btn primary">按此目录重建课程结构</button></form></section><section class="card"><div class="card-head"><h3>最近一次目录匹配</h3><span class="badge blue">${review.outlines.length} 个版本</span></div>${latest?outlineDiffHtml(latest,review.canonical_topics):'<div class="empty"><b>尚未上传教材目录</b>OpenDSA 理论资源已在资源池中；上传目录后才创建课程知识点。</div>'}</section></div><section class="card"><div class="card-head"><div><h3>按本校章节审核知识库</h3><p class="muted">${data.knowledge_points.length} 个课程知识点 · ${data.relations.length} 条前置关系 · 共 ${review.template.resource_points} 个候选知识点</p></div><div class="toolbar"><button class="btn ghost" id="approve-all" ${data.knowledge_points.length?'':'disabled'}>全部通过</button><button class="btn primary" id="publish" ${data.knowledge_points.length?'':'disabled'}>发布课程</button></div></div>${chapterReviewHtml(review.chapters)}</section>`;$('#outline-form').onsubmit=uploadOutline;$('#approve-all').onclick=async()=>{await api(`/courses/${state.course.id}/knowledge/approve-all`,{method:'POST'});toast('全部课程知识点和前置关系已通过');render()};$('#publish').onclick=async()=>{await api(`/courses/${state.course.id}/publish`,{method:'POST'});state.course.published=true;toast('课程已发布');render()};$$('[data-topic-approve]').forEach(b=>b.onclick=async()=>{const d=await api(`/topics/${b.dataset.topicApprove}/approve`,{method:'POST'});toast(`本章已通过 ${d.knowledge_points} 个知识点`);render()});$$('[data-kp-toggle]').forEach(b=>b.onclick=async()=>{await api(`/knowledge/${b.dataset.kpToggle}`,{method:'PATCH',body:{approved:b.dataset.next==='true'}});render()});$$('[data-kp-edit]').forEach(b=>b.onclick=()=>openKpEdit(data.knowledge_points.find(k=>k.id===Number(b.dataset.kpEdit))));$$('[data-theory]').forEach(b=>b.onclick=()=>openTheory(Number(b.dataset.theory)));$$('[data-coverage]').forEach(s=>s.onchange=async()=>{await api(`/knowledge/${s.dataset.coverage}/coverage`,{method:'PATCH',body:{coverage_status:s.value}});toast('课程范围已更新')});$$('[data-outline-entry]').forEach(s=>s.onchange=async()=>{await api(`/outline-entries/${s.dataset.outlineEntry}`,{method:'PATCH',body:{matched_topic_key:s.value,review_status:s.value?'approved':'unmatched'}});toast('目录映射与课程知识点已更新');render()});const reparse=$('[data-reparse]');if(reparse)reparse.onclick=async()=>{reparse.disabled=true;reparse.textContent='正在重新解析…';try{const d=await api(`/outlines/${reparse.dataset.reparse}/reparse`,{method:'POST'});toast(`重新识别 ${d.entries} 条目录，其中 ${d.matched} 条已匹配`);render()}catch(e){toast(e.message,true);reparse.disabled=false;reparse.textContent='重新解析已保存目录'}}}
,resources:async()=>{const [rs,ev]=await Promise.all([api(`/courses/${state.course.id}/resources`),api(`/courses/${state.course.id}/evidence?status=pending`)]);$('#view').innerHTML=`<div class="notice">AI 只从资料中提取概念并挂接到已有课程知识点；课程章节、知识点和关系框架保持不变。</div><div class="grid-2"><section class="card"><div class="card-head"><h3>上传教学资料</h3><span class="badge blue">PDF / TXT / MD</span></div><form id="resource-form" class="upload-box"><div class="form-row"><label>资料名称<input name="title" required></label><label>资料类型<select name="resource_type"><option value="syllabus">考试大纲</option><option value="ppt">教学PPT</option><option value="assignment">作业</option><option value="exam">往年试题</option><option value="note">补充资料</option></select></label></div><label>文件<input name="file" type="file" accept=".pdf,.txt,.md" required></label><button class="btn primary">AI解析并匹配现有知识点</button></form></section><section class="card"><div class="card-head"><h3>已上传教学资料</h3><span class="badge green">${rs.length} 份</span></div>${rs.length?rs.map(r=>`<div class="resource-row"><div><b>${esc(r.title)}</b><div class="meta"><span class="badge blue">${typeName(r.type)}</span><span>${r.page_count} 页</span><span>${esc(r.message)}</span></div></div><button class="btn danger" data-resource-delete="${r.id}">删除</button></div>`).join(''):'<div class="empty">暂无教学资料</div>'}</section></div><section class="card"><div class="card-head"><div><h3>知识点匹配审核</h3><p class="muted">AI 提取资料中的细分概念，再挂到既有知识点；接受后只更新教学权重。</p></div><div class="toolbar"><span class="badge amber">${ev.length} 条</span>${ev.length?'<button class="btn primary" id="evidence-all">全部接受</button>':''}</div></div>${ev.length?ev.map(e=>`<article class="evidence-card"><div class="concept-map"><div><small>资料概念</small><b>${esc(e.concept_name||e.kp_name)}</b><p>${esc(e.concept_summary||'')}</p></div><span>→</span><div><small>课程框架位置</small><b>${esc(e.kp_name)}</b><p>${esc(e.topic_name||'课程内容')}</p></div></div><div class="meta"><span>${esc(e.resource)} · 第 ${e.page} 页</span><span class="badge blue">${effectName(e.effect_type)} → ${pct(e.suggested_value)}</span><span>置信度 ${pct(e.confidence)}</span><span>${e.match_method==='ai'?'AI匹配':'本地匹配'}</span></div><blockquote>${esc(e.excerpt)}</blockquote><div class="actions"><button class="btn primary" data-evidence="${e.id}" data-ok="true">接受</button><button class="btn danger" data-evidence="${e.id}" data-ok="false">驳回</button></div></article>`).join(''):'<div class="empty"><b>审核队列为空</b>上传资料后，匹配结果会在这里出现</div>'}</section>`;$('#resource-form').onsubmit=uploadResource;bindResourceDeletes();$$('[data-evidence]').forEach(b=>b.onclick=async()=>{await api(`/evidence/${b.dataset.evidence}/review?approve=${b.dataset.ok}`,{method:'POST'});toast(b.dataset.ok==='true'?'证据已应用':'证据已驳回');render()});const all=$('#evidence-all');if(all)all.onclick=async()=>{await api(`/courses/${state.course.id}/evidence/review-all?approve=true`,{method:'POST'});toast('全部证据已应用');render()}}
,questionbank:async()=>{const d=await api(`/courses/${state.course.id}/question-bank`);const groups={};d.questions.forEach(q=>(groups[q.chapter]??=[]).push(q));const sc=d.source_counts||{};$('#view').innerHTML=`<section class="card"><div class="card-head"><div><h3>成熟题库知识点判断题</h3><p class="muted">从 OpenDSA 与严蔚敏配套原题中逐题挖掘原子知识，并映射到本校课程章节。</p></div><button class="btn primary" id="generate-bank">${d.count?'重新提炼并映射':'导入全部判断题'}</button></div><div class="stats bank-stats"><div class="stat"><small>已映射判断题</small><strong>${d.count}</strong><span>条</span></div><div class="stat"><small>覆盖章节</small><strong>${d.chapters}</strong><span>章</span></div><div class="stat"><small>OpenDSA</small><strong>${sc.opendsa||0}</strong><span>条</span></div><div class="stat"><small>严蔚敏配套习题</small><strong>${sc.yanweimin||0}</strong><span>条</span></div></div><div class="notice">每道原题对应一道基础知识判断题。错误命题会替换一个关键事实，学生作答后按正误更新掌握度。</div>${Object.entries(groups).map(([chapter,qs],i)=>`<details class="chapter-review" ${i===0?'open':''}><summary><div><b>${esc(chapter)}</b><small>${qs.length} 道判断题</small></div><span class="badge blue">知识点提炼</span></summary>${qs.map(q=>`<div class="bank-row"><div><b>${esc(q.statement)}</b><small>${esc(q.explanation||q.rationale||'判断知识结论')}</small></div><div class="meta"><span class="badge ${q.correct_answer?'green':'amber'}">答案：${q.correct_answer?'正确':'错误'}</span><span class="badge ${q.source==='opendsa'?'blue':'green'}">${q.source==='opendsa'?'OpenDSA':q.source==='yanweimin'?'严蔚敏题集':'本地'}</span><span>重点 ${pct(q.focus_score)}</span><button class="btn danger" data-bank-delete="${q.id}">删除</button></div></div>`).join('')}</details>`).join('')||'<div class="empty"><b>题库等待导入</b>点击上方按钮提炼两个来源的全部题目，并映射到课程知识点。</div>'}</section>`;$('#generate-bank').onclick=async e=>{const b=e.currentTarget;b.disabled=true;b.textContent='正在导入并映射判断题…';try{const x=await api(`/courses/${state.course.id}/question-bank/generate`,{method:'POST'});toast(`${x.message}，共 ${x.count} 条`);render()}catch(x){toast(x.message,true);b.disabled=false;b.textContent='重新提炼并映射'}};$$('[data-bank-delete]').forEach(b=>b.onclick=async()=>{await api(`/question-bank/${b.dataset.bankDelete}`,{method:'DELETE'});toast('判断题已删除');render()})}
,graph:async()=>{const [d,review]=await Promise.all([api(`/courses/${state.course.id}/knowledge`),api(`/courses/${state.course.id}/outline-review`).catch(()=>({chapters:[]}))]);kgSetCtx(d,null,kgAlignMap(review),'teacher');$('#view').innerHTML=`<section class="card"><div class="card-head"><div><h3>课程层级知识图</h3></div><div class="toolbar">${kgToolbarHtml('teacher')}</div></div>${kgLegendHtml('teacher')}<div class="canvas" id="graph-canvas">${kgRender()}</div><div id="graph-detail">${kgDetailHtml()}</div></section>${insightsHtml(d,'teacher')}`;kgBind()}
,students:async()=>{const o=await api(`/courses/${state.course.id}/teacher-overview`);$('#view').innerHTML=`<div class="stats"><div class="stat"><small>加入课程</small><strong>${o.students}</strong><span>人</span></div><div class="stat"><small>班级平均掌握</small><strong>${pct(o.average_mastery)}</strong></div><div class="stat"><small>知识点</small><strong>${o.knowledge_points}</strong><span>个</span></div><div class="stat"><small>待审核资料证据</small><strong>${o.pending_evidence}</strong><span>条</span></div></div><section class="card"><div class="card-head"><h3>全班薄弱知识点</h3><span class="badge amber">掌握度由低到高</span></div>${o.weak_points.length?`<div class="table-wrap"><table><thead><tr><th>知识点</th><th>覆盖学生</th><th>平均掌握度</th><th>风险</th></tr></thead><tbody>${o.weak_points.map(x=>`<tr><td><b>${esc(x.name)}</b></td><td>${x.student_count}</td><td><div class="meter"><div class="progress"><span style="width:${pct(x.avg_mastery)}"></span></div><b>${pct(x.avg_mastery)}</b></div></td><td><span class="badge ${x.avg_mastery<.4?'red':x.avg_mastery<.7?'amber':'green'}">${x.avg_mastery<.4?'需干预':x.avg_mastery<.7?'需巩固':'稳定'}</span></td></tr>`).join('')}</tbody></table></div>`:'<div class="empty"><b>等待学生学习数据</b>学生完成诊断或测验后显示</div>'}</section>`}
,course:async()=>{const courses=state.courses;const steps=c=>[!!c.template_code,c.outline_count>0,c.approved_points>0,c.question_count>0,c.published];$('#view').innerHTML=`<div class="grid-2 course-manage-grid"><section class="card"><div class="card-head"><div><h3>新建课程</h3><p class="muted">每门课程拥有独立的目录、知识库、题库和学生学习数据。</p></div><span class="badge blue">${courses.length} 门课程</span></div><form id="course-form"><label>课程名称<input name="name" required placeholder="例如：操作系统"></label><div class="form-row"><label>课程代码（可选）<input name="code" maxlength="40" pattern="[A-Za-z0-9_-]{2,40}" placeholder="留空自动产生"></label><label>学年<input name="academic_year" value="2026-2027"></label></div><label>课程简介<textarea name="description" rows="4" placeholder="课程对象、教材版本或教学目标"></textarea></label><button class="btn primary">创建并配置课程</button></form></section><section class="card"><div class="card-head"><div><h3>当前课程</h3><p class="muted">${state.course?esc(state.course.code):'等待创建'}</p></div>${state.course?`<button class="btn ghost" data-course-edit="${state.course.id}">编辑课程</button>`:''}</div>${state.course?`<div class="current-course-panel"><b>${esc(state.course.name)}</b><p>${esc(state.course.description||'尚未填写课程简介')}</p><div class="meta"><span class="badge ${state.course.published?'green':'amber'}">${state.course.published?'已发布':'配置中'}</span><span>${esc(state.course.academic_year)}</span><span>${state.course.knowledge_points||0} 个知识点</span><span>${state.course.students||0} 名学生</span></div></div>`:'<div class="empty"><b>建立第一门课程</b>创建后选择基础知识库并上传本校教材目录。</div>'}</section></div><section class="card"><div class="card-head"><div><h3>我的课程</h3><p class="muted">进入、编辑或通过左侧选择框自由切换。</p></div><span class="badge blue">${courses.length} 门</span></div><div class="course-card-grid">${courses.map(c=>{const ss=steps(c),done=ss.filter(Boolean).length;return`<article class="course-manage-card ${state.course?.id===c.id?'active':''}"><div class="course-card-head"><div><small>${esc(c.code)}</small><h4>${esc(c.name)}</h4></div><span class="badge ${c.published?'green':'amber'}">${c.published?'已发布':'配置中'}</span></div><p>${esc(c.description||'尚未填写课程简介')}</p><div class="course-metrics"><span><b>${c.knowledge_points||0}</b> 知识点</span><span><b>${c.question_count||0}</b> 判断题</span><span><b>${c.students||0}</b> 学生</span></div><div class="setup-progress"><div><span>课程初始化 ${done}/5</span><small>${c.template_name?esc(c.template_name):'待选择基础知识库'}</small></div><div class="progress"><span style="width:${done*20}%"></span></div></div><div class="toolbar"><button class="btn primary" data-course-open="${c.id}">${state.course?.id===c.id?'当前课程':'进入课程'}</button><button class="btn ghost" data-course-edit="${c.id}">编辑</button></div></article>`}).join('')||'<div class="empty"><b>课程列表为空</b>使用上方表单创建课程。</div>'}</div></section>`;$('#course-form').onsubmit=async e=>{e.preventDefault();const body=Object.fromEntries(new FormData(e.target));body.code=(body.code||'').trim();try{const created=await api('/courses',{method:'POST',body});state.courses=await api('/courses');state.course=state.courses.find(c=>c.id===created.id);localStorage.setItem(courseStorageKey(),String(created.id));resetCourseUi();renderCourses();state.page='knowledge';renderNav();toast('课程已创建，请选择基础知识库');render()}catch(x){toast(x.message,true)}};$$('[data-course-open]').forEach(b=>b.onclick=()=>activateCourse(b.dataset.courseOpen));$$('[data-course-edit]').forEach(b=>b.onclick=()=>openCourseEdit(state.courses.find(c=>c.id===Number(b.dataset.courseEdit))))}
};

const studentPages={
dashboard:async()=>{const [states,plan]=await Promise.all([api(`/courses/${state.course.id}/states`),api(`/courses/${state.course.id}/plans/current`)]);const avg=states.length?states.reduce((a,b)=>a+b.mastery,0)/states.length:0;const weak=[...states].sort((a,b)=>a.mastery-b.mastery).slice(0,5);const done=plan?plan.items.filter(x=>x.completed).length:0;$('#view').innerHTML=`<section class="hero"><div><h3>${esc(state.course.name)}</h3><p>知识库已由教师整理。完成诊断、设定考试时间，StudyShip 会把考纲重点、个人薄弱和遗忘风险转换成每天的行动。</p></div><button class="btn" id="start-plan">${plan?'查看计划':'生成计划'}</button></section><div class="stats"><div class="stat"><small>平均掌握度</small><strong>${pct(avg)}</strong></div><div class="stat"><small>知识点</small><strong>${states.length}</strong><span>个</span></div><div class="stat"><small>计划完成</small><strong>${plan?`${done}/${plan.items.length}`:'—'}</strong></div><div class="stat"><small>距离考试</small><strong>${plan?daysTo(plan.exam_date):'—'}</strong><span>${plan?'天':''}</span></div></div><div class="grid-2"><section class="card"><div class="card-head"><h3>当前薄弱点</h3><span class="badge amber">优先关注</span></div>${weak.map(x=>`<div style="margin:14px 0"><div class="meter"><span style="min-width:120px">${esc(x.name)}</span><div class="progress"><span style="width:${pct(x.mastery)}"></span></div><b>${pct(x.mastery)}</b></div></div>`).join('')||'<div class="empty">暂无知识点</div>'}</section><section class="card"><div class="card-head"><h3>今日建议</h3><span class="badge green">可执行</span></div>${plan?renderToday(plan):'<div class="empty"><b>生成第一份计划</b>先完成掌握度诊断，再设置考试日期与每日时间。</div>'}</section></div>`;$('#start-plan').onclick=()=>{state.page='plan';renderNav();render()}}
,content:async()=>{const d=await api(`/courses/${state.course.id}/knowledge`);const byTopic=Object.fromEntries(d.topics.map(t=>[t.id,t]));$('#view').innerHTML=`<section class="card"><div class="card-head"><div><h3>课程理论知识</h3><p class="muted">章节目次来自本校教材目录；OpenDSA 正文、教师教学资料和你的个人资料都汇入对应知识点。</p></div><span class="badge blue">${d.knowledge_points.reduce((n,k)=>n+(k.material_concepts||0),0)} 条资料补充</span></div>${d.knowledge_points.length?d.knowledge_points.map(k=>`<article class="evidence-card"><div><b>${esc(k.name)}</b><p>${esc(k.summary)}</p><div class="meta"><span>${esc(byTopic[k.topic_id]?.title||'课程内容')}</span><span>${k.theory_modules} 个理论模块</span>${k.material_concepts?`<span class="badge green">${k.material_concepts} 条资料概念</span>`:''}</div></div><button class="btn primary" data-theory="${k.id}" ${k.theory_modules||k.material_concepts?'':'disabled'}>阅读知识内容</button></article>`).join(''):'<div class="empty">教师尚未发布目录知识点</div>'}</section>`;$$('[data-theory]').forEach(b=>b.onclick=()=>openTheory(Number(b.dataset.theory)))},selfresources:async()=>{const [rs,ev]=await Promise.all([api(`/courses/${state.course.id}/resources`),api(`/courses/${state.course.id}/personal-evidence`)]);$('#view').innerHTML=`<div class="notice">上传个人笔记、参考章节或练习资料后，AI 会提取细分概念并挂到已有课程板块。结果仅属于当前账号，课程公共知识库框架保持不变。</div><div class="grid-2"><section class="card"><div class="card-head"><h3>自主学习资料上传</h3><span class="badge blue">PDF / TXT / MD</span></div><form id="resource-form" class="upload-box"><div class="form-row"><label>资料名称<input name="title" required placeholder="例如：链表复习笔记"></label><label>资料类型<select name="resource_type"><option value="self_study">自主学习资料</option><option value="book">参考书章节</option><option value="article">课程文章</option><option value="exercise">练习资料</option><option value="note">个人笔记</option></select></label></div><label>文件<input name="file" type="file" accept=".pdf,.txt,.md" required></label><button class="btn primary">AI解析并归入课程知识点</button></form></section><section class="card"><div class="card-head"><h3>我的学习资料</h3><span class="badge green">${rs.length} 份</span></div>${rs.length?rs.map(r=>`<div class="resource-row"><div><b>${esc(r.title)}</b><div class="meta"><span class="badge blue">${typeName(r.type)}</span><span>${r.page_count} 页</span><span>${esc(r.message)}</span></div></div><button class="btn danger" data-resource-delete="${r.id}">删除</button></div>`).join(''):'<div class="empty"><b>还没有个人资料</b>上传后自动形成个人知识点补充层。</div>'}</section></div><section class="card"><div class="card-head"><div><h3>我的知识点补充</h3><p class="muted">左侧是资料中提取的概念，右侧是它在课程固定框架中的位置。</p></div><span class="badge blue">${ev.length} 条映射</span></div>${ev.length?ev.map(e=>`<article class="evidence-card"><div class="concept-map"><div><small>资料概念</small><b>${esc(e.concept_name)}</b><p>${esc(e.concept_summary||'')}</p></div><span>→</span><div><small>归入课程知识点</small><b>${esc(e.kp_name)}</b><p>${esc(e.topic_name||'课程内容')}</p></div></div><div class="meta"><span>${esc(e.resource)} · 第 ${e.page} 页</span><span>置信度 ${pct(e.confidence)}</span><span class="badge green">${e.match_method==='ai'?'AI已匹配':'本地已匹配'}</span></div><blockquote>${esc(e.excerpt)}</blockquote></article>`).join(''):'<div class="empty"><b>等待资料解析</b>成功匹配的个人知识点会显示在这里。</div>'}</section>`;$('#resource-form').onsubmit=uploadResource;bindResourceDeletes()},mastery:async()=>{const xs=await api(`/courses/${state.course.id}/states`);$('#view').innerHTML=`<section class="card"><div class="card-head"><div><h3>初始掌握度诊断</h3><p class="muted">请根据当前实际情况自评；后续测验会自动校正。</p></div><span class="badge blue">${xs.length} 项</span></div><div class="table-wrap"><table><thead><tr><th>知识点</th><th>掌握程度</th><th>记忆保持</th><th>测验次数</th></tr></thead><tbody>${xs.map(x=>`<tr><td><b>${esc(x.name)}</b></td><td><div class="meter"><input type="range" min="0" max="100" value="${Math.round(x.mastery*100)}" data-state="${x.kp_id}"><b id="sv-${x.kp_id}">${pct(x.mastery)}</b></div></td><td>${pct(x.retention)}</td><td>${x.review_count}</td></tr>`).join('')}</tbody></table></div></section>`;$$('[data-state]').forEach(s=>{s.oninput=()=>{$(`#sv-${s.dataset.state}`).textContent=s.value+'%'};s.onchange=async()=>{await api(`/states/${s.dataset.state}`,{method:'PUT',body:{mastery:Number(s.value)/100}});toast('掌握度已更新')}})}
,plan:async()=>{const plan=await api(`/courses/${state.course.id}/plans/current`);$('#view').innerHTML=`<div class="grid-2"><section class="card"><div class="card-head"><h3>计划参数</h3><span class="badge blue">重新生成会保留学习记录</span></div><form id="plan-form"><label>考试日期<input name="exam_date" type="date" min="${futureDate(0)}" value="${plan?.exam_date||futureDate(30)}" required></label><label>每天可学习分钟<input name="daily_minutes" type="number" min="15" max="720" value="${plan?.daily_minutes||90}" required></label><button class="btn primary">生成个性化计划</button></form></section><section class="card"><h3>计划原则</h3><p class="muted">考纲 50% · 掌握状态 30% · 遗忘风险 20%</p><p class="muted">每日安排按考试分值优先，在剩余复习时间内覆盖更多、更重要的知识点。</p><div class="notice">计划只使用教师审核过的知识点和资料证据，并遵守批准的前置关系。</div></section></div>${plan?.overloaded?`<div class="notice" style="margin-bottom:18px">复习时间不足，已自动压缩各知识点时长并均匀分布到每日，优先保留考纲高分内容；建议增加每日时间或延后考试日期。</div>`:''}<section class="card"><div class="card-head"><h3>每日安排</h3><span class="badge green">${plan?plan.items.length:0} 个任务</span></div>${plan?renderPlan(plan):'<div class="empty"><b>暂无学习计划</b>填写上方参数后生成</div>'}</section>`;$('#plan-form').onsubmit=async e=>{e.preventDefault();const x=Object.fromEntries(new FormData(e.target));x.daily_minutes=Number(x.daily_minutes);try{await api(`/courses/${state.course.id}/plans`,{method:'POST',body:x});toast('计划已生成');render()}catch(err){toast(err.message,true)}};$$('[data-plan-item]').forEach(x=>x.onchange=async()=>{await api(`/plan-items/${x.dataset.planItem}/complete`,{method:'POST'});render()})}
,graph:async()=>{const [d,states,review]=await Promise.all([api(`/courses/${state.course.id}/knowledge`),api(`/courses/${state.course.id}/states`),api(`/courses/${state.course.id}/outline-review`).catch(()=>({chapters:[]}))]);kgSetCtx(d,states,kgAlignMap(review),'student');$('#view').innerHTML=`<section class="card"><div class="card-head"><div><h3>课程层级知识图</h3></div><div class="toolbar">${kgToolbarHtml('student')}</div></div>${kgLegendHtml('student')}<div class="canvas" id="graph-canvas">${kgRender()}</div><div id="graph-detail">${kgDetailHtml()}</div></section>${kgMatrixHtml(d,states)}${insightsHtml(d,'student')}`;kgBind()}
,quiz:async()=>{state.quiz=await api(`/courses/${state.course.id}/quiz?count=8`);state.quizIndex=0;state.quizResults={correct:0,wrong:0};renderQuiz()}
,course:async()=>{const avail=await api('/courses/available');$('#view').innerHTML=`<section class="card"><div class="card-head"><div><h3>可加入课程</h3><p class="muted">课程由教师发布，教材知识库由全体同学共享。</p></div><span class="badge blue">${avail.length} 门</span></div>${avail.length?avail.map(c=>`<article class="evidence-card"><b>${esc(c.name)}</b><p>${esc(c.description)}</p><div class="meta"><span>课程代码 ${esc(c.code)}</span><button class="btn primary" data-enroll="${c.id}">加入课程</button></div></article>`).join(''):'<div class="empty"><b>暂无新课程</b>你已经加入所有已发布课程</div>'}</section>`;$$('[data-enroll]').forEach(b=>b.onclick=async()=>{await api(`/courses/${b.dataset.enroll}/enroll`,{method:'POST'});toast('已加入课程');state.courses=await api('/courses');activateCourse(Number(b.dataset.enroll))})}
};

function coverageName(x){return({course:'课程内容',exam:'考试重点',prerequisite:'前置补充',supplemental:'课件补充',excluded:'本学期排除',resource_only:'仅资源池'})[x]||x}
function chapterReviewHtml(chapters){return chapters.length?chapters.map((chapter,index)=>{const points=chapter.sections.flatMap(s=>s.points),done=points.filter(p=>p.approved).length;return`<details class="chapter-review" ${index===0?'open':''}><summary><div><b>${esc(chapter.title)}</b><small>${done}/${points.length} 已审核</small></div><div class="toolbar"><span class="badge ${done===points.length&&points.length?'green':'amber'}">${points.length} 个课程知识点</span>${chapter.topic_id?`<button type="button" class="btn ghost" data-topic-approve="${chapter.topic_id}" onclick="event.preventDefault()">整章通过</button>`:''}</div></summary>${chapter.sections.map(section=>`<div class="section-review"><div class="section-title"><b>${esc(section.title)}</b><span>${section.points.length} 项</span></div>${section.points.length?section.points.map(k=>`<div class="kp-review-row"><div><b>${esc(k.name)}</b><small>${esc(k.summary)}</small></div><span class="difficulty">${'●'.repeat(k.difficulty)}${'○'.repeat(5-k.difficulty)}</span><span>${k.estimated_minutes} 分钟</span><select data-coverage="${k.id}" title="课程范围"><option value="course" ${k.coverage_status==='course'?'selected':''}>课程内容</option><option value="exam" ${k.coverage_status==='exam'?'selected':''}>考试重点</option><option value="prerequisite" ${k.coverage_status==='prerequisite'?'selected':''}>前置补充</option><option value="supplemental" ${k.coverage_status==='supplemental'?'selected':''}>课件补充</option><option value="excluded" ${k.coverage_status==='excluded'?'selected':''}>本学期排除</option></select><span class="badge ${k.approved?'green':'amber'}">${k.approved?'已通过':'待审核'}</span><div class="toolbar">${k.theory_modules?`<button class="btn ghost" data-theory="${k.id}">理论正文 ${k.theory_modules}</button>`:'<span class="badge amber">待补正文</span>'}<button class="btn ghost" data-kp-edit="${k.id}">编辑</button><button class="btn ${k.approved?'danger':'primary'}" data-kp-toggle="${k.id}" data-next="${!k.approved}">${k.approved?'撤回':'通过'}</button></div></div>`).join(''):'<div class="empty compact">本节尚未挂接理论知识点</div>'}</div>`).join('')}</details>`}).join(''):'<div class="empty"><b>等待本校教材目录</b>上传目录后，系统按目录建立章节目次并挂接 OpenDSA 理论知识点。</div>'}
function outlineDiffHtml(outline,topics){const options=(value)=>`<option value="">未匹配</option>${topics.map(t=>`<option value="${t.key}" ${value===t.key?'selected':''}>${esc('　'.repeat(Math.max(0,t.level-1))+t.title)}</option>`).join('')}`;return`<div class="card-head"><p class="muted">${esc(outline.message)}</p><button class="btn ghost" data-reparse="${outline.id}">重新解析已保存目录</button></div><div class="outline-list">${outline.entries.map(e=>`<div class="outline-row level-${e.level}"><span>${esc(e.title)}</span><select data-outline-entry="${e.id}">${options(e.matched_topic_key)}</select><span class="badge ${e.matched_topic_key?'green':'amber'}">${e.matched_topic_key?pct(e.confidence):'本地内容'}</span></div>`).join('')}</div>`}
async function initializeCurriculum(){const sel=$('#template-select'),templateCode=sel?.value;if(!templateCode){toast('请选择基础知识库',true);return}const label=sel.options[sel.selectedIndex]?.textContent||templateCode;if(!confirm(`使用“${label}”初始化当前课程？`))return;const btn=$('#init-template');btn.disabled=true;btn.textContent='正在载入基础知识库…';try{const d=await api(`/courses/${state.course.id}/curriculum-template?template_code=${encodeURIComponent(templateCode)}`,{method:'POST'});state.courses=await api('/courses');state.course=state.courses.find(c=>c.id===state.course.id);renderCourses();toast(d.already_applied?'基础知识库已关联':`基础知识库已就绪，包含 ${d.resource_points||0} 个候选知识点`);render()}catch(x){toast(x.message,true);btn.disabled=false;btn.textContent='使用所选基础知识库'}}
async function uploadOutline(e){e.preventDefault();const fd=new FormData(e.target);if(!fd.get('outline_text')?.trim()&&!fd.get('file')?.name){toast('请选择目录文件或粘贴目录文本',true);return}const btn=e.target.querySelector('button');btn.disabled=true;btn.textContent='正在匹配目录…';try{const d=await api(`/courses/${state.course.id}/outlines`,{method:'POST',body:fd});toast(`目录匹配完成：${d.matched}/${d.entries} 条`);render()}catch(x){toast(x.message,true);btn.disabled=false;btn.textContent='按此目录重建课程结构'}}
function kpTable(xs,teacher){return xs.length?`<div class="table-wrap"><table><thead><tr><th>知识点</th><th>来源</th><th>难度</th><th>预计时长</th><th>考试权重</th><th>状态</th>${teacher?'<th>操作</th>':''}</tr></thead><tbody>${xs.map(k=>`<tr><td><b>${esc(k.name)}</b><br><small class="muted">${esc((k.summary||'').slice(0,90))}</small></td><td>${k.page_start?`第 ${k.page_start}-${k.page_end} 页`:'基准模板'}<br><small>置信度 ${pct(k.confidence)}</small></td><td>${'●'.repeat(k.difficulty)}${'○'.repeat(5-k.difficulty)}</td><td>${k.estimated_minutes} 分钟</td><td>${pct(k.requirement?.exam_weight||.5)}</td><td><span class="badge ${k.approved?'green':'amber'}">${k.approved?'已通过':'待审核'}</span></td>${teacher?`<td><div class="toolbar"><button class="btn ghost" data-kp-edit="${k.id}">编辑</button><button class="btn ${k.approved?'danger':'primary'}" data-kp-toggle="${k.id}" data-next="${!k.approved}">${k.approved?'撤回':'通过'}</button><button class="btn danger" data-kp-delete="${k.id}">删除</button></div></td>`:''}</tr>`).join('')}</tbody></table></div>`:'<div class="empty"><b>知识库为空</b>先载入课程基准模板</div>'}
async function openTheory(kpId){modal('<h2>正在读取知识内容…</h2>');try{const d=await api(`/knowledge/${kpId}/theory`);const modules=d.modules.map(m=>`<article class="theory-module"><div class="card-head"><h3>${esc(m.title)}</h3><a href="${esc(m.source_url)}" target="_blank" rel="noopener">OpenDSA 源文件</a></div>${m.sections.map(x=>`<section class="theory-section level-${x.level}"><h4>${esc(x.title)}</h4><div>${esc(x.body).replace(/\n\n/g,'</div><div>').replace(/\n/g,'<br>')}</div></section>`).join('')}</article>`).join('');const materials=(d.material_concepts||[]).map(x=>`<article class="evidence-card"><div class="card-head"><div><small class="muted">${x.scope==='personal'?'我的学习资料':'教师教学资料'} · ${esc(x.resource)} · 第 ${x.page} 页</small><h3>${esc(x.name)}</h3></div><span class="badge ${x.scope==='personal'?'green':'blue'}">置信度 ${pct(x.confidence)}</span></div><p>${esc(x.summary||'')}</p><blockquote>${esc(x.excerpt||'')}</blockquote></article>`).join('');modal(`<h2>${esc(d.name)}</h2><p class="muted">${esc(d.summary)}</p>${modules}${materials?`<h3>资料补充知识点</h3>${materials}`:''}${!modules&&!materials?'<div class="empty">该知识点当前还没有正文或资料补充</div>':''}`)}catch(e){closeModal();toast(e.message,true)}}
function openCourseEdit(c){if(!c)return;modal(`<h2>编辑课程</h2><form id="course-edit-form"><label>课程名称<input name="name" value="${esc(c.name)}" required></label><div class="form-row"><label>课程代码<input name="code" value="${esc(c.code)}" required pattern="[A-Za-z0-9_-]{2,40}"></label><label>学年<input name="academic_year" value="${esc(c.academic_year||'')}"></label></div><label>课程简介<textarea name="description" rows="5">${esc(c.description||'')}</textarea></label><button class="btn primary">保存课程信息</button></form>`);$('#course-edit-form').onsubmit=async e=>{e.preventDefault();const body=Object.fromEntries(new FormData(e.target));try{await api(`/courses/${c.id}`,{method:'PATCH',body});const currentId=state.course?.id;state.courses=await api('/courses');state.course=state.courses.find(x=>x.id===currentId)||state.courses[0]||null;renderCourses();closeModal();toast('课程信息已更新');render()}catch(x){toast(x.message,true)}}}
function openKpEdit(k){modal(`<h2>编辑知识点</h2><form id="kp-edit-form"><label>名称<input name="name" value="${esc(k.name)}"></label><label>摘要<textarea name="summary" rows="5">${esc(k.summary)}</textarea></label><div class="form-row"><label>难度 1-5<input name="difficulty" type="number" min="1" max="5" value="${k.difficulty}"></label><label>预计分钟<input name="estimated_minutes" type="number" min="10" value="${k.estimated_minutes}"></label></div><button class="btn primary">保存</button></form>`);$('#kp-edit-form').onsubmit=async e=>{e.preventDefault();const x=Object.fromEntries(new FormData(e.target));x.difficulty=Number(x.difficulty);x.estimated_minutes=Number(x.estimated_minutes);await api(`/knowledge/${k.id}`,{method:'PATCH',body:x});closeModal();toast('知识点已保存');render()}}
function parseJobId(){return globalThis.crypto?.randomUUID?globalThis.crypto.randomUUID():`parse-${Date.now()}-${Math.random().toString(36).slice(2)}`}
function durationText(seconds){if(seconds==null||!Number.isFinite(seconds))return '预计时间计算中';const n=Math.max(0,Math.round(seconds));return n<60?`约 ${n} 秒`:`约 ${Math.ceil(n/60)} 分钟`}
function showParseProgress(p){const box=$('#parse-progress');if(!box)return;box.classList.remove('hidden');$('#parse-stage').textContent=p.stage||'正在解析教材';$('#parse-percent').textContent=`${p.progress_percent||0}%`;$('#parse-progress-fill').style.width=`${p.progress_percent||0}%`;const total=p.total_sections||0,done=p.completed_sections||0;$('#parse-section').textContent=p.current_section?`${done}/${total} · ${p.current_section}`:(total?`${done}/${total} 个章节已完成`:'正在读取 PDF、识别目录');$('#parse-eta').textContent=p.status==='completed'?'解析完成':p.status==='failed'?'解析失败':p.status==='cancelled'?'解析已停止':p.status==='cancelling'?'等待当前章节请求结束':`剩余 ${durationText(p.remaining_seconds)}`;const cancel=$('#parse-cancel');if(cancel)cancel.disabled=['completed','failed','cancelled','cancelling'].includes(p.status)}
function watchParseProgress(jobId){let active=true;const cancel=$('#parse-cancel');if(cancel)cancel.onclick=async()=>{if(!confirm('停止当前教材解析？本轮尚未提交的知识库变更会回滚。'))return;cancel.disabled=true;cancel.textContent='正在停止…';try{const p=await api(`/parse-progress/${encodeURIComponent(jobId)}/cancel`,{method:'POST'});showParseProgress(p)}catch(x){cancel.disabled=false;cancel.textContent='停止解析';toast(x.message,true)}};const tick=async()=>{if(!active)return;try{const p=await api(`/parse-progress/${encodeURIComponent(jobId)}`);showParseProgress(p)}catch(_){}};tick();const timer=setInterval(tick,1200);return()=>{active=false;clearInterval(timer)}}
async function uploadBook(e){e.preventDefault();const fd=new FormData(e.target);const btn=e.target.querySelector('button');const jobId=parseJobId();fd.append('job_token',jobId);btn.disabled=true;btn.textContent='正在解析教材…';showParseProgress({stage:'正在提交教材',progress_percent:1,status:'parsing'});const stop=watchParseProgress(jobId);try{const d=await api(`/courses/${state.course.id}/books`,{method:'POST',body:fd});showParseProgress({stage:'知识库构建完成',progress_percent:100,status:'completed',total_sections:d.processed_sections,completed_sections:d.processed_sections});toast(`解析完成：${d.knowledge_points||0} 个知识点`);render()}catch(x){toast(x.message,true);btn.disabled=false;btn.textContent='解析并建立知识库'}finally{stop()}}
async function retryBook(btn){const jobId=parseJobId();btn.disabled=true;btn.textContent='正在解析…';const stop=watchParseProgress(jobId);try{const d=await api(`/books/${btn.dataset.bookRetry}/retry?job_token=${encodeURIComponent(jobId)}`,{method:'POST'});toast(`重新解析完成：${d.knowledge_points||0} 个知识点`);render()}catch(x){toast(x.message,true);btn.disabled=false;btn.textContent='重新解析'}finally{stop()}}
async function uploadResource(e){e.preventDefault();const fd=new FormData(e.target);const btn=e.target.querySelector('button');btn.disabled=true;btn.textContent='正在匹配知识点…';try{const d=await api(`/courses/${state.course.id}/resources`,{method:'POST',body:fd});toast(`已提取并匹配 ${d.evidence_count} 条知识点内容`);render()}catch(x){toast(x.message,true);btn.disabled=false;btn.textContent='解析资料并匹配知识点'}}
function typeName(x){return({syllabus:'考试大纲',ppt:'教学PPT',assignment:'作业',exam:'往年试题',note:'个人/补充笔记',self_study:'自主学习资料',book:'参考书章节',article:'课程文章',exercise:'练习资料'})[x]||x}
function bindResourceDeletes(){$$('[data-resource-delete]').forEach(b=>b.onclick=async()=>{if(!confirm('删除这份资料及其知识点映射？'))return;await api(`/resources/${b.dataset.resourceDelete}`,{method:'DELETE'});toast('资料及映射已删除');render()})}
function effectName(x){return({exam_weight:'考试权重',ppt_emphasis:'PPT强调',assignment_weight:'作业权重',exam_frequency:'试题频率',required_level:'掌握等级'})[x]||x}
function kpOptions(xs){return xs.map(k=>`<option value="${k.id}">${esc(k.name)}</option>`).join('')}
const weightOf=k=>Number(k.requirement?.exam_weight??.5);
const dotsOf=n=>{const v=Math.max(0,Math.min(5,Number(n)||0));return'●'.repeat(v)+'○'.repeat(5-v)};
function dedupeKps(kps){const m=new Map();(kps||[]).forEach(k=>{const key=String(k.name||'').trim();if(!key)return;const p=m.get(key);if(!p||(k.approved&&!p.approved)||(k.approved===p.approved&&weightOf(k)>weightOf(p)))m.set(key,k)});return[...m.values()]}
function bigrams(s){s=String(s||'').replace(/[^\u4e00-\u9fa5A-Za-z0-9]/g,'');const r=new Set();for(let i=0;i<s.length-1;i++)r.add(s.slice(i,i+2));if(!r.size&&s)r.add(s);return r}
function jaccard(a,b){const A=bigrams(a),B=bigrams(b);if(!A.size||!B.size)return 0;let n=0;A.forEach(x=>{if(B.has(x))n++});return n/(A.size+B.size-n)}
function diffHint(a,b){let i=0;while(i<a.length&&i<b.length&&a[i]===b[i])i++;let j=0;while(j<a.length-i&&j<b.length-i&&a[a.length-1-j]===b[b.length-1-j])j++;return[a.slice(i,a.length-j),b.slice(i,b.length-j)]}
function chapName(t){const s=String(t||'').trim();const m=s.match(/^(第\s*\d+\s*章)\s*([\u4e00-\u9fa5]*)/);return m?m[1]+(m[2]?' '+m[2]:''):(s.slice(0,20)||'未归章')}
function cleanName(n){const s=String(n||'').replace(/^\s*\d+(\.\d+)*[、.．\s]+/,'').replace(/\s+\d+$/,'').trim();return s||String(n||'').trim()}
function computeInsights(d,role){const topicMap=Object.fromEntries(d.topics.map(t=>[t.id,t])),rootOf=id=>{let t=topicMap[id],g=0;while(t&&t.parent_id&&g++<10)t=topicMap[t.parent_id];return t?t.id:null},all=(d.knowledge_points||[]).map(k=>{const nm=cleanName(k.name);return nm===k.name?k:Object.assign({},k,{name:nm})}),valid=dedupeKps(all.filter(k=>(k.scope||'course')!=='excluded'&&(role==='teacher'||k.approved))),dupCount=all.length-dedupeKps(all).length,ids=new Set(valid.map(k=>k.id)),chapOf={};valid.forEach(k=>{const r=rootOf(k.topic_id);chapOf[k.id]=r!=null&&topicMap[r]?chapName(topicMap[r].title):'未归章'});const out={},inc={};valid.forEach(k=>{out[k.id]=[];inc[k.id]=[]});(d.relations||[]).filter(r=>r.approved&&ids.has(r.from)&&ids.has(r.to)).forEach(r=>{out[r.from].push(r.to);inc[r.to].push(r.from)});const memo={};const depth=(id,seen)=>{if(memo[id]!=null)return memo[id];seen=seen||new Set();if(seen.has(id))return 1;seen.add(id);const ps=inc[id]||[];const v=ps.length?1+Math.max.apply(null,ps.map(p=>depth(p,new Set(seen)))):1;memo[id]=v;return v};const heavy=valid.map(k=>{const od=(out[k.id]||[]).length,dh=depth(k.id);return{k,od,d:dh,idg:(inc[k.id]||[]).length,score:od*3+dh*1.5+(Number(k.difficulty)||0)+(Number(k.estimated_minutes)||0)/40}}).filter(x=>x.od>=1||x.d>=4||(Number(x.k.difficulty)||0)>=4).sort((a,b)=>b.score-a.score);const conf=[],pairs=new Set();for(let i=0;i<valid.length;i++)for(let j=i+1;j<valid.length;j++){const a=valid[i],b=valid[j];if(rootOf(a.topic_id)!==rootOf(b.topic_id))continue;const s=jaccard(a.name,b.name);if(s<.34)continue;const h=diffHint(a.name,b.name);if(!h[0]||!h[1])continue;const key=[a.name,b.name].sort().join('|');if(pairs.has(key))continue;pairs.add(key);conf.push({a,b,s,h})}conf.sort((x,y)=>y.s-x.s);const rawById=Object.fromEntries(all.map(k=>[k.id,k])),excl=[];(d.relations||[]).filter(r=>r.approved).forEach(r=>{const f=rawById[r.from],t=rawById[r.to];if(f&&t&&['excluded','resource_only'].includes(f.scope||'course'))excl.push([f.name,t.name])});const isolated=valid.filter(k=>!(out[k.id]||[]).length&&!(inc[k.id]||[]).length),deepTail=valid.filter(k=>depth(k.id)>=5),longOnes=valid.filter(k=>(Number(k.estimated_minutes)||0)>=90);const dupes=dupCount,noChap=valid.filter(k=>chapOf[k.id]==='未归章').length;const risks=[{n:'重复知识点',v:dupes,u:'条冗余',lvl:dupes?'warn':'ok',msg:'同名知识点被多次导入，会让复习时长翻倍、排序失真',fix:'在课程知识库里合并同名项'},{n:'未归章知识点',v:noChap,u:'个',lvl:noChap?'note':'ok',msg:'没有挂到任何章节，会从「章节负担」里漏掉，也无法按章复习',fix:'在课程知识库里为它们指定所属章节'},{n:'被排除但仍被依赖',v:excl.length,u:'处',lvl:excl.length?'warn':'ok',msg:'已标记「本学期排除/仅资源池」的点，仍是其它知识点的前置',fix:'补替代前置，或恢复这些点的课程归属'},{n:'孤立知识点',v:isolated.length,u:'个',lvl:isolated.length?'note':'ok',msg:'既无前置也无后继，游离在知识体系之外',fix:'确认是否漏建关系，或归为独立拓展内容'},{n:'前置链末端',v:deepTail.length,u:'个',lvl:deepTail.length?'note':'ok',msg:'位于 5 层以上依赖链的末端，前置没掌握会连续失分',fix:'按依赖深度从小到大依次攻克'},{n:'单点超长',v:longOnes.length,u:'个',lvl:longOnes.length?'note':'ok',msg:'单个知识点预计复习 90 分钟以上，一次吃不透',fix:'拆成 2~3 个复习单元分次攻克'}];const agg={};valid.forEach(k=>{const t=chapOf[k.id],a=agg[t]||(agg[t]={n:0,m:0,df:0,base:0});a.n++;a.m+=Number(k.estimated_minutes)||0;a.df+=Number(k.difficulty)||0;if((out[k.id]||[]).length>=2)a.base++});const totalM=Object.values(agg).reduce((s,a)=>s+a.m,0)||1,chapters=Object.entries(agg).map(([t,a])=>({t,n:a.n,m:a.m,avg:a.n?a.df/a.n:0,base:a.base,share:a.m/totalM})).sort((x,y)=>y.m-x.m);return{heavy,conf,risks,chapters,totalM,kpCount:valid.length,rawCount:all.length,dupCount,chapOf}}
const INSIGHT_TOP=10;
function insightsHtml(d,role){const ins=computeInsights(d,role);const rows=ins.heavy.slice(0,INSIGHT_TOP),tagOf=x=>x.od>=3?['地基','red']:(Number(x.k.difficulty)||0)>=4?['硬骨头','amber']:x.d>=5?['链末','blue']:['重点','blue'];const hBody=rows.map((x,i)=>{const t=tagOf(x),k=x.k;return`<tr data-kg-kp="${k.id}" title="点击在知识图上聚焦"><td>${i+1}</td><td><b>${esc(k.name)}</b></td><td class="muted">${esc(ins.chapOf[k.id]||'')}</td><td class="difficulty">${dotsOf(k.difficulty)}</td><td>${x.d} 层</td><td><b>${x.od}</b></td><td>${Number(k.estimated_minutes)||0} 分</td><td><span class="badge ${t[1]}">${t[0]}</span></td></tr>`}).join('');const cBody=ins.conf.slice(0,14).map((c,i)=>`<tr><td>${i+1}</td><td data-kg-kp="${c.a.id}" title="点击在知识图上聚焦"><b>${esc(c.a.name)}</b></td><td data-kg-kp="${c.b.id}" title="点击在知识图上聚焦"><b>${esc(c.b.name)}</b></td><td class="muted">${esc(ins.chapOf[c.a.id]||'')}</td><td>${Math.round(c.s*100)}%</td><td>区分 <b>${esc(c.h[0])}</b> ↔ <b>${esc(c.h[1])}</b></td></tr>`).join('');const rBody=ins.risks.map(r=>`<tr><td><b>${r.n}</b></td><td><span class="badge ${r.lvl==='warn'?'red':r.lvl==='ok'?'green':'amber'}">${r.v}</span> ${r.u}</td><td class="muted">${r.msg}</td><td class="muted">${r.fix}</td></tr>`).join('');const chBody=ins.chapters.map(c=>`<tr><td><b>${esc(c.t)}</b></td><td>${c.n}</td><td>${c.m} 分</td><td>${c.avg.toFixed(1)}</td><td>${c.base}</td><td><div class="bar"><i style="width:${Math.max(4,Math.round(c.share*100))}%"></i></div></td></tr>`).join('');const head=(t)=>`<h4 class="insight-title">${t}</h4>`;return`<section class="card" id="insight-card"><div class="card-head"><div><h3>备考要点</h3></div><div class="toolbar"><span class="badge red">重难点 ${ins.heavy.length}</span><span class="badge amber">易混 ${ins.conf.length} 对</span></div></div>${head('① 重难点（地基优先）')}<div class="table-wrap"><table class="insight-table"><thead><tr><th>#</th><th>知识点</th><th>章节</th><th>难度</th><th>依赖深度</th><th>被依赖</th><th>时长</th><th>类型</th></tr></thead><tbody>${hBody}${ins.heavy.length>INSIGHT_TOP?`<tr><td colspan="8" class="muted">另有 ${ins.heavy.length-INSIGHT_TOP} 个未列出</td></tr>`:''}</tbody></table></div>${head('② 易混知识点对照')}<div class="table-wrap"><table class="insight-table"><thead><tr><th>#</th><th>知识点 A</th><th>知识点 B</th><th>所属章节</th><th>相似度</th><th>区分</th></tr></thead><tbody>${cBody||'<tr><td colspan="6" class="muted">未发现明显易混对</td></tr>'}</tbody></table></div>${head('③ 学习风险体检')}<div class="table-wrap"><table class="insight-table"><thead><tr><th>检查项</th><th>数量</th><th>影响</th><th>建议</th></tr></thead><tbody>${rBody}</tbody></table></div>${head('④ 章节负担分布')}<div class="table-wrap"><table class="insight-table"><thead><tr><th>章节</th><th>知识点</th><th>总时长</th><th>平均难度</th><th>地基点</th><th>占比</th></tr></thead><tbody>${chBody}</tbody></table></div></section>`}
function rootTopicOptions(topics){return topics.filter(t=>!t.parent_id).map(t=>`<option value="${t.id}">${esc(t.title)}</option>`).join('')}
/* ==================== 知识地图：关系可视化 + 节点内速览 + 详情对照 ==================== */
const KG_SCOPE_NAME={course:'课程内容',exam:'考试重点',prerequisite:'前置补充',supplemental:'课件补充',excluded:'本学期排除',resource_only:'仅资源池'};
const KG_SCOPE_FILL={course:'#ffffff',exam:'#fdeaea',prerequisite:'#eeedfe',supplemental:'#e6f1fb',excluded:'#f7f7f4',resource_only:'#f7f7f4'};
const KG_SCOPE_STROKE={course:'#8294be',exam:'#b4453f',prerequisite:'#534ab7',supplemental:'#3f7fbf',excluded:'#9d9c96',resource_only:'#9d9c96'};
/* 三档「比例」不一致：高、宽、字号、圆角、缩进同向放大 → 面积差＝重要度差 */
const KG_IMP={hi:{h:66,w:288,rx:12,fs:13.2,fw:700,fill:'#c6d4f7',stroke:'#2a49a6',name:'重要度高'},
  mid:{h:48,w:264,rx:9,fs:11.4,fw:550,fill:'#e4ebfb',stroke:'#6b83bd',name:'重要度中'},
  lo:{h:38,w:240,rx:8,fs:10.4,fw:400,fill:'#f8fafd',stroke:'#a9b5ce',name:'重要度低'}};
const KG_DIFF_COLOR=[{max:2,c:'#2f9e79'},{max:3,c:'#d99323'},{max:5,c:'#c0504d'}];
const KG_MASTERY=[{max:.4,fill:'#fdeaea',stroke:'#b4453f',name:'掌握度 <40% 待补强'},
  {max:.7,fill:'#fdf4e5',stroke:'#c98424',name:'掌握度 40–70% 待巩固'},
  {max:9,fill:'#e8f6f1',stroke:'#1f8f76',name:'掌握度 ≥70% 已掌握'}];
const KG_VIEW={teacher:[['imp','结构重要度'],['scope','考试范围'],['diff','难度'],['review','审核状态']],
  student:[['mastery','我的掌握度'],['imp','结构重要度'],['diff','难度'],['risk','遗忘风险']]};
const KG_RISK=.85;
const KG_PLACEHOLDER=/等待教师补充|待补充|本校教材目录中的课程内容/;
const KG={ctx:null,m:null,kp:null,ui:{root:null,fold:new Set(),focus:null,q:'',color:'imp',zoom:'fit',trans:true}};

function kgTextWidth(s){let w=0;for(const ch of String(s||''))w+=ch.charCodeAt(0)<256?.56:1;return w}
function kgCut(s,px,fs){const max=Math.max(2,px/(fs||11));let out='',w=0;for(const ch of String(s||'')){const cw=ch.charCodeAt(0)<256?.56:1;if(w+cw>max)return out.trim()+'…';out+=ch;w+=cw}return out}
function kgBrief(k){let s=String(k.summary||'').trim();if(!s||KG_PLACEHOLDER.test(s))return'';s=s.replace(/[。.]+$/,'');const n=String(k.name||'').trim();if(n&&s.indexOf(n)===0)s=s.slice(n.length).replace(/^[，,、:：\s]+/,'');return s.trim()}
function kgAlignMap(review){const out={};((review||{}).chapters||[]).forEach(ch=>(ch.sections||[]).forEach(sec=>(sec.points||[]).forEach(p=>{if(p.matched_outline_title)out[p.id]={outline:p.matched_outline_title,conf:p.match_confidence}})));return out}
function kgDiffColor(v){const n=Math.max(1,Math.min(5,Number(v)||3));return(KG_DIFF_COLOR.find(x=>n<=x.max)||{}).c||'#d99323'}
function kgKp(id){return KG.ctx?((KG.ctx.d.knowledge_points||[]).find(k=>k.id===id)||null):null}

function kgSetCtx(d,states,align,role){
  const topicMap={},order={};
  (d.topics||[]).forEach((t,i)=>{topicMap[t.id]={...t,_i:i};order[t.id]=i});
  const smap={};((states)||[]).forEach(s=>{smap[s.kp_id]=s});
  const kps=d.knowledge_points||[],rels=(d.relations||[]).filter(r=>r.approved);
  const ids=new Set(kps.map(k=>k.id)),outd={},ind={},up={},down={};
  rels.forEach(r=>{if(ids.has(r.from)&&ids.has(r.to)){outd[r.from]=(outd[r.from]||0)+1;ind[r.to]=(ind[r.to]||0)+1;(up[r.to]=up[r.to]||[]).push(r.from);(down[r.from]=down[r.from]||[]).push(r.to)}});
  const rootOf=id=>{let t=topicMap[id],g=0;while(t&&t.parent_id&&g++<10)t=topicMap[t.parent_id];return t?t.id:null};
  const depthOf=id=>{let n=0,t=topicMap[id],g=0;while(t&&t.parent_id&&g++<10){n++;t=topicMap[t.parent_id]}return n};
  const memo={};
  const chain=id=>{if(memo[id]!=null)return memo[id];return kgChain(id,new Set(),up,memo)};
  const score={},tier={};
  kps.forEach(k=>{score[k.id]=(outd[k.id]||0)*3+chain(k.id)*1.5+(k.difficulty||3)+Math.min(4,(k.estimated_minutes||60)/30)+Number((k.requirement||{}).exam_weight??.5)*4});
  const vals=Object.values(score).slice().sort((a,b)=>a-b);
  const q=p=>vals.length?vals[Math.min(vals.length-1,Math.max(0,Math.round((vals.length-1)*p)))]:0;
  const hiT=q(.72),midT=q(.38),loT=q(.02);
  kps.forEach(k=>{const s=score[k.id];tier[k.id]=(hiT>midT&&s>=hiT)?'hi':((midT>loT&&s>=midT)?'mid':'lo')});
  KG.m={topicMap,order,rootOf,depthOf,smap,outd,ind,up,down,chain,score,tier,align:align||{},ids,rels,hiT,midT};
  KG.kp=null;
  KG.ui={root:null,fold:new Set(),focus:null,q:'',color:(KG_VIEW[role]||KG_VIEW.teacher)[0][0],trans:true};
  KG.ctx={d,states,role};
}
function kgChain(id,seen,up,memo){
  if(memo[id]!=null)return memo[id];
  if(seen.has(id))return 0;
  seen.add(id);
  const ps=up[id]||[];
  let v=0;
  ps.forEach(p=>{const x=kgChain(p,seen,up,memo);if(x+1>v)v=x+1});
  seen.delete(id);
  memo[id]=v;
  return v;
}

function kgFillOf(k){
  const m=KG.m,c=KG.ui.color,imp=KG_IMP[m.tier[k.id]];
  if(c==='scope'){const s=k.scope||'course';return{fill:KG_SCOPE_FILL[s]||'#fff',stroke:KG_SCOPE_STROKE[s]||'#8294be'}}
  if(c==='diff'){const col=kgDiffColor(k.difficulty);return{fill:'#ffffff',stroke:col}}
  if(c==='review'){return k.approved?{fill:'#ffffff',stroke:'#8294be'}:{fill:'#fffaf0',stroke:'#e9b55a'}}
  if(c==='mastery'){const v=Number(m.smap[k.id]?.mastery??.25),b=KG_MASTERY.find(x=>v<x.max)||KG_MASTERY[2];return{fill:b.fill,stroke:b.stroke}}
  if(c==='risk'){const r=Number(m.smap[k.id]?.retention??1);return r<KG_RISK?{fill:'#fdeaea',stroke:'#b4453f'}:{fill:'#ffffff',stroke:'#9fadc9'}}
  return{fill:imp.fill,stroke:imp.stroke};
}
function kgDash(k){
  if(!k.approved)return'5 4';
  if(KG.ui.color==='risk'&&Number(KG.m.smap[k.id]?.retention??1)<KG_RISK)return'4 3';
  return'';
}
function kgTip(k){
  const m=KG.m,s=m.smap[k.id],a=m.align[k.id],chap=(m.topicMap[k.topic_id]||{}).title||'未归章';
  const brief=kgBrief(k);
  const L=[cleanName(k.name)];
  if(brief)L.push('速览：'+brief);
  L.push('章节：'+chap);
  L.push('范围：'+(KG_SCOPE_NAME[k.scope]||'课程内容')+' · 审核：'+(k.approved?'已通过':'待审核'));
  L.push('难度 '+(k.difficulty||'-')+'/5 · 预计 '+(k.estimated_minutes||'-')+' 分钟 · 被依赖 '+(m.outd[k.id]||0)+' · 直接前置 '+(m.ind[k.id]||0)+' · 前置链深 '+m.chain(k.id));
  const ext=kgExtPre(k);
  if(ext.length)L.push('跨章前置（'+ext.length+'）：'+ext.slice(0,4).map(pid=>{const pk=kgKp(pid);return pk?cleanName(pk.name):('#'+pid)}).join('、')+(ext.length>4?' 等':''));
  L.push(a?('大纲条目：'+a.outline+(a.conf!=null?'（匹配 '+Math.round(a.conf*100)+'%）':'')):'大纲条目：未匹配');
  L.push(Number(k.page_start)>0?('教材：p.'+k.page_start+(Number(k.page_end)>Number(k.page_start)?'–'+k.page_end:'')):'教材：未标注页码');
  if(s)L.push('我的进度：掌握 '+pct(s.mastery)+' · 保持度 '+pct(s.retention)+' · 复习 '+(s.review_count||0)+' 次');
  L.push('点击方块查看详情与前置链');
  return L.join('\n');
}
function kgHits(q){
  const out=new Set();
  if(!q)return out;
  const m=KG.m;
  (KG.ctx.d.knowledge_points||[]).forEach(k=>{
    const a=m.align[k.id];
    const hay=(cleanName(k.name)+' '+(k.summary||'')+' '+(a?a.outline:'')).toLowerCase();
    if(hay.indexOf(q)>=0)out.add(k.id);
  });
  return out;
}
function kgFocusSet(){
  const id=KG.ui.focus;
  if(!id)return null;
  const m=KG.m,set=new Set([id]);
  const walk=(start,adj)=>{const st=[start],seen=new Set([start]);while(st.length){const u=st.pop();(adj[u]||[]).forEach(v=>{if(!seen.has(v)){seen.add(v);set.add(v);st.push(v)}})}};
  walk(id,m.up);walk(id,m.down);
  return set;
}

/* ---------- 大框（章）> 中框（节）> 小框（知识点）：章内「两列网格」+ 左侧骨架 ---------- */
/* 节内知识点按「两列流式」铺开（左→右、上→下，阅读顺序就是前置顺序），不再一列竖到底；
   卡片因此变宽、整张图从 1:3.4 的长条收成约 1:1.5 的方正版式（章级 3 列）。
   骨架：每章一条主干（SPINE）→ 每个节一条标签支线 + 一条竖直分支干（CORR）→
   只有「重要度高」的知识点才从分支干接一条水平支线（中/低档靠节框归属，点开才画链）。
   同章**跨节**前置依赖走右侧专用走廊（BUSX），与左侧骨架互不打架；同节内的先后由排列顺序表达。
   卡片宽 700 = 左骨架 60 + 两列节点 288+18+288 + 右侧走廊 26 + 两侧内边距。 */
/* 间距重排：两列之间留 34px「列间走廊」、章右侧留 36px「跨节走廊」、节与节留 34px 空隙——
   这些都是给关系线走的通道，线不再压在方块上。宽度核算：62 + 288 + 34 + 288 = 672（节点最右），
   节框右边 = 738 − 14 − 36 = 688（留 16px），跨节走廊 704（离章边 34px）。 */
const KG_COLS=3,KG_SEC_COLS=2,KG_CH_W=738,KG_CH_GAP=36,KG_CH_HDR=70,KG_CH_HDRB=16,KG_CH_PAD=14,KG_BUSW=36,KG_NODE_GAP=18,KG_SEC_GAP=34,KG_MARGIN=26;
const KG_SPINE=15,KG_CORR=36,KG_HUB=48,KG_NODE_X=62,KG_COLW=288,KG_COL_GAP=34,KG_IND={hi:0,mid:8,lo:16},KG_BUSX=704,KG_RR=6;
/* 关系线视觉编码：颜色＝关系范围（跨章/跨节/节内）；粗细+线型+透明度＝依赖距离（直接/一跳/传递） */
const KG_EDGE_SCOPE={x:{c:'#d9455f',name:'跨章前置'},c:{c:'#3f6fd8',name:'跨节前置'},s:{c:'#2f9e79',name:'节内先后'}};
const KG_EDGE_TIER={1:{w:2.8,op:1,dash:'',name:'直接依赖'},2:{w:1.7,op:.72,dash:'',name:'一跳间接'},3:{w:1,op:.26,dash:'5 4',name:'传递依赖'}};

function kgExtPre(k){
  const m=KG.m,rid=m.rootOf(k.topic_id)||0;
  return (m.up[k.id]||[]).filter(pid=>{const pk=kgKp(pid);return pk&&(m.rootOf(pk.topic_id)||0)!==rid});
}

function kgNodeBox(k,p,st){
  const m=KG.m,t=KG_IMP[m.tier[k.id]],col=kgFillOf(k),brief=kgBrief(k),fs=t.fs;
  const pg=Number(k.page_start)>0?('p.'+k.page_start+(Number(k.page_end)>Number(k.page_start)?'–'+k.page_end:'')):'';
  const od=m.outd[k.id]||0,ext=kgExtPre(k);
  const nm=(ext.length?'◂ ':'')+cleanName(k.name);
  const right=(pg?46:0)+(od?28:0);
  const name=kgCut(nm,p.w-24-right,fs);
  const bl=brief?kgCut(brief,p.w-24-(od?28:0),fs-2):'';
  const y1=p.y+p.h*.40,y2=p.y+p.h*.76,pad=10;
  let badges='';
  if(brief){
    if(od)badges+='<text class="kg-out" x="'+(p.x+p.w-pad)+'" y="'+y2+'" text-anchor="end">↑'+od+'</text>';
    if(pg)badges+='<text class="kg-page" x="'+(p.x+p.w-pad)+'" y="'+y1+'" text-anchor="end">'+pg+'</text>';
  }else{
    let rx=p.x+p.w-pad;
    if(od){badges+='<text class="kg-out" x="'+rx+'" y="'+y1+'" text-anchor="end">↑'+od+'</text>';rx-=26}
    if(pg)badges+='<text class="kg-page" x="'+rx+'" y="'+y1+'" text-anchor="end">'+pg+'</text>';
  }
  return '<g class="kg-node kg-t-'+m.tier[k.id]+'" data-kg-node="'+k.id+'"'+(st==='dim'?' style="opacity:.22"':'')+'><title>'+esc(kgTip(k))+'</title>'
    +(st==='hit'?'<rect class="kg-halo" x="'+(p.x-4)+'" y="'+(p.y-4)+'" width="'+(p.w+8)+'" height="'+(p.h+8)+'" rx="13" fill="none" stroke="#4568f2" stroke-width="2.4"/>':'')
    +'<rect class="kg-box" x="'+p.x+'" y="'+p.y+'" width="'+p.w+'" height="'+p.h+'" rx="'+t.rx+'" style="fill:'+col.fill+';stroke:'+col.stroke+';stroke-width:'+(m.tier[k.id]==='hi'&&!kgDash(k)?2:1.3)+(kgDash(k)?';stroke-dasharray:'+kgDash(k):'')+'"/>'
    +'<rect class="kg-dbar" x="'+(p.x+7)+'" y="'+(p.y+6)+'" width="'+(m.tier[k.id]==='hi'?5.5:3.5)+'" height="'+(p.h-12)+'" rx="2.5" style="fill:'+kgDiffColor(k.difficulty)+'"/>'
    +'<text class="kg-name" x="'+(p.x+19)+'" y="'+y1+'" style="font-size:'+fs+'px;font-weight:'+t.fw+'">'+esc(name)+'</text>'
    +(bl?'<text class="kg-brief" x="'+(p.x+19)+'" y="'+y2+'" style="font-size:'+(fs-2.2)+'px">'+esc(bl)+'</text>':'')
    +badges+'</g>';
}

function kgRender(){
  const m=KG.m;
  if(!m)return'<div class="empty compact">暂无知识点</div>';
  const d=KG.ctx.d,ui=KG.ui,kps=d.knowledge_points||[];
  if(!kps.length)return'<div class="empty compact"><b>暂无知识点</b>请先上传教材目录或选择其他课程</div>';
  const lanes=new Map();
  kps.forEach(k=>{const rid=m.rootOf(k.topic_id)||0;if(!lanes.has(rid))lanes.set(rid,[]);lanes.get(rid).push(k)});
  let laneIds=[...lanes.keys()].sort((a,b)=>((order(a)-order(b))));
  if(ui.root)laneIds=laneIds.filter(id=>id===ui.root);
  if(!laneIds.length)return'<div class="empty compact"><b>本章暂无知识点</b>请选择其他章节</div>';
  laneIds=laneIds.filter(id=>id!==0).concat(laneIds.filter(id=>id===0));
  const laneWt={};
  laneIds.forEach(id=>{const L=lanes.get(id);laneWt[id]=L.reduce((a,k)=>a+(m.score[k.id]||0),0)/Math.max(1,L.length)});
  const maxWt=Math.max(1,...laneIds.map(id=>laneWt[id]));
  let topLane=laneIds[0];
  laneIds.forEach(id=>{if(laneWt[id]>laneWt[topLane])topLane=id});
  const multi=laneIds.length>1;
  // 知识点归到「章下的节」（depth ≤ 1 的祖先）
  const secOf=id=>{let t=m.topicMap[id];if(!t)return 0;let g=0;while(t.parent_id&&m.depthOf(t.id)>1&&g++<10)t=m.topicMap[t.parent_id];return t?t.id:0};
  // pass1：章内相对坐标
  const chaps=laneIds.map(rid=>{
    const list=lanes.get(rid),byTopic=new Map();
    list.forEach(k=>{const t=secOf(k.topic_id);if(!byTopic.has(t))byTopic.set(t,[]);byTopic.get(t).push(k)});
    const secIds=[...byTopic.keys()].sort((a,b)=>((order(a)-order(b))));
    const hdr=KG_CH_HDR+Math.round(KG_CH_HDRB*(laneWt[rid]/maxWt));
    const secs=[];let y=hdr;
    secIds.forEach(tid=>{
      const xs=byTopic.get(tid).slice().sort((a,b)=>((m.chain(a.id)-m.chain(b.id))||(m.score[b.id]-m.score[a.id])||(a.id-b.id)));
      // 节内「两列流式」：按顺序左→右、上→下铺开，行高取该行最高的一档
      const top=y,rows=[];let cy=y+42;
      for(let i=0;i<xs.length;i+=KG_SEC_COLS){
        const row=xs.slice(i,i+KG_SEC_COLS);
        const hs=row.map(k=>{const t=KG_IMP[m.tier[k.id]];return kgBrief(k)?t.h:t.h-9});
        const rh=Math.max.apply(null,hs);
        rows.push({row,hs,cy});
        cy+=rh+KG_NODE_GAP+(row.some(k=>m.tier[k.id]==='hi')?5:0);
      }
      const hb=cy-top+6;
      secs.push({tid,xs,rows,top,hb});
      y=top+hb+KG_SEC_GAP;
    });
    return{rid,title:rid===0?'未归章':((m.topicMap[rid]||{}).title||'未归章'),list,secs,hdr,H:y+14};
  });
  // pass2：按章序依次落到「当前最矮的列」——列高尽量均衡、底部不浪费，且每列内部章序递增
  const cols=Math.max(1,Math.min(KG_COLS,Math.ceil(Math.sqrt(laneIds.length))||1));
  const colH=new Array(cols).fill(KG_MARGIN);
  chaps.forEach(ch=>{let c=0;for(let i=1;i<cols;i++){if(colH[i]<colH[c])c=i}ch.x=KG_MARGIN+c*(KG_CH_W+KG_CH_GAP);ch.y=colH[c];colH[c]=ch.y+ch.H+KG_CH_GAP});
  const w0=Math.max(900,KG_MARGIN*2+cols*KG_CH_W+(cols-1)*KG_CH_GAP);
  let w=w0;
  let maxY=KG_MARGIN;colH.forEach(h=>{if(h>maxY)maxY=h});maxY+=KG_MARGIN;
  const q=(ui.q||'').toLowerCase(),hits=kgHits(q),fset=kgFocusSet();
  const stateOf=id=>{
    if(ui.focus===id)return 'hit';
    const inF=!!fset&&fset.has(id);
    if(q){if(hits.has(id))return 'hit';return inF?'':'dim'}
    if(fset)return inF?'':'dim';
    return '';
  };
  const pos={},posCh={},chOut=[],focusOut=[],rel=m.rels||[];
  chaps.forEach(ch=>{
    const folded=ui.fold.has(ch.rid),H=folded?ch.hdr:ch.H;
    const wRatio=laneWt[ch.rid]/maxWt,isTop=multi&&ch.rid===topLane;
    const hint=folded?('▸ 展开本章 · 已折叠 '+ch.list.length+' 个点')
      :('▾ 折叠本章 · 重点度 '+Math.round(100*wRatio)+(isTop?' · 重点章':''));
    const mins=Math.round(ch.list.reduce((a,k)=>a+(Number(k.estimated_minutes)||0),0)/6)/10;
    const tfs=Math.round((12.5+3.5*wRatio)*10)/10;
    const sx=ch.x+KG_SPINE,tx=ch.x+KG_CORR,hx=ch.x+KG_HUB,bx=ch.x+KG_BUSX;
    let head='<g class="kg-lane-head" data-kg-fold="'+ch.rid+'"><title>点击'+(folded?'展开':'折叠')+'本章「'+ch.title+'」</title>'
      +'<rect class="kg-lane-hit" x="'+ch.x+'" y="'+ch.y+'" width="'+KG_CH_W+'" height="'+Math.min(ch.hdr,H)+'" fill="transparent"/>'
      +'<text class="kg-lane-title" x="'+(ch.x+16)+'" y="'+(ch.y+30)+'" text-anchor="start" style="font-size:'+tfs+'px">'+esc(kgCut(ch.title,KG_CH_W-170,tfs))+'</text>'
      +'<text class="kg-ch-stat" x="'+(ch.x+KG_CH_W-16)+'" y="'+(ch.y+30)+'" text-anchor="end">'+ch.list.length+' 点 · '+mins+'h</text>'
      +'<rect class="kg-wt-bg" x="'+(ch.x+16)+'" y="'+(ch.y+40)+'" width="'+(KG_CH_W-32)+'" height="'+(isTop?8:6)+'" rx="3"/>'
      +'<rect class="kg-wt-bar" x="'+(ch.x+16)+'" y="'+(ch.y+40)+'" width="'+Math.max(8,Math.round((KG_CH_W-32)*wRatio))+'" height="'+(isTop?8:6)+'" rx="3"/>'
      +'<text class="kg-lane-hint" x="'+(ch.x+16)+'" y="'+(ch.y+ch.hdr-8)+'" text-anchor="start">'+esc(hint)+'</text></g>';
    const rail=[],dots=[],pills=[],secTop=[],nbox=[];
    let yTop=null,yBot=null;
    if(!folded){
      const colX=[ch.x+KG_NODE_X,ch.x+KG_NODE_X+KG_COLW+KG_COL_GAP];
      ch.secs.forEach(sec=>{
        const sy=ch.y+sec.top,sw=KG_CH_W-KG_CH_PAD*2-KG_BUSW,swx=ch.x+KG_CH_PAD;
        const label=(sec.tid===ch.rid||sec.tid===0)?'本章直属知识点':((m.topicMap[sec.tid]||{}).title||'未命名节');
        const big=sec.rows.length>=4;
        const pfs=big?11:10.5,ph=big?21:18;
        const pw=Math.min(sw-KG_HUB-24,Math.round(kgTextWidth(label)*pfs)+24);
        const py=sy+6,pcy=py+ph/2;
        secTop.push('<rect class="kg-sec" x="'+swx+'" y="'+sy+'" width="'+sw+'" height="'+sec.hb+'" rx="10"/>');
        pills.push('<rect class="kg-sec-pill" x="'+hx+'" y="'+py+'" width="'+pw+'" height="'+ph+'" rx="'+(ph/2)+'"/>');
        pills.push('<text class="kg-sec-name" x="'+(hx+12)+'" y="'+(py+ph*0.70)+'" style="font-size:'+pfs+'px">'+esc(kgCut(label,pw-22,pfs))+'</text>');
        rail.push('M'+sx+','+pcy+' H'+hx);
        dots.push('<circle class="kg-dot" cx="'+sx+'" cy="'+pcy+'" r="'+(big?2.6:2)+'"/>');
        yTop=yTop===null?pcy:Math.min(yTop,pcy);yBot=yBot===null?pcy:Math.max(yBot,pcy);
        // 节内两列网格：第 ci 列固定落在 colX[ci]，同排顶部对齐
        const nodes=[];
        sec.rows.forEach(r=>r.row.forEach((k,ci)=>{
          const tp=KG_IMP[m.tier[k.id]],ind=KG_IND[m.tier[k.id]]||0;
          const p={x:colX[ci]+ind,y:ch.y+r.cy,w:tp.w,h:r.hs[ci],cx:colX[ci]+ind+tp.w/2,cy:ch.y+r.cy+r.hs[ci]/2};
          pos[k.id]=p;posCh[k.id]=ch;nodes.push({k,p});
        }));
        // 分支干只画到"最后一个接了支线的知识点"，避免出现挂不到任何盒子的悬空竖线
        const att=nodes.filter(n=>m.tier[n.k.id]==='hi');
        if(att.length){const lc=Math.max.apply(null,att.map(n=>n.p.cy));if(lc>pcy+2)rail.push('M'+tx+','+pcy+' V'+(lc+KG_RR))}
        nodes.forEach(({k,p})=>{
          if(m.tier[k.id]==='hi'){
            rail.push('M'+tx+','+(p.cy-KG_RR)+' Q'+tx+','+p.cy+' '+(tx+KG_RR)+','+p.cy+' H'+p.x);
            dots.push('<circle class="kg-bdot" cx="'+tx+'" cy="'+p.cy+'" r="1.9"/>');
          }
          nbox.push(kgNodeBox(k,p,stateOf(k.id)));
        });
      });
    }
    let g='<g class="kg-ch" data-kg-lane="'+ch.rid+'">'
      +'<rect class="kg-lane'+(folded?' folded':'')+(multi&&ch.rid===topLane?' top':'')+'" x="'+ch.x+'" y="'+ch.y+'" width="'+KG_CH_W+'" height="'+H+'" rx="16"/>'
      +head;
    // 图层顺序：节底框 → 主干/分支骨架 → 节标签 → 同章前置关系线 → 知识点盒（顶）
    g+=secTop.join('');
    if(yTop!==null)g+='<path class="kg-spine" d="M'+sx+','+yTop+' V'+yBot+'"/>';
    if(rail.length)g+='<path class="kg-rail" d="'+rail.join(' ')+'"/>';
    g+=dots.join('')+pills.join('');
    if(!folded){
      // 只画「跨节」的前置关系：同一个节里节点已按前置顺序自上而下排列，再画线只会糊成一团
      const items=[];
      rel.forEach(r=>{
        const a=kgKp(r.from),b=kgKp(r.to);
        if(!a||!b)return;
        if((m.rootOf(a.topic_id)||0)!==ch.rid||(m.rootOf(b.topic_id)||0)!==ch.rid)return;
        if(secOf(a.topic_id)===secOf(b.topic_id))return;
        const pa=pos[a.id],pb=pos[b.id];
        if(!pa||!pb)return;
        items.push({pa,pb,from:r.from,to:r.to});
      });
      // 贪心分配走廊车道：竖段互相重叠的关系分到不同车道，避免整列叠成一条贯穿的长竖线
      if(items.length){
        items.sort((a,b)=>Math.min(a.pa.cy,a.pb.cy)-Math.min(b.pa.cy,b.pb.cy));
        const laneX=[bx,bx+6,bx+12,bx+18],laneEnd=[-1e9,-1e9,-1e9,-1e9];
        items.forEach(({pa,pb,from,to})=>{
          const y1=Math.min(pa.cy,pb.cy),y2=Math.max(pa.cy,pb.cy);
          let li=0,free=false;
          for(let i=0;i<laneX.length;i++){if(laneEnd[i]+8<y1){li=i;free=true;break}}
          if(!free){for(let i=1;i<laneX.length;i++)if(laneEnd[i]<laneEnd[li])li=i}
          laneEnd[li]=y2;
          const lane=laneX[li],rr=7,dy=pb.cy-pa.cy,sx2=pa.x+pa.w+6,ex2=pb.x+pb.w+6;
          const hub=(m.outd[to]||0)>=3||m.tier[to]==='hi';
          let d;
          if(Math.abs(dy)<2*rr+2){
            d='M'+sx2+','+pa.cy+' H'+lane+' V'+pb.cy+' H'+ex2;
          }else{
            const sg=dy>0?1:-1;
            d='M'+sx2+','+pa.cy+' H'+(lane-rr)+' Q'+lane+','+pa.cy+' '+lane+','+(pa.cy+sg*rr)+' V'+(pb.cy-sg*rr)+' Q'+lane+','+pb.cy+' '+(lane-rr)+','+pb.cy+' H'+ex2;
          }
          g+='<path class="kg-bus'+(hub?' kg-bus-hub':'')+'" d="'+d+'" marker-end="url(#kg-ar-c)"/>';
        });
      }
    }
    chOut.push(g+nbox.join('')+'</g>');
  });
  if(fset){
    const fid=ui.focus;
    /* ---- ① 距离分层：按「有向」步数。上游几步 / 下游几步，0 就是当前点 ---- */
    const ua=new Map([[fid,0]]),da=new Map([[fid,0]]);
    {let fr=[fid],dd=0;while(fr.length){dd++;const nx=[];
      for(const u of fr)for(const v of (m.up[u]||[]))if(!ua.has(v)){ua.set(v,dd);nx.push(v)}
      fr=nx}}
    {let fr=[fid],dd=0;while(fr.length){dd++;const nx=[];
      for(const u of fr)for(const v of (m.down[u]||[]))if(!da.has(v)){da.set(v,dd);nx.push(v)}
      fr=nx}}
    const step=x=>x===fid?0:Math.min(ua.has(x)?ua.get(x):99,da.has(x)?da.get(x):99);
    /* ---- ② 关系范围：跨章 x / 同章跨节 c / 节内 s ---- */
    const scopeOf=(ka,kb)=>((m.rootOf(ka.topic_id)||0)!==(m.rootOf(kb.topic_id)||0))?'x':(secOf(ka.topic_id)===secOf(kb.topic_id)?'s':'c');
    /* ---- ③ 收集：去重 → 分类 → 分档（节内顺序已由排列表达，只画直接先后） ---- */
    const seenE=new Set(),eds=[];
    rel.forEach(r=>{
      const a=pos[r.from],b=pos[r.to],ka=kgKp(r.from),kb=kgKp(r.to);
      if(!a||!b||!ka||!kb||!fset.has(r.from)||!fset.has(r.to))return;
      const key=r.from+'>'+r.to;if(seenE.has(key))return;seenE.add(key);
      const sc=scopeOf(ka,kb);
      const dd=Math.min(step(r.from),step(r.to));
      const tier=(r.from===fid||r.to===fid)?1:(dd<=1?2:3);
      if(sc==='s'&&tier>1)return;
      if(tier===3&&!ui.trans)return;
      eds.push({a,b,sc,tier,chA:posCh[r.from],chB:posCh[r.to],side:(Math.abs(a.cx-b.cx)<KG_COLW/2)?-1:(b.cx>a.cx?1:-1)});
    });
    /* ---- ④ 通道图：一个章里只有三处空白，线只能从这三处走 ----
       ① 两列之间的「列间走道」LANE0（ch.x+367 附近）；② 章右侧「章右走廊」LANE1（ch.x+704）；
       ③ 节与节之间 34px 的「横向安全带」——章内唯一能横穿一整列的高度。
       竖向主干落在「列与列之间」的空隙 gapX[k] 里；跨两列时先在中间列的一条安全带上横穿过去。
       这样每一段横线要么不跨列、要么恰好落在安全带高度，几何上不可能压到任何知识点框。 */
    const spans=chaps.map(c=>[c.x,c.x+KG_CH_W]).sort((p,q)=>p[0]-q[0]);
    const mrg=[];spans.forEach(s=>{const L=mrg[mrg.length-1];
      if(L&&s[0]<=L[1])L[1]=Math.max(L[1],s[1]);else mrg.push(s.slice())});
    const LANE0=ch=>ch.x+KG_NODE_X+KG_COLW+KG_COL_GAP/2;
    const LANE1=ch=>ch.x+KG_BUSX;
    const ciOf=(ch,p)=>p.cx<LANE0(ch)?0:1;
    const colOf=x=>{for(let i=0;i<mrg.length;i++)if(x>=mrg[i][0]-1&&x<=mrg[i][1]+1)return i;return 0};
    const gapX=[];
    { gapX.push(Math.max(11,mrg[0][0]/2));
      for(let i=1;i<mrg.length;i++)gapX.push((mrg[i-1][1]+mrg[i][0])/2);
      gapX.push(mrg[mrg.length-1][1]+Math.max(11,(w0-mrg[mrg.length-1][1])/2)); }
    const beltsOf=ch=>{const t=ch.secs.map(s=>ch.y+s.top),bt=ch.secs.map(s=>ch.y+s.top+s.hb);
      const o=[(ch.y+KG_CH_HDR+t[0])/2];
      for(let i=1;i<t.length;i++)o.push((bt[i-1]+t[i])/2);
      return o};
    const beltOf=(ch,y)=>{let bst=null,bd=1e18;
      beltsOf(ch).forEach(v=>{const d=Math.abs(v-y);if(d<bd){bd=d;bst=v}});
      return bst===null?y:bst};
    const chOnCol=(ci,y)=>{let bst=null;chaps.forEach(c=>{if(colOf(c.x)!==ci)return;if(y>=c.y-1&&y<=c.y+c.H+1)bst=c});return bst};
    /* 同排另一列的水平区间：用来判断「这段横线会不会从同一排的兄弟节点上压过去」 */
    const sibOf=(ch,ci)=>ci===0
      ?[ch.x+KG_NODE_X+KG_COLW+KG_COL_GAP,ch.x+KG_NODE_X+KG_COLW*2+KG_COL_GAP]
      :[ch.x+KG_NODE_X,ch.x+KG_NODE_X+KG_COLW];
    const hitSib=(x1,x2,ch,ci)=>{const l=Math.min(x1,x2),r=Math.max(x1,x2),s=sibOf(ch,ci);
      return r>s[0]+1&&l<s[1]-1};
    /* 节点 → 主干：不跨列就直接横过去；跨列就先横到列间走道，沿走道竖到安全带，再借安全带横穿整列 */
    const lead=(p,ch,x0)=>{
      const ci=ciOf(ch,p),ed=x0>=p.cx?p.x+p.w:p.x;
      if(!hitSib(ed,x0,ch,ci))return [[ed,p.cy],[x0,p.cy]];
      const lane=LANE0(ch),bl=beltOf(ch,p.cy);
      return [[ed,p.cy],[lane,p.cy],[lane,bl],[x0,bl]];
    };
    /* ---- ⑤ 主干规划：每条边先决定经过哪几条竖向主干，再一次性折出顶点序列 ---- */
    const pathOf=(e,st)=>{
      const a=e.a,b=e.b,V=[];
      const push=(x,y)=>{const L=V[V.length-1];
        if(L&&Math.abs(L[0]-x)<.4&&Math.abs(L[1]-y)<.4)return;V.push([x,y])};
      const A=lead(a,e.chA,st[0].base+st[0].off);
      A.forEach(p=>push(p[0],p[1]));
      st[0].y1=A[A.length-1][1];
      for(let i=0;i<st.length-1;i++){
        const y0=V[V.length-1][1];
        const mc=chOnCol(Math.min(st[i].gi,st[i+1].gi),y0);
        const yc=mc?beltOf(mc,y0):y0;
        st[i].y2=yc;st[i+1].y1=yc;
        push(st[i].base+st[i].off,yc);push(st[i+1].base+st[i+1].off,yc);
      }
      const B=lead(b,e.chB,st[st.length-1].base+st[st.length-1].off);
      st[st.length-1].y2=B[B.length-1][1];
      push(st[st.length-1].base+st[st.length-1].off,B[B.length-1][1]);
      for(let i=B.length-2;i>=0;i--)push(B[i][0],B[i][1]);
      return V;
    };
    const mkStations=e=>{
      if(e.sc==='s'){
        /* 同列的节内先后才用短弧；跨列的两个点若还画弧，弧会斜穿整节把中间的点压住 —— 改走正交 */
        if(ciOf(e.chA,e.a)===ciOf(e.chB,e.b))return null;
        return [{key:'L'+e.chA.rid,base:LANE0(e.chA),off:0,y1:0,y2:0}];
      }
      if(e.sc==='c')return [{key:'L'+e.chA.rid,base:LANE0(e.chA),off:0,y1:0,y2:0}];
      const cA=colOf(e.chA.x),cB=colOf(e.chB.x);
      const mk=ks=>ks.map(k=>({key:'X'+k,gi:k,base:gapX[k],off:0,y1:0,y2:0}));
      if(cA===cB){                       /* 同列的两个章：左右两侧空隙各试一次，取拐弯最少的 */
        const cand=[];
        if(cB+1<gapX.length)cand.push(mk([cB+1]));
        cand.push(mk([cB]));
        cand.sort((p,q)=>pathOf(e,p).length-pathOf(e,q).length);
        return cand[0];
      }
      const lo=Math.min(cA,cB),hi=Math.max(cA,cB),ks=[];
      for(let k=lo+1;k<=hi;k++)ks.push(k);
      if(cA>cB)ks.reverse();
      return mk(ks);
    };
    eds.forEach(e=>{e.st=mkStations(e);if(e.st)e.V=pathOf(e,e.st)});   /* 先折一遍拿到各段竖线的 y 区间 */
    /* 分道：同一主干的竖段按 y 区间贪心排开（最多 4 道、间距 7px），避免整条通道叠成一根粗线 */
    { const runs=new Map();
      eds.forEach(e=>e.st&&e.st.forEach(s=>{
        if(!runs.has(s.key))runs.set(s.key,[]);
        runs.get(s.key).push(s);
      }));
      runs.forEach(list=>{
        list.sort((p,q)=>Math.min(p.y1,p.y2)-Math.min(q.y1,q.y2));
        const ends=[];
        list.forEach(s=>{
          const y1=Math.min(s.y1,s.y2),y2=Math.max(s.y1,s.y2);
          let li=0,ok=false;
          for(let i=0;i<ends.length;i++)if(ends[i]+10<y1){li=i;ok=true;break}
          if(!ok)li=ends.length;ends[li]=y2;s.slot=li;
        });
        const n=Math.min(4,Math.max.apply(null,list.map(s=>s.slot))+1);
        list.forEach(s=>{s.off=(Math.min(s.slot,n-1)-(n-1)/2)*7});
      });
    }
    /* 节内短弧的分道（同一节的左右两侧各自排开） */
    { const g=new Map();
      eds.forEach(e=>{if(e.sc!=='s')return;const k='S'+e.chA.rid+':'+e.side;
        if(!g.has(k))g.set(k,[]);g.get(k).push(e)});
      g.forEach(list=>{
        list.sort((p,q)=>Math.min(p.a.cy,p.b.cy)-Math.min(q.a.cy,q.b.cy));
        const ends=[];
        list.forEach(e=>{const y1=Math.min(e.a.cy,e.b.cy),y2=Math.max(e.a.cy,e.b.cy);
          let li=0,ok=false;
          for(let i=0;i<ends.length;i++)if(ends[i]+10<y1){li=i;ok=true;break}
          if(!ok)li=ends.length;ends[li]=y2;e.lane=Math.min(li,3);
        });
      });
    }
    /* ---- ⑥ 出线：正交折线拐角切 1/4 圆弧；颜色＝关系范围，粗细+线型+透明度＝依赖距离 ---- */
    const polyD=(V,rr)=>{
      if(!V.length)return'';
      if(V.length<2)return'M'+V[0][0]+','+V[0][1];
      const f=v=>Math.round(v*10)/10;
      let d='M'+f(V[0][0])+','+f(V[0][1]);
      for(let i=1;i<V.length-1;i++){
        const a=V[i-1],p=V[i],b=V[i+1];
        const dx1=p[0]-a[0],dy1=p[1]-a[1],dx2=b[0]-p[0],dy2=b[1]-p[1];
        const l1=Math.abs(dx1)+Math.abs(dy1),l2=Math.abs(dx2)+Math.abs(dy2);
        if(l1<1||l2<1)continue;
        if((dx1&&dy1)||(dx2&&dy2)){d+=' L'+f(p[0])+','+f(p[1]);continue}
        const r=Math.min(rr,l1/2,l2/2);
        d+=' L'+f(p[0]-Math.sign(dx1)*r)+','+f(p[1]-Math.sign(dy1)*r)
          +' Q'+f(p[0])+','+f(p[1])+' '+f(p[0]+Math.sign(dx2)*r)+','+f(p[1]+Math.sign(dy2)*r);
      }
      return d+' L'+f(V[V.length-1][0])+','+f(V[V.length-1][1]);
    };
    eds.forEach(e=>{
      const cls='kg-fx kg-sc-'+e.sc+' kg-t'+e.tier;
      const meta=' data-kg-e="'+e.sc+e.tier+'"';
      if(e.sc==='s'&&!e.st){
        /* 同列的节内先后：短弧。两个端点都取「朝列间走道那一侧的边」、朝走道鼓出，
           于是弧始终待在 34px 的走道里；弧宽也必须小于 34px（26+8*lane 会探进相邻列压住兄弟节点）。 */
        const k=Math.min(16+e.lane*5,31),d0=ciOf(e.chA,e.a)===0?1:-1;
        const ax=d0>0?e.a.x+e.a.w:e.a.x, bx=d0>0?e.b.x+e.b.w:e.b.x;
        focusOut.push('<path class="'+cls+'"'+meta+' d="M'+ax+','+e.a.cy+' C'+(ax+d0*k)+','+e.a.cy+' '+(bx+d0*k)+','+e.b.cy+' '+bx+','+e.b.cy+'" marker-end="url(#kg-ar-s)"/>');
      }else{
        const V=pathOf(e,e.st);
        const cx=st0=>st0.base+st0.off;
        focusOut.push('<path class="'+cls+'"'+meta+' data-kg-cx="'+Math.round(cx(e.st[0])*10)/10
          +'" data-kg-cx2="'+Math.round(cx(e.st[e.st.length-1])*10)/10
          +'" d="'+polyD(V,8)+'" marker-end="url(#kg-ar-'+e.sc+')"/>');
        V.forEach(p=>{if(p[0]+KG_MARGIN>w)w=p[0]+KG_MARGIN});
      }
    });
  }
  // 默认「一屏看全」：等比缩到容器宽，方正版式一屏读完；切「原始尺寸」可 1:1 看细节
  const fit=ui.zoom!=='full';
  return '<svg class="graph-svg kg-svg" viewBox="0 0 '+w+' '+maxY+'" style="width:'+w+'px;height:'+(fit?'auto':maxY+'px')+(fit?';max-width:100%':'')+'">'
    +'<defs>'
    +Object.keys(KG_EDGE_SCOPE).map(s=>'<marker id="kg-ar-'+s+'" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="5.4" markerHeight="5.4" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="'+KG_EDGE_SCOPE[s].c+'"/></marker>').join('')
    +'</defs>'
    +chOut.join('')+focusOut.join('')+'</svg>';
}
function order(id){return KG.m.order[id]==null?9999:KG.m.order[id]}

function kgLegendItems(){
  const c=KG.ui.color;
  let sw=[];
  if(c==='scope')sw=Object.keys(KG_SCOPE_NAME).map(s=>[KG_SCOPE_FILL[s],KG_SCOPE_STROKE[s],KG_SCOPE_NAME[s],null]);
  else if(c==='mastery')sw=KG_MASTERY.map(b=>[b.fill,b.stroke,b.name,null]);
  else if(c==='diff')sw=KG_DIFF_COLOR.map((x,i)=>['#ffffff',x.c,'难度 '+(i===0?'1–2 易':(i===1?'3 中':'4–5 难')),null]);
  else if(c==='review')sw=[['#fffaf0','#e9b55a','待审核',null],['#ffffff','#8294be','已通过',null]];
  else if(c==='risk')sw=[['#fdeaea','#b4453f','保持度 <85% 有遗忘风险',null],['#ffffff','#9fadc9','保持度充足',null]];
  else sw=[['hi','高'],['mid','中'],['lo','低']].map(([t,n])=>[KG_IMP[t].fill,KG_IMP[t].stroke,'重要度'+n,t]);
  const SZ={hi:[17,13],mid:[13,10],lo:[10,7.5]};
  return sw.map(([f,s,n,t])=>{
    const z=t?SZ[t]:null;
    return '<span class="kg-sw">'+(z?'<i class="kg-sw-sz" style="background:'+f+';border-color:'+s+';width:'+z[0]+'px;height:'+z[1]+'px"></i>':'<i style="background:'+f+';border-color:'+s+'"></i>')+n+'</span>'
  }).join('');
}
function kgLegendHtml(role){
  return '<div class="kg-legend"><b>'+(role==='student'?'掌握度视角':'重点视角')+'</b><span class="kg-sws" id="kg-legend-items">'+kgLegendItems()+'</span><span class="kg-lines" id="kg-legend-lines">'+kgLineLegend()+'</span></div>';
}
/* 关系线图例：颜色＝关系范围，粗细/虚实＝依赖距离。只在聚焦时出现，纯图例不做解释。 */
function kgLineLegend(){
  if(!KG.ui.focus)return'';
  const sw=(color,w,dash)=>{
    const da=dash?(' stroke-dasharray="'+dash+'"'):'';
    return '<svg class="kg-lw-svg" width="36" height="10" viewBox="0 0 36 10">'
      +'<line x1="1" y1="5" x2="26" y2="5" stroke="'+color+'" stroke-width="'+w+'"'+da+' stroke-linecap="round"/>'
      +'<path d="M26,1.6 L34,5 L26,8.4 z" fill="'+color+'"'+(dash?' opacity=".45"':'')+'/></svg>';
  };
  const sc=Object.keys(KG_EDGE_SCOPE).map(s=>'<span class="kg-lw"><i>'+sw(KG_EDGE_SCOPE[s].c,3,'')+'</i>'+KG_EDGE_SCOPE[s].name+'</span>').join('');  const ti=Object.keys(KG_EDGE_TIER).map(t=>{const d=KG_EDGE_TIER[t];
    const on=!(t==='3'&&!KG.ui.trans);
    const btn=(t==='3')?' kg-lw-btn'+(on?'':' off'):'';
    const tip=(t==='3')?('点击'+(on?'收起':'显示')+'传递依赖（第 3 层及更远的间接依赖）'):d.name;
    return '<span class="kg-lw'+btn+'"'+(t==='3'?' data-kg-toggle="trans"':'')+' title="'+tip+'"><i>'+sw('#6b7794',t==='1'?3:(t==='2'?2:1),d.dash)+'</i>'+d.name+'</span>'}).join('');
  return '<em>关系线</em><span class="kg-lws">'+sc+'</span><em>依赖距离</em><span class="kg-lws">'+ti+'</span>';
}
function kgHitText(){
  const total=((KG.ctx||{}).d||{knowledge_points:[]}).knowledge_points.length;
  if(KG.ui.q)return '匹配 '+kgHits(KG.ui.q.toLowerCase()).size+' / 共 '+total;
  if(KG.ui.focus){const k=kgKp(KG.ui.focus);return '已聚焦：'+(k?cleanName(k.name):'')}
  return '共 '+total+' 个知识点';
}
function kgToolbarHtml(role){
  const views=KG_VIEW[role]||KG_VIEW.teacher;
  return '<input id="kg-q" class="kg-search" placeholder="搜索知识点 / 速览 / 大纲条目" autocomplete="off"><span class="badge blue" id="kg-hit">'+esc(kgHitText())+'</span><select id="kg-root" class="kg-sel"><option value="">全部章节</option>'+rootTopicOptions(KG.ctx.d.topics)+'</select><select id="kg-color" class="kg-sel">'+views.map(([v,l])=>'<option value="'+v+'"'+(v===KG.ui.color?' selected':'')+'>着色：'+l+'</option>').join('')+'</select><button class="btn" id="kg-zoom" title="在「按容器宽度缩放」与「原始尺寸 1:1」之间切换">'+((KG.ui.zoom==='full')?'▣ 原尺寸':'◱ 适屏')+'</button><button class="btn" id="kg-clear">清除聚焦</button><button class="btn" id="kg-print" title="按浏览器打印／另存为 PDF">打印本页</button>';
}
function kgDetailHtml(){
  const m=KG.m;
  if(!m)return'';
  const id=KG.ui.focus;
  if(!id){KG.kp=null;return'<div class="kg-hint">点击任意方块查看详情</div>'}
  const k=kgKp(id);
  if(!k){KG.kp=null;return''}
  KG.kp=k;
  const a=m.align[k.id],s=m.smap[k.id],st=KG.ctx.role==='student',req=k.requirement||{};
  const chap=(m.topicMap[k.topic_id]||{}),rootT=(m.topicMap[m.rootOf(k.topic_id)]||{});
  const pg=Number(k.page_start)>0?('p.'+k.page_start+(Number(k.page_end)>Number(k.page_start)?'–'+k.page_end:'')):'未标注页码';
  const chips=(ids,tip)=>{const arr=ids||[];if(!arr.length)return'<span class="muted">—</span>';
    return arr.slice(0,12).map(i=>{const kk=kgKp(i);if(!kk)return'';
      const c2=(m.topicMap[kk.topic_id]||{}).title||'未归章';
      return '<button class="kg-chip" data-kg-kp="'+i+'" title="'+esc(tip+'：'+cleanName(kk.name)+' · '+c2)+'">'+esc(cleanName(kk.name))+'</button>'}).join('')
      +(arr.length>12?('<span class="muted">等 '+(arr.length-12)+' 个</span>'):'')};
  const brief=kgBrief(k);
  return '<div class="kg-detail">'
    +'<div class="kg-dhead"><b>'+esc(cleanName(k.name))+'</b>'
    +'<span class="badge '+(k.approved?'green':'amber')+'">'+(k.approved?'已通过':'待审核')+'</span>'
    +'<span class="badge blue">'+esc(KG_SCOPE_NAME[k.scope]||'课程内容')+'</span>'
    +(req.included_in_exam?'<span class="badge red">纳入考试</span>':'')
    +'<span class="badge">'+esc(KG_IMP[m.tier[k.id]].name)+'</span>'
    +'<button class="btn" id="kg-clear2">清除聚焦</button></div>'
    +'<div class="kg-briefline">'+(brief?esc(brief):'该条目暂无一句话速览（来自教材目录，等待补充摘要）')+'</div>'
    +'<div class="kg-grid">'
    +'<div class="kg-f"><small>教材出处</small><span>'+esc(pg)+'</span></div>'
    +'<div class="kg-f"><small>大纲条目</small><span>'+(a?(esc(a.outline)+(a.conf!=null?' <em>匹配 '+Math.round(a.conf*100)+'%</em>':'')):'未匹配到大纲条目')+'</span></div>'
    +'<div class="kg-f"><small>所属章节</small><span>'+esc(chap.title||'未归章')+((rootT.title&&rootT.id!==chap.id)?(' › '+esc(rootT.title)):'')+'</span></div>'
    +'<div class="kg-f"><small>结构位置</small><span>被依赖 '+(m.outd[k.id]||0)+' · 直接前置 '+(m.ind[k.id]||0)+' · 前置链深 '+m.chain(k.id)+'</span></div>'
    +'<div class="kg-f"><small>学习成本</small><span>难度 '+(k.difficulty||'-')+'/5 '+dotsOf(k.difficulty)+' · 预计 '+(k.estimated_minutes||'-')+' 分钟</span></div>'
    +'<div class="kg-f"><small>'+(st?'我的状态':'考核要求')+'</small><span>'+(st?('掌握度 '+pct(s?.mastery??.25)+' · 保持度 '+pct(s?.retention??1)+' · 复习 '+(s?.review_count||0)+' 次'):('权重 '+(req.exam_weight??'-')+' · 要求层级 '+(req.required_level??'-')+(req.teacher_note?(' · 备注：'+esc(req.teacher_note)):'')))+'</span></div>'
    +'</div>'
    +'<div class="kg-flows"><div class="kg-flow"><b>前置（要先学）'+ (m.up[k.id]||[]).length +' 个</b><div class="kg-chips">'+chips(m.up[k.id],'前置')+'</div></div><div class="kg-flow"><b>后续（学完可做）'+ (m.down[k.id]||[]).length +' 个</b><div class="kg-chips">'+chips(m.down[k.id],'后续')+'</div></div></div>'
    +'<div class="kg-fnote">点击标签可跳转</div>'
    +'<div class="kg-acts"><button class="btn primary" id="kg-theory">看理论正文</button>'+(st?'':'<button class="btn" id="kg-edit">编辑知识点</button>')+'<span class="muted">再点方块取消聚焦</span></div>'
    +'</div>';
}
function kgMatrixHtml(d,states){
  const m=KG.m;
  if(!m)return'';
  const smap=m.smap,approved=(d.knowledge_points||[]).filter(k=>k.approved);
  if(!approved.length)return'';
  const lanes=new Map();
  approved.forEach(k=>{const rid=m.rootOf(k.topic_id)||0;if(!lanes.has(rid))lanes.set(rid,[]);lanes.get(rid).push(k)});
  const rows=[...lanes.entries()].map(([rid,list])=>{
    const vals=list.map(k=>Number(smap[k.id]?.mastery??.25));
    const mean=vals.reduce((a,b)=>a+b,0)/vals.length;
    return{rid,list:list.slice().sort((a,b)=>(m.score[b.id]-m.score[a.id])),mean,weak:vals.filter(v=>v<.4).length,solid:vals.filter(v=>v>=.7).length};
  }).sort((a,b)=>a.mean-b.mean);
  const cell=k=>{const v=Number(smap[k.id]?.mastery??.25),b=KG_MASTERY.find(x=>v<x.max)||KG_MASTERY[2];
    return '<i class="kg-cell" style="background:'+b.fill+';border-color:'+b.stroke+'" title="'+esc(cleanName(k.name))+' · 掌握度 '+pct(v)+'"></i>'};
  return '<section class="card"><div class="card-head"><div><h3>章节掌握度总览</h3></div><div class="toolbar">'+KG_MASTERY.map(b=>'<span class="kg-sw"><i style="background:'+b.fill+';border-color:'+b.stroke+'"></i>'+b.name+'</span>').join('')+'</div></div><div class="kg-matrix">'
    +rows.map(r=>'<div class="kg-mrow"><span class="kg-mname">'+esc(kgCut(r.rid===0?'未归章':((m.topicMap[r.rid]||{}).title||'未归章'),170,12))+'</span><span class="kg-cells">'+r.list.map(cell).join('')+'</span><span class="kg-mstat"><b>'+pct(r.mean)+'</b><small>待补强 '+r.weak+' · 已掌握 '+r.solid+'</small></span></div>').join('')
    +'</div></section>';
}
function kgFocusKp(id){
  const k=kgKp(id);
  if(!k)return;
  KG.ui.focus=KG.ui.focus===id?null:id;
  if(KG.ui.focus){
    KG.ui.root=null;
    KG.ui.fold.delete(KG.m.rootOf(k.topic_id)||0);
    const rs=$('#kg-root');
    if(rs)rs.value='';
  }
  kgRedraw();
  if(KG.ui.focus){const c=$('#graph-canvas');if(c&&c.scrollIntoView)c.scrollIntoView({behavior:'smooth',block:'center'})}
}
function kgBind(){
  const canvas=$('#graph-canvas');
  if(canvas)canvas.onclick=e=>{
    const node=e.target.closest('[data-kg-node]'),fold=e.target.closest('[data-kg-fold]');
    if(node){const id=Number(node.dataset.kgNode);KG.ui.focus=KG.ui.focus===id?null:id;kgRedraw();return}
    if(fold){const id=Number(fold.dataset.kgFold);if(KG.ui.fold.has(id))KG.ui.fold.delete(id);else KG.ui.fold.add(id);kgRedraw();return}
    if(KG.ui.focus){KG.ui.focus=null;kgRedraw()}
  };
  const q=$('#kg-q');
  if(q)q.oninput=()=>{KG.ui.q=q.value.trim();kgRedraw()};
  const rs=$('#kg-root');
  if(rs){rs.value=KG.ui.root==null?'':String(KG.ui.root);rs.onchange=()=>{KG.ui.root=Number(rs.value)||null;kgRedraw()}}
  const col=$('#kg-color');
  if(col)col.onchange=()=>{KG.ui.color=col.value;const L=$('#kg-legend-items');if(L)L.innerHTML=kgLegendItems();kgRedraw()};
  const cl=$('#kg-clear');
  if(cl)cl.onclick=()=>{KG.ui.focus=null;KG.ui.q='';const qq=$('#kg-q');if(qq)qq.value='';kgRedraw()};
  const zm=$('#kg-zoom');
  if(zm)zm.onclick=()=>{KG.ui.zoom=(KG.ui.zoom==='full')?'fit':'full';zm.textContent=(KG.ui.zoom==='full')?'▣ 原尺寸':'◱ 适屏';kgRedraw()};
  const ic=$('#insight-card');
  if(ic)ic.onclick=e=>{const t=e.target.closest('[data-kg-kp]');if(t)kgFocusKp(Number(t.dataset.kgKp))};
  const lg=$('#kg-legend-lines');
  if(lg)lg.onclick=e=>{if(e.target.closest('[data-kg-toggle="trans"]')){KG.ui.trans=!KG.ui.trans;kgRedraw()}};
  const pr=$('#kg-print');
  if(pr)pr.onclick=()=>window.print();
  const det=$('#graph-detail');
  if(det)det.onclick=e=>{
    const chip=e.target.closest('[data-kg-kp]');
    if(chip){kgFocusKp(Number(chip.dataset.kgKp));return}
    if(e.target.closest('#kg-theory')&&KG.kp)openTheory(KG.kp.id);
    else if(e.target.closest('#kg-edit')&&KG.kp)openKpEdit(KG.kp);
    else if(e.target.closest('#kg-clear2')){KG.ui.focus=null;kgRedraw()}
  };
}
function kgRedraw(){
  const canvas=$('#graph-canvas');
  if(!canvas)return;
  const sl=canvas.scrollLeft,tp=canvas.scrollTop;
  canvas.innerHTML=kgRender();
  canvas.scrollLeft=sl;canvas.scrollTop=tp;
  const hit=$('#kg-hit');
  if(hit)hit.textContent=kgHitText();
  const LL=$('#kg-legend-lines');
  if(LL)LL.innerHTML=kgLineLegend();
  const det=$('#graph-detail');
  if(det)det.innerHTML=kgDetailHtml();
}
function futureDate(days){const d=new Date();d.setDate(d.getDate()+days);return d.toISOString().slice(0,10)}
function daysTo(s){return Math.max(0,Math.ceil((new Date(s)-new Date())/86400000))}
function renderToday(plan){const pending=plan.items.filter(x=>!x.completed),day=pending[0]?.day||1,items=pending.filter(x=>x.day===day).slice(0,4);return items.length?items.map(x=>`<div class="plan-item"><div><div class="plan-name">${esc(x.name)}</div><div class="plan-meta">${x.minutes} 分钟 · ${esc(x.reason)}</div></div></div>`).join(''):'<div class="empty"><b>计划已全部完成</b>可以进行一次诊断测验</div>'}
function renderPlan(plan){const groups={};plan.items.forEach(x=>(groups[x.day]??=[]).push(x));return Object.entries(groups).map(([day,xs])=>`<div class="plan-day"><div class="day-label">第 ${day} 天</div><div>${xs.map(x=>`<label class="plan-item ${x.completed?'done':''}"><input type="checkbox" data-plan-item="${x.id}" ${x.completed?'checked':''}><div><div class="plan-name">${esc(x.name)}</div><div class="plan-meta">${x.minutes} 分钟 · 优先级 ${pct(x.priority)} · ${esc(x.reason)}</div></div></label>`).join('')}</div></div>`).join('')}
function renderQuiz(){const q=state.quiz[state.quizIndex];if(!q){const r=state.quizResults;$('#view').innerHTML=`<section class="card quiz-card"><div class="empty"><b>本轮判断题诊断完成</b><p>答对 ${r.correct} 题 · 答错 ${r.wrong} 题</p><p>掌握度已按作答正误更新，复习计划会优先安排错误较多且章节权重高的内容。</p><button class="btn primary" id="quiz-again">再诊断一轮</button></div></section>`;$('#quiz-again').onclick=()=>studentPages.quiz();return}const progress=Math.round(state.quizIndex*100/state.quiz.length);$('#view').innerHTML=`<section class="card quiz-card"><div class="card-head"><div><h3>知识判断 ${state.quizIndex+1} / ${state.quiz.length}</h3><small class="muted">${esc(q.chapter)} · ${esc(q.kp_name)}</small></div><span class="badge ${q.focus_score>=.7?'amber':'blue'}">章节重点 ${pct(q.focus_score)}</span></div><div class="progress quiz-progress"><span style="width:${progress}%"></span></div><div class="quiz-question">${esc(q.question)}</div><div class="familiarity-statement">${esc(q.statement)}</div><div id="quiz-feedback"></div><div class="answer-buttons familiarity-buttons"><button class="btn danger" data-judgment="false">错误</button><button class="btn success" data-judgment="true">正确</button></div><p class="quiz-hint">根据定义、性质、适用条件或复杂度判断命题正误。</p></section>`;$$('[data-judgment]').forEach(b=>b.onclick=async()=>{const judgment=b.dataset.judgment==='true';$$('[data-judgment]').forEach(x=>x.disabled=true);try{const x=await api('/quiz/submit',{method:'POST',body:{question_id:q.question_id,kp_id:q.kp_id,question:q.statement,answer:judgment?'正确':'错误',judgment}});state.quizResults[x.correct?'correct':'wrong']++;$('#quiz-feedback').innerHTML=`<div class="notice"><b>${x.correct?'回答正确':'回答有误'} · 正确答案：${x.correct_answer?'正确':'错误'}</b><p>${esc(x.explanation||'')}</p><button class="btn primary" id="quiz-next">下一题</button></div>`;$('#quiz-next').onclick=()=>{state.quizIndex++;renderQuiz()};toast(`${q.kp_name} 掌握度更新为 ${pct(x.mastery)}`)}catch(x){toast(x.message,true);$$('[data-judgment]').forEach(x=>x.disabled=false)}})}

(async()=>{if(state.token){try{state.user=await api('/auth/me');await boot()}catch(e){logout()}}})();

