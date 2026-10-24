// Editable presentation JSX; rendering/export uses the bundled artifact-tool.
import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const project = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const skill = process.env.PRESENTATION_SKILL_DIR ?? path.join(process.env.HOME,
  ".codex/plugins/cache/openai-primary-runtime/presentations/26.513.11550/skills/presentations");
const workspace = path.join(project, "outputs/manual-20261024/presentations/elevator-coursework");
const helpers = await import(pathToFileURL(path.join(skill, "scripts/artifact_tool_utils.mjs")));
await helpers.ensureArtifactToolWorkspace(workspace);
const artifact = await helpers.importArtifactTool(workspace);
const { jsx } = await import(pathToFileURL(path.join(workspace, "node_modules/@oai/artifact-tool/dist/presentation-jsx/jsx-runtime.mjs")));

const C = { paper: "#F7F8F5", ink: "#143139", teal: "#087F78", amber: "#C78132", muted: "#64777A", light: "#E1E9E4", white: "#FFFFFF", coral: "#C35E42" };
function T(slide, text, x, y, w, h, size = 24, color = C.ink, bold = false, name = "text") {
  const children = text.split("\n").map(line => jsx("paragraph", {children: line}));
  slide.compose(jsx("text", {name, width: w, height: h,
    style: {fontSize: size, typeface: "PingFang SC", color, bold, verticalAlignment: name === "kicker-label" ? "middle" : "top", insets: {left:0,right:0,top:0,bottom:0}}, children}),
    {frame: {left:x, top:y, width:w, height:h}});
}
function R(slide, x, y, w, h, fill, name = "shape", geometry = "rect") {
  slide.compose(jsx("shape", {name, geometry, width:w, height:h, fill}),
    {frame:{left:x,top:y,width:w,height:h}});
}
function A(slide, x, y, w = 36, h = 18, geometry = "rightArrow") { R(slide,x,y,w,h,C.muted,"connector",geometry); }
async function I(slide, filename, x, y, w, h) {
  const bytes=await fs.readFile(path.join(project, "docs/coursework/images", filename));
  slide.compose(jsx("image", {name:filename, blob:bytes, width:w,height:h,fit:"contain",alt:filename}),
    {frame:{left:x,top:y,width:w,height:h}});
}
function base(p, n, kicker, title, dark = false) {
  const s=p.slides.add();s.background.fill=dark?C.ink:C.paper;
  const ink=dark?C.white:C.ink;
  R(s,64,42,8,18,C.amber,"kicker-marker");
  T(s,kicker,84,39,1050,24,17,dark?"#B9D0D0":C.teal,true,"kicker-label");
  T(s,title,64,95,1148,100,38,ink,true,"claim-title");
  R(s,64,663,1152,1,dark?"#416066":"#C8D4CF","footer-rule");
  T(s,"多电梯智能群控 · 课程冻结提交版",64,679,650,24,14,dark?"#B9D0D0":C.muted,false,"footer");
  T(s,String(n).padStart(2,"0"),1164,676,50,27,17,dark?C.white:C.ink,true,"page");
  return s;
}
function note(s,text) { T(s,text,64,620,1140,34,16,C.muted,false,"source"); }
function node(s,x,y,w,h,label,detail) {
  R(s,x,y,w,h,C.light,"module");
  T(s,label,x+18,y+18,w-36,36,25,C.ink,true,"module-name");
  T(s,detail,x+18,y+62,w-36,h-70,19,C.muted,false,"module-detail");
}

export async function render(n,p) {
  let s;
  if(n===1) {
    s=base(p,n,"DEEP REINFORCEMENT LEARNING","让 PPO 看见接单的后果",true);
    T(s,"基于深度强化学习的多电梯智能群控系统",64,214,1120,58,30,"#B9D0D0");
    T(s,"13.14",64,350,360,106,84,C.white,true);
    T(s,"秒 · 提交801的开发平均等待",68,465,550,45,23,"#B9D0D0");
    R(s,690,350,2,175,C.amber);
    T(s,"统一仿真  →  真实PPO  →  同流验证",735,360,480,55,25,C.white,true);
    T(s,"135组开发客流 · 单模型结果\n不作为独立盲测结论",735,432,480,95,22,"#B9D0D0");
    T(s,"小组：____________    成员：________________________",64,580,1100,36,20,"#B9D0D0");
  } else if(n===2) {
    s=base(p,n,"PROBLEM","相同接人时间，可能对应完全不同的任务延误");
    T(s,"两梯在1层；第一台已有1→5层任务；新请求为2→3层",64,190,1150,46,24,C.muted);
    for(const [x,label,color] of [[64,"派给已有任务的第一台",C.coral],[675,"派给空闲的第二台",C.teal]]) {
      R(s,x,264,540,295,C.light);T(s,label,x+24,286,500,40,25,color,true);
      T(s,"4.8 秒",x+24,342,500,77,54,C.ink,true);
      T(s,"新乘客接到时间",x+24,423,500,35,21,C.muted);
    }
    T(s,"旧乘客：接人 +8.8秒，送达 +13.6秒",88,490,495,40,21,C.coral,true);
    T(s,"已有任务不产生新增延误",699,490,490,40,21,C.teal,true);
    note(s,"独立手算回归：默认物理参数；第一台插入路线2→1→3→5。ETA本身不能表达全部外部性。");
  } else if(n===3) {
    s=base(p,n,"REQUIREMENTS","四个页面覆盖配置、运行、比较和训练");
    const list=[["场景配置","建筑 / 客流 / 输入Trace"],["实时仿真","暂停 / 继续 / 乘客与决策"],["实验评价","同流比较 / 指标与原始表"],["训练与模型","真实曲线 / 版本与权重SHA"]];
    list.forEach((a,i)=>{const x=64+i*292;node(s,x,230,264,160,a[0],a[1]);if(i<3)A(s,x+268,300,20,15);});
    T(s,"5–30",64,445,280,80,56,C.teal,true);T(s,"层",64,525,280,35,24,C.muted);
    T(s,"2–8",405,445,280,80,56,C.teal,true);T(s,"部电梯 · 容量6–20人",405,525,365,35,24,C.muted);
    T(s,"5",830,445,280,80,56,C.teal,true);T(s,"种客流模式",830,525,340,35,24,C.muted);
    note(s,"本地教学仿真；普通CPU运行已提供模型。所有策略共享物理内核与不可变乘客流。");
  } else if(n===4) {
    s=base(p,n,"ARCHITECTURE","物理、策略、评价与界面各有明确边界");
    const xs=[64,460,856];
    const upper=[["配置与Trace","严格校验 / 独立随机流"],["事件仿真","整数微秒 / 容量与路线"],["控制器","三经典 / PPO / 合法mask"]];
    const lower=[["归档与指标","乘客 / 决策 / 完整cohort"],["API与worker","作业协调 / HTTP与WS"],["Web工作台","服务端状态 / 图表与导出"]];
    upper.forEach((v,i)=>node(s,xs[i],225,350,135,...v));
    lower.forEach((v,i)=>node(s,xs[i],440,350,135,...v));
    [0,1].forEach(i=>{A(s,xs[i]+355,282,34);A(s,xs[i]+355,498,34);});
    T(s,"仿真在决策边界反复调用策略；前端不自行推进电梯物理",64,380,1140,36,23,C.teal,true);
    note(s,"上排为输入与决策链，下排为结果交付链；计算worker不写SQLite，协调器维护索引。");
  } else if(n===5) {
    s=base(p,n,"MODELING","六项后果进入网络，权衡仍由 PPO 学习");
    const features=["新客接人时间","新客送达时间","新增运行距离","已有任务接人延误","已有任务送达延误","路线延长"];
    features.forEach((v,i)=>{T(s,String(i+1).padStart(2,"0"),64,212+i*54,55,38,21,C.amber,true);T(s,v,134,212+i*54,430,38,25,C.ink);});
    R(s,620,218,570,310,C.light);
    T(s,"128 + 96 + 6 = 230",652,250,510,58,35,C.teal,true);
    T(s,"电梯编码     上下文     后果",652,320,500,38,22,C.muted);
    T(s,"230 → 128 → 1",652,388,510,58,35,C.ink,true);
    T(s,"共享派梯评分 → 合法mask → argmax",652,458,510,42,22,C.ink);
    T(s,"+768 参数",620,552,560,50,32,C.teal,true);
    note(s,"仅使用已到达任务；没有固定候选系数、教师动作、行为克隆或规则兜底。模型共427399参数。");
  } else if(n===6) {
    s=base(p,n,"TRAINING","事件时间、完整服务与开发选模贯穿训练");
    const items=[["环境采样","4环境 × 128步"],["时间GAE","按Δt折扣"],["PPO更新","clip=0.2 · 4 epoch"],["开发选模","先完整与约束，再等待"]];
    items.forEach((v,i)=>{const x=64+i*292;node(s,x,230,264,160,...v);if(i<3)A(s,x+268,302,20,15);});
    T(s,"原课程权重 → 六列补零迁移 → 200000步微调",64,438,1120,47,29,C.teal,true);
    T(s,"提交801：选中143360步；802/803共同保留",64,500,1120,44,26,C.ink,true);
    T(s,"gamma(Δt)=0.99^(Δt/10)；lambda(Δt)=0.95^(Δt/10)",64,556,1120,38,22,C.muted);
    note(s,"三个独立微调seed共享同一已训练初始化，不是独立预训练；本次提交整理不重新训练。");
  } else if(n===7) {
    s=base(p,n,"DEVELOPMENT EVIDENCE","新增输入让三seed平均等待下降43.46%");
    const rows=[["ETA",35.8772,C.muted],["ETA-Zone",25.9598,C.muted],["轮询",25.6363,C.muted],["原PPO",24.4030,C.amber],["后果PPO · 3 seed",13.7975,C.teal],["固定规则 · 非RL",11.3546,"#9EAC9D"]];
    rows.forEach(([label,value,color],i)=>{const y=215+i*61;T(s,label,64,y,250,40,22,C.ink,i===4);R(s,333,y+3,value/36*735,34,color);T(s,value.toFixed(2),1082,y,130,38,24,color,true);});
    note(s,"平均等待/秒，越低越好；同一135组开发客流，参与选模。原数据：reports/candidate-ppo。");
  } else if(n===8) {
    s=base(p,n,"DEPLOYED CHECKPOINT","提交801降低等待，同时接近 ETA 的运行距离");
    const stats=[[64,"13.1399","平均等待 / 秒"],[460,"33.0974","P95等待 / 秒"],[856,"147.9481","运行距离 / 层"]];
    stats.forEach(([x,value,label])=>{T(s,value,x,242,350,95,53,C.teal,true);T(s,label,x,344,350,42,25,C.muted);});
    R(s,64,425,1150,2,C.light);
    T(s,"ETA参照",64,461,270,42,25,C.ink,true);T(s,"35.8772秒",360,461,280,42,25,C.muted);T(s,"132.7466秒",656,461,280,42,25,C.muted);T(s,"147.1185层",955,461,260,42,25,C.muted);
    T(s,"801距离相对ETA仅 +0.56%；这是单模型开发结果",64,540,1145,52,29,C.teal,true);
    note(s,"单801与三seed均值分别报告；开发可行且等待最低的既有检查点用于演示，不在新测试上挑模型。");
  } else if(n===9) {
    s=base(p,n,"LIVE PRODUCT","从真实输入到完整服务，页面与归档一致");
    await I(s,"06_井道局部.png",590,198,625,395);
    T(s,"26 / 26",64,236,500,88,62,C.teal,true);T(s,"位乘客完成服务",64,325,480,40,25,C.muted);
    T(s,"10.4068 秒",64,398,500,63,38,C.ink,true);T(s,"单次平均等待 · 距离109层",64,467,500,42,24,C.muted);
    T(s,"配置 → 运行 → 暂停观察 → 导出",64,551,540,38,23,C.ink,true);
    note(s,"12F4E、早高峰、12人/分钟、120秒、seed9001；历史演示输入，不代替研究汇总或盲测。");
  } else if(n===10) {
    s=base(p,n,"ABLATION","输入置零后性能退化，网络实际使用了新信息");
    await I(s,"08_训练曲线局部.png",64,240,670,320);
    T(s,"同一模型 · 等待/秒",790,215,425,42,24,C.ink,true);
    [["801","13.14","22.71"],["802","14.92","24.05"],["803","13.33","23.18"]].forEach((r,i)=>{
      const y=299+i*75;T(s,r[0],790,y,80,40,24,C.muted);T(s,r[1],880,y,130,42,29,C.teal,true);T(s,"→",1014,y,45,42,27,C.muted);T(s,r[2],1072,y,140,42,29,C.coral,true);
    });
    T(s,"真实训练曲线 · 801",64,564,660,36,23,C.muted);
    note(s,"置零为分布外诊断，不是独立算法成绩；曲线来自随仓库提供的updates.csv与validation.csv。");
  } else if(n===11) {
    s=base(p,n,"VERIFICATION","软件验证与原始重算共同支撑可复现交付");
    [[64,"90","Python测试"],[460,"2","前端单元测试"],[856,"5","浏览器端到端测试"]].forEach(([x,v,l])=>{T(s,v,x,240,350,98,74,C.teal,true);T(s,l,x,352,350,42,25,C.muted);});
    R(s,64,435,1150,2,C.light);
    T(s,"1892 次运行 / 61813 条乘客记录独立重算",64,475,1140,48,31,C.ink,true);
    T(s,"SHA验证 · 干净目录安装 · 幂等 · 拒绝覆盖改动文件",64,545,1140,40,25,C.muted);
    note(s,"当前质量10/10通过；研究审计不增加独立客流样本数，远程Linux CI尚未执行。");
  } else if(n===12) {
    s=base(p,n,"HANDOVER & LIMITS","冻结课程交付，同时保留研究边界",true);
    T(s,"dev",64,215,330,72,48,C.white,true);T(s,"bc0fef6",64,294,460,50,27,"#B9D0D0");
    T(s,"原开发源码 + 12份注册模型\n原始档案清单；10GB数据留本机",64,364,525,112,24,"#B9D0D0");
    T(s,"main",700,215,480,72,48,C.white,true);T(s,"源程序 / 模型 / 两页需求 / 报告 / PPT",700,300,500,92,25,"#B9D0D0");
    T(s,"课程交付已认可；研究严格门槛尚未全过",64,508,1150,44,27,"#F0B76C",true);
    T(s,"规则参照仍更快；803距离超限；确认与最终未打开",64,565,1150,43,24,"#B9D0D0");
  }
  return s;
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  const plan={mode:"create",profile:"engineering-platform",slides:12,thesis:"公开后果输入帮助PPO学习插单外部性；开发收益明确，独立泛化与严格目标分别披露。",font:"PingFang SC",palette:C,proofs:["hand-calculated externality","module architecture","230→128→1 policy","training path","editable wait bars","real UI","feature ablation","full QA"],source:"reports/candidate-ppo + assets/release + actual browser capture"};
  for(const folder of ["slides","preview","layout","qa"])await fs.mkdir(path.join(workspace,folder),{recursive:true});
  for(const filename of ["profile-plan.txt","source-notes.txt","reference-audit.txt","claim-spine.txt","design-system.txt","contact-sheet-plan.txt"])await fs.writeFile(path.join(workspace,filename),JSON.stringify(plan,null,2));
  const data={references:JSON.parse(await fs.readFile(path.join(project,"reports/candidate-ppo/references.json"))),development:JSON.parse(await fs.readFile(path.join(project,"reports/candidate-ppo/development.json")))};
  await fs.writeFile(path.join(workspace,"data.json"),JSON.stringify(data,null,2));
  for(let n=1;n<=12;n++)await fs.writeFile(path.join(workspace,"slides",`slide${String(n).padStart(2,"0")}.mjs`),`import {render} from ${JSON.stringify(pathToFileURL(fileURLToPath(import.meta.url)).href)};\nexport async function slide${String(n).padStart(2,"0")}(p,ctx){return render(${n},p,ctx);}\n`);
  console.log(workspace);
}
