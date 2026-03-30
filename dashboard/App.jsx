import { useState, useEffect, useRef, useCallback } from "react";

// ─── Design tokens ─────────────────────────────────────────────────────────
const G = {
  bg:"#0d1117", canvas:"#010409", surface:"#161b22", surfaceHov:"#1c2128",
  border:"#21262d", borderMid:"#30363d",
  text:"#e6edf3", textSec:"#8b949e", textMut:"#484f58",
  green:"#3fb950", greenBg:"#0f2419", red:"#f85149", redBg:"#1a0800",
  blue:"#58a6ff", blueDim:"#388bfd", yellow:"#d29922", yellowBg:"#1a1000",
  purple:"#bc8cff", orange:"#f0883e", teal:"#39d353", pink:"#ec4899",
  cyan:"#00d4ff", amber:"#ffaa00",
};

const BACKEND = "http://localhost:8000";
const VERSION = "v5.0.0";
const AUTHOR  = "Rajesh Nemani";

// ─── Indian market charges ─────────────────────────────────────────────────
const CHARGES = {
  brokerage:      20,
  stt_delivery:   0.001,
  stt_intraday:   0.00025,
  exchange_nse:   0.0000345,
  sebi:           0.000001,
  stamp_delivery: 0.00015,
  stamp_intraday: 0.00003,
  dp_charge:      15.93,
  gst_rate:       0.18,
};

function calcNetPnl(pos) {
  const { entryPrice=0, cp=0, qty=0, tt="SWING" } = pos;
  const isIntraday = tt === "INTRADAY";
  const turnover   = (entryPrice + cp) * qty;
  const grossPnl   = (cp - entryPrice) * qty;
  const brok  = CHARGES.brokerage * 2;
  const stt   = isIntraday ? cp*qty*CHARGES.stt_intraday : turnover*CHARGES.stt_delivery;
  const exc   = turnover * CHARGES.exchange_nse;
  const sebi  = turnover * CHARGES.sebi;
  const stamp = isIntraday ? entryPrice*qty*CHARGES.stamp_intraday : entryPrice*qty*CHARGES.stamp_delivery;
  const dp    = isIntraday ? 0 : CHARGES.dp_charge;
  const gst   = (brok + exc) * CHARGES.gst_rate;
  const totalCharges = brok + stt + exc + sebi + stamp + dp + gst;
  const netPnl = grossPnl - totalCharges;
  const netPct = entryPrice > 0 ? (netPnl / (entryPrice * qty)) * 100 : 0;
  return { grossPnl, netPnl, netPct, totalCharges, brok, stt, exc, sebi, stamp, dp, gst };
}

// ─── REGIME config ─────────────────────────────────────────────────────────
const REGIME = {
  TRENDING: { color:G.green,  icon:"↑", label:"Trending" },
  SIDEWAYS: { color:G.yellow, icon:"↔", label:"Sideways" },
  VOLATILE: { color:G.red,    icon:"⚡", label:"Volatile" },
  RISK_OFF: { color:G.purple, icon:"⛔", label:"Risk Off" },
};
const TT_COLOR = { INTRADAY:G.orange, SHORT_TERM:G.blue, SWING:G.purple, LONG_TERM:G.green };

// ─── Rating ─────────────────────────────────────────────────────────────────
function computeRating(confidence, buyCount, sellCount, sigmaScore) {
  const net = buyCount - sellCount;
  const score = confidence*0.4 + (sigmaScore||0)*0.4 + (net/Math.max(buyCount+sellCount,1))*0.2;
  if (score>=0.80&&net>=4) return {label:"STRONG BUY",  color:G.green,  icon:"⬆⬆", bg:G.greenBg};
  if (score>=0.62&&net>=2) return {label:"BUY",         color:G.teal,   icon:"⬆",  bg:"#0a1f14"};
  if (score>=0.45||net===0)return {label:"HOLD",        color:G.yellow, icon:"→",  bg:G.yellowBg};
  if (score>=0.28||net<=-2)return {label:"SELL",        color:G.orange, icon:"⬇",  bg:"#1a0e00"};
  return                         {label:"STRONG SELL", color:G.red,    icon:"⬇⬇", bg:G.redBg};
}

// ─── Indicators ─────────────────────────────────────────────────────────────
function ema(arr, p) {
  const k=2/(p+1), out=new Float64Array(arr.length);
  out[0]=arr[0];
  for(let i=1;i<arr.length;i++) out[i]=arr[i]*k+out[i-1]*(1-k);
  return out;
}

function indicators(candles) {
  if(!candles||candles.length<15) return null;
  const n=candles.length;
  const c=candles.map(x=>x.close??x.Close??0);
  const h=candles.map(x=>x.high??x.High??0);
  const l=candles.map(x=>x.low??x.Low??0);
  const v=candles.map(x=>x.volume??x.Volume??0);
  const e9=ema(c,9),e20=ema(c,20),e50=ema(c,50);
  const macdLine=e9.map((v9,i)=>v9-e20[i]);
  const macdSig=ema(Array.from(macdLine),9);
  const macd=Array.from(macdLine);
  const mh=macd.map((v,i)=>v-macdSig[i]);
  const gains=[],losses=[];
  for(let i=1;i<n;i++){const d=c[i]-c[i-1];gains.push(Math.max(0,d));losses.push(Math.max(0,-d));}
  const ag=ema(gains,14),al=ema(losses,14);
  const rsi=ag.map((g,i)=>{const rs=al[i]===0?100:g/al[i];return 100-100/(1+rs);});
  const tr=h.map((hi,i)=>Math.max(hi-l[i],Math.abs(hi-(c[i-1]??c[i])),Math.abs(l[i]-(c[i-1]??c[i]))));
  const atr=Array.from(ema(tr,14));
  const pdm=h.map((hi,i)=>i===0?0:Math.max(0,hi-h[i-1]));
  const ndm=l.map((li,i)=>i===0?0:Math.max(0,l[i-1]-li));
  const pdi=ema(pdm,14).map((v,i)=>atr[i]>0?v/atr[i]*100:0);
  const ndi=ema(ndm,14).map((v,i)=>atr[i]>0?v/atr[i]*100:0);
  const dx=pdi.map((p,i)=>{const s=p+ndi[i];return s>0?Math.abs(p-ndi[i])/s*100:0;});
  const adx=Array.from(ema(dx,14));
  const sma20=c.map((_,i)=>i<19?c[i]:c.slice(i-19,i+1).reduce((a,b)=>a+b,0)/20);
  const std20=c.map((_,i)=>{if(i<19)return 0;const sl=c.slice(i-19,i+1),m=sma20[i];return Math.sqrt(sl.reduce((a,b)=>a+(b-m)**2,0)/20);});
  const bbu=sma20.map((m,i)=>m+2*std20[i]);
  const bbl=sma20.map((m,i)=>m-2*std20[i]);
  const bbw=bbu.map((u,i)=>sma20[i]>0?(u-bbl[i])/sma20[i]:0);
  const bbpb=c.map((ci,i)=>(bbu[i]-bbl[i])>0?(ci-bbl[i])/(bbu[i]-bbl[i]):0.5);
  const cumV=v.reduce((a,vi,i)=>{a.push((a[i-1]??0)+vi);return a;},[]);
  const cumPV=c.map((ci,i)=>ci*v[i]).reduce((a,pvi,i)=>{a.push((a[i-1]??0)+pvi);return a;},[]);
  const vwap=cumPV.map((pv,i)=>cumV[i]>0?pv/cumV[i]:c[i]);
  const loK=14,sk=c.map((_,i)=>{if(i<loK-1)return 50;const sl=l.slice(i-loK+1,i+1),sh=h.slice(i-loK+1,i+1);const lo=Math.min(...sl),hi=Math.max(...sh);return hi===lo?50:(c[i]-lo)/(hi-lo)*100;});
  const sd=Array.from(ema(sk,3));
  return {c,h,l,v,n,e9,e20,e50,atr,rsi,macd,mh,adx,bbu,bbl,bbw,bbpb,vwap,sk,sd,sma20};
}

// ─── Candle patterns ────────────────────────────────────────────────────────
function detectCandlePatterns(candles) {
  if(!candles||candles.length<3) return [];
  const c=candles.map(x=>x.close??x.Close??0);
  const o=candles.map(x=>x.open??x.Open??c[candles.indexOf(x)]);
  const h=candles.map(x=>x.high??x.High??0);
  const l=candles.map(x=>x.low??x.Low??0);
  const n=c.length,i=n-1,p=n-2;
  const body=idx=>Math.abs(c[idx]-o[idx]);
  const range=idx=>h[idx]-l[idx];
  const isBull=idx=>c[idx]>o[idx];
  const pats=[];
  if(body(i)<range(i)*0.1)
    pats.push({name:"Doji",icon:"✚",type:"neutral",desc:"Opening and closing prices nearly equal — perfect indecision. A Doji after a strong move often signals exhaustion. Wait for the next candle to confirm direction before entering. Most reliable when appearing near support/resistance levels."});
  if(isBull(i)&&body(i)>range(i)*0.6&&(h[i]-c[i])<body(i)*0.1&&(o[i]-l[i])<body(i)*0.15)
    pats.push({name:"Bullish Marubozu",icon:"🟢",type:"bull",desc:"A full green candle with almost no wicks — buyers dominated the entire session from open to close. This is a high-confidence bullish signal especially on volume. Often the start of a new leg up. TITAN's T1/T2 strategies look for these."});
  if(!isBull(i)&&body(i)>range(i)*0.6&&(l[i]-c[i])<body(i)*0.1&&(h[i]-o[i])<body(i)*0.15)
    pats.push({name:"Bearish Marubozu",icon:"🔴",type:"bear",desc:"Full red candle, no wicks — sellers in complete control. Exit longs immediately. This candle type has high follow-through probability. GUARDIAN uses this as a partial exit signal."});
  if((h[i]-Math.max(o[i],c[i]))>body(i)*2&&body(i)<range(i)*0.3)
    pats.push({name:"Shooting Star",icon:"💫",type:"bear",desc:"Small body near the low with a long upper wick — buyers pushed price up but sellers rejected the move aggressively. Classic reversal signal at resistance. Bearish on next open below the body. Most effective after 3+ up candles."});
  if((Math.min(o[i],c[i])-l[i])>body(i)*2&&body(i)<range(i)*0.3)
    pats.push({name:"Hammer",icon:"🔨",type:"bull",desc:"Small body near the high with a long lower wick — sellers pushed price down but buyers stepped in strongly. Classic demand-zone reversal signal. Most effective after 3+ down candles or at support. Entry on next green candle open."});
  if(n>=3&&!isBull(n-3)&&body(n-2)<body(n-3)*0.5&&isBull(i)&&c[i]>(o[n-3]+c[n-3])/2)
    pats.push({name:"Morning Star",icon:"🌅",type:"bull",desc:"Three-candle bullish reversal: Day 1 large red candle (sellers). Day 2 small body (indecision). Day 3 large green candle closing above Day 1 midpoint. One of the most reliable reversal signals. Target = prior resistance."});
  if(n>=3&&isBull(n-3)&&body(n-2)<body(n-3)*0.5&&!isBull(i)&&c[i]<(o[n-3]+c[n-3])/2)
    pats.push({name:"Evening Star",icon:"🌆",type:"bear",desc:"Three-candle bearish reversal — mirror of Morning Star. Day 1 large green. Day 2 small body gap up. Day 3 large red closing below Day 1 midpoint. Exit longs."});
  if(isBull(i)&&body(i)>range(i)*0.7)
    pats.push({name:"Strong Bull Candle",icon:"💪",type:"bull",desc:"Momentum candle with body >70% of range. Buyers dominated the entire session. High follow-through probability especially with elevated volume."});
  if(h[i]<h[p]&&l[i]>l[p])
    pats.push({name:"Inside Bar",icon:"📦",type:"neutral",desc:"Current candle's range is within the prior candle's range. Volatility compression. Breakout above high = bullish, below low = bearish."});
  return pats;
}

// ─── Volume analysis ────────────────────────────────────────────────────────
function computeVolumeAnalysis(candles) {
  if(!candles||candles.length<5) return null;
  const c=candles.map(x=>x.close??x.Close??0);
  const v=candles.map(x=>x.volume??x.Volume??0);
  const n=c.length;
  const v20avg=v.slice(-20).reduce((a,b)=>a+b,0)/Math.min(20,n);
  const v5avg=v.slice(-5).reduce((a,b)=>a+b,0)/5;
  const lastVol=v[n-1];
  const volRatio=v20avg>0?lastVol/v20avg:1;
  const obvDir=c.map((ci,i)=>i===0?0:ci>c[i-1]?1:ci<c[i-1]?-1:0);
  const obv=v.map((vi,i)=>vi*obvDir[i]).reduce((acc,val,i)=>{acc.push((acc[i-1]??0)+val);return acc;},[]);
  const obv5avg=obv.length>5?obv.slice(-5).reduce((a,b)=>a+b,0)/5:obv[obv.length-1]??0;
  const obvTrend=obv[n-1]>obv5avg?"RISING":"FALLING";
  const priceUp=c[n-1]>c[n-2];
  const volUp=lastVol>v5avg;
  const pvConfirm=(priceUp&&volUp)||(!priceUp&&!volUp);
  const price5chg=Math.abs(c[n-1]-c[Math.max(0,n-5)])/(c[Math.max(0,n-5)]||1);
  const accumulation=price5chg<0.02&&volRatio>1.3&&obvTrend==="RISING";
  const distribution=price5chg<0.02&&volRatio>1.3&&obvTrend==="FALLING";
  return {volRatio:+volRatio.toFixed(2),obvTrend,pvConfirm,accumulation,distribution,
    lastVol:Math.round(lastVol),v20avg:Math.round(v20avg),priceUp,volUp};
}

// ─── TITAN signals ───────────────────────────────────────────────────────────
function titanSignals(candles, regime) {
  const ind=indicators(candles);
  if(!ind) return [];
  const {c,h,l,v,n,e9,e20,e50,atr,rsi,macd,mh,adx,bbu,bbl,bbw,bbpb,vwap,sk,sd}=ind;
  const i=n-1,p=n-2;
  const out=[];
  const push=(id,cat,sig,conf,reason)=>{if(sig!==0)out.push({id,category:cat,signal:sig,confidence:+conf.toFixed(2),reason});};
  if(e20[i]>e50[i]&&e20[p]<=e50[p])      push("T1","Trend",1,0.78,"EMA20 crossed above EMA50 — bull cross");
  else if(e20[i]<e50[i]&&e20[p]>=e50[p]) push("T1","Trend",-1,0.78,"EMA20 crossed below EMA50 — bear cross");
  else push("T1","Trend",e20[i]>e50[i]?1:-1,0.44,`EMA20 ${e20[i]>e50[i]?"above":"below"} EMA50`);
  if(e9[i]>e20[i]&&e20[i]>e50[i])        push("T2","Trend",1,0.80,"Triple EMA bull stack 9>20>50");
  else if(e9[i]<e20[i]&&e20[i]<e50[i])   push("T2","Trend",-1,0.80,"Triple EMA bear stack 9<20<50");
  if(mh[i]>0&&mh[p]<=0)                  push("T4","Trend",1,0.75,"MACD histogram turned positive");
  else if(mh[i]<0&&mh[p]>=0)             push("T4","Trend",-1,0.75,"MACD histogram turned negative");
  if(adx[i]>25)                           push("T5","Trend",macd[i]>0?1:-1,Math.min(0.90,0.54+adx[i]/100),`ADX=${adx[i].toFixed(0)} strong trend`);
  const hi20=Math.max(...h.slice(Math.max(0,i-19),i+1)),lo20=Math.min(...l.slice(Math.max(0,i-19),i+1));
  if(c[i]>=hi20*0.998)        push("T7","Trend",1,0.82,`20-bar Donchian high ${hi20.toFixed(0)}`);
  else if(c[i]<=lo20*1.002)   push("T7","Trend",-1,0.82,`20-bar Donchian low ${lo20.toFixed(0)}`);
  if(rsi[i]<30&&rsi[p]>=30)   push("M1","MeanRev",1,0.72,"RSI crossed below 30 — oversold");
  else if(rsi[i]>70&&rsi[p]<=70) push("M1","MeanRev",-1,0.72,"RSI crossed above 70 — overbought");
  if(c[i]<bbl[i]&&c[p]>=bbl[p]) push("M2","MeanRev",1,0.68,"Price crossed below lower Bollinger Band — bounce likely");
  else if(c[i]>bbu[i]&&c[p]<=bbu[p]) push("M2","MeanRev",-1,0.68,"Price crossed above upper BB — mean reversion likely");
  if(bbw[i]<0.02&&bbw[p]>=0.02)  push("M3","MeanRev",macd[i]>0?1:-1,0.65,"BB squeeze — volatility contraction breakout pending");
  if(c[i]>vwap[i]&&c[p]<=vwap[p]) push("V1","VWAP",1,0.71,"Price reclaimed VWAP — institutional buy zone");
  else if(c[i]<vwap[i]&&c[p]>=vwap[p]) push("V1","VWAP",-1,0.71,"Price lost VWAP — institutional sell pressure");
  const zscore=(c[i]-(ind.sma20?.[i]??c[i]))/(atr[i]||1);
  if(zscore<-2) push("S1","Statistical",1,0.70,`Z-score ${zscore.toFixed(2)} — statistically oversold`);
  else if(zscore>2) push("S1","Statistical",-1,0.70,`Z-score ${zscore.toFixed(2)} — statistically overbought`);
  const ok=["Trend","Breakout","MeanRev","VWAP","Statistical"];
  return out.filter(s=>ok.includes(s.category)).sort((a,b)=>b.confidence-a.confidence);
}

// ─── NSE Universe ────────────────────────────────────────────────────────────
// Demo fallback universe — only used if backend API fails
const DEMO_UNIVERSE=[
  {s:"BHARTIHEXA",n:"Bharti Hexacom",sec:"Telecom",base:1100},
  {s:"ACMESOLAR",n:"ACME Solar",sec:"Energy",base:250},
];

// ─── Demo news generator ──────────────────────────────────────────────────
function generateDemoNews(picks) {
  if(!picks?.length) return [];
  const now=new Date();
  const TEMPLATES=[
    {sent:"BULLISH",score:0.72,src:"ET Markets",tmpl:(s,n)=>`${n} Q3 results beat estimates; PAT up 18% YoY — analysts raise target`},
    {sent:"BULLISH",score:0.61,src:"Moneycontrol",tmpl:(s,n)=>`FII net buyers in ${n} for third consecutive session`},
    {sent:"BEARISH",score:-0.55,src:"Business Standard",tmpl:(s,n)=>`${n} faces margin pressure as raw material costs rise 12%`},
    {sent:"NEUTRAL",score:0.1,src:"Reuters",tmpl:(s,n)=>`${n} announces board meeting to discuss fund raise`},
    {sent:"BULLISH",score:0.80,src:"NSE",tmpl:(s,n)=>`${s} added to MSCI India index — passive inflows expected`},
  ];
  return picks.flatMap((p,pi)=>
    TEMPLATES.slice(0,2).map((t,ti)=>{
      const mins=(pi*17+ti*11)%55;
      return {
        id:`news-${p.s}-${ti}`,symbol:p.s,related:[],
        headline:t.tmpl(p.s,p.n??p.s),
        summary:`Analysis by AlphaZero sentiment engine.`,
        sentiment:t.sent,sentiment_score:t.score,source:t.src,
        time:`${now.getHours()}:${String(now.getMinutes()-mins<0?0:now.getMinutes()-mins).padStart(2,"0")}`,
        impact:`${t.sent.includes("BULL")?"Positive for share price":"Negative short-term pressure"}. ${p.s} SIGMA score adjusted.`,
        confirmation:t.score>0.5?[t.src,"AlphaZero AI"]:t.score<-0.3?[t.src]:[],
      };
    })
  );
}

// ─── Shared atoms ─────────────────────────────────────────────────────────
const Tag=({label,color,bg})=>(
  <span style={{background:bg??color+"1a",border:`1px solid ${color}44`,
    color,padding:"1px 8px",borderRadius:20,fontSize:10,fontWeight:600,
    display:"inline-block",whiteSpace:"nowrap"}}>{label}</span>
);
const Num=({n,color})=>(
  <span style={{background:(color??G.blue)+"1a",color:color??G.blue,
    borderRadius:20,padding:"0 7px",fontSize:11,fontWeight:700,
    minWidth:18,display:"inline-block",textAlign:"center"}}>{n}</span>
);
const Empty=({icon,title,sub})=>(
  <div style={{display:"flex",flexDirection:"column",alignItems:"center",padding:"64px 20px",gap:10}}>
    <span style={{fontSize:28}}>{icon}</span>
    <div style={{color:G.textSec,fontSize:13,fontWeight:500}}>{title}</div>
    <div style={{color:G.textMut,fontSize:11,textAlign:"center",maxWidth:280}}>{sub}</div>
  </div>
);
function KpiBar({value,max=1,color}) {
  return (
    <div style={{background:G.border,borderRadius:3,height:4,overflow:"hidden"}}>
      <div style={{width:`${Math.min(100,(value/max)*100)}%`,height:"100%",
        background:color??G.green,borderRadius:3,transition:"width .6s ease"}}/>
    </div>
  );
}
function RatingBadge({rating,size="md"}) {
  const sz=size==="lg"?{fontSize:13,padding:"4px 14px"}:{fontSize:10,padding:"2px 8px"};
  return (
    <span style={{...sz,background:rating.bg,border:`1px solid ${rating.color}55`,
      color:rating.color,borderRadius:20,fontWeight:700,letterSpacing:".04em",whiteSpace:"nowrap"}}>
      {rating.icon} {rating.label}
    </span>
  );
}

// ─── ConnBanner ────────────────────────────────────────────────────────────
function ConnBanner({status}) {
  if(status==="live") return null;
  const cfg={
    connecting:{color:G.yellow,icon:"⟳",msg:"Connecting to backend…"},
    offline:{color:G.orange,icon:"⚠",msg:"Backend offline — run: uvicorn dashboard.backend:app --port 8000"},
  };
  const {color,icon,msg}=cfg[status]??cfg.offline;
  return (
    <div style={{background:color+"12",borderBottom:`1px solid ${color}30`,
      padding:"7px 24px",fontSize:11,color,display:"flex",gap:8,alignItems:"center"}}>
      <span style={{fontWeight:700}}>{icon}</span><span>{msg}</span>
    </div>
  );
}

// ─── TopNav ───────────────────────────────────────────────────────────────
function TopNav({regime,indices,paperPnl,time,connStatus,mode,initial_capital}) {
  const R=REGIME[regime]??REGIME.TRENDING;
  const nChange=(indices.nifty??0)-24150,bChange=(indices.banknifty??0)-51840;
  return (
    <div style={{background:G.surface,borderBottom:`1px solid ${G.border}`,
      padding:"0 24px",height:54,display:"flex",alignItems:"center",gap:16,width:"100%"}}>
      <div style={{display:"flex",alignItems:"center",gap:8}}>
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none">
          <polygon points="12,2 22,20 2,20" fill={G.green} opacity=".9"/>
          <polygon points="12,6 19,19 5,19" fill={G.bg}/>
          <polygon points="12,10 16,18 8,18" fill={G.green}/>
        </svg>
        <span style={{color:G.text,fontWeight:700,fontSize:14,fontFamily:"monospace",letterSpacing:".06em"}}>AlphaZero Capital</span>
        <Tag label={mode==="LIVE"?"🔴 LIVE":"📄 PAPER"} color={mode==="LIVE"?G.red:G.yellow}/>
      </div>
      <div style={{width:1,height:20,background:G.border}}/>
      <div style={{display:"flex",gap:16,alignItems:"center"}}>
        {[["NIFTY",indices.nifty,nChange],["BANKNIFTY",indices.banknifty,bChange]].map(([label,val,chg])=>(
          <div key={label} style={{display:"flex",gap:4,alignItems:"baseline"}}>
            <span style={{color:G.textMut,fontSize:10,fontFamily:"monospace"}}>{label}</span>
            <span style={{color:G.text,fontSize:12,fontWeight:700,fontFamily:"monospace"}}>{(val||0).toLocaleString("en-IN",{maximumFractionDigits:0})}</span>
            <span style={{color:chg>=0?G.green:G.red,fontSize:10,fontFamily:"monospace"}}>{chg>=0?"▲":"▼"}{Math.abs(chg||0).toFixed(0)}</span>
          </div>
        ))}
      </div>
      <Tag label={`${R.icon} ${R.label}`} color={R.color}/>
      <span style={{color:G.textSec,fontSize:11,fontFamily:"monospace"}}>
        VIX <span style={{color:(indices.vix??0)>22?G.red:G.green,fontWeight:700}}>{(indices.vix??14.2).toFixed(1)}</span>
      </span>
      <div style={{flex:1}}/>
      <div style={{textAlign:"right",borderRight:`1px solid ${G.border}`,paddingRight:16}}>
        <div style={{color:G.textMut,fontSize:9,fontFamily:"monospace",letterSpacing:".08em"}}>TOTAL CAPITAL</div>
        <div style={{color:G.textSec,fontSize:13,fontWeight:700,fontFamily:"monospace"}}>
          ₹{((mode==="LIVE"?initial_capital:1000000)??0).toLocaleString("en-IN",{maximumFractionDigits:0})}
        </div>
      </div>
      <div style={{textAlign:"right"}}>
        <div style={{color:G.textMut,fontSize:9,fontFamily:"monospace",letterSpacing:".08em"}}>NET P&L (after charges)</div>
        <div style={{color:(paperPnl??0)>=0?G.green:G.red,fontSize:13,fontWeight:700,fontFamily:"monospace"}}>
          {(paperPnl??0)>=0?"+":"-"}₹{Math.abs(paperPnl??0).toLocaleString("en-IN",{maximumFractionDigits:0})}
        </div>
      </div>
      <div style={{display:"flex",alignItems:"center",gap:6}}>
        <div style={{width:6,height:6,borderRadius:"50%",
          background:indices.market_open?G.green:G.textMut,
          boxShadow:indices.market_open?`0 0 8px ${G.green}`:"none"}}/>
        <span style={{color:G.textMut,fontSize:11,fontFamily:"monospace"}}>
          {time.toLocaleTimeString("en-IN",{hour12:false})} IST
        </span>
      </div>
    </div>
  );
}

// ─── TabBar ───────────────────────────────────────────────────────────────
function TabBar({active,setActive,counts}) {
  const tabs=[
    {id:"overview",label:"Overview"},
    {id:"positions",label:"Positions",badge:counts.pos},
    {id:"signals",label:"Signals",badge:counts.sigs},
    {id:"news",label:"News",badge:counts.news},
    {id:"macro",label:"External Factors"},
    {id:"performance",label:"Performance"},
    {id:"evaluation",label:"Evaluation",badge:counts.eval},
    {id:"agents",label:"Agents"},
  ];
  return (
    <div style={{background:G.surface,borderBottom:`1px solid ${G.border}`,padding:"0 24px",display:"flex",overflowX:"auto",width:"100%",flexShrink:0}}>
      {tabs.map(t=>(
        <button key={t.id} onClick={()=>setActive(t.id)} style={{
          background:"none",border:"none",cursor:"pointer",
          borderBottom:active===t.id?`2px solid ${G.blueDim}`:"2px solid transparent",
          color:active===t.id?G.text:G.textSec,
          padding:"10px 14px",fontSize:12,fontWeight:active===t.id?600:400,
          marginBottom:-1,display:"flex",alignItems:"center",gap:6,whiteSpace:"nowrap",
          transition:"color .15s",
        }}
        onMouseEnter={e=>{if(active!==t.id)e.currentTarget.style.color=G.text;}}
        onMouseLeave={e=>{if(active!==t.id)e.currentTarget.style.color=G.textSec;}}>
          {t.label}
          {t.badge!=null&&t.badge>0&&<Num n={t.badge}/>}
        </button>
      ))}
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════════════
// TAB: OVERVIEW
// ═══════════════════════════════════════════════════════════════════════════
function OverviewTab({picks:rawPicks,positions:rawPositions,allSigs:rawSigs,evalStats,indices,candleCache,news,onStock}) {
  const positions = Array.isArray(rawPositions) ? rawPositions : Object.values(rawPositions || {});
  const picks = Array.isArray(rawPicks) ? rawPicks : Object.values(rawPicks || {});
  const allSigs = Array.isArray(rawSigs) ? rawSigs : Object.values(rawSigs || {});

  const open=positions.filter(p=>p.status==="OPEN");
  const netPnl=open.reduce((s,p)=>s+calcNetPnl(p).netPnl,0);
  const grossPnl=open.reduce((s,p)=>s+calcNetPnl(p).grossPnl,0);
  const buy=allSigs.filter(s=>s.signal===1).length;
  const sell=allSigs.filter(s=>s.signal===-1).length;
  const wr=evalStats?.win_rate??0;
  return (
    <div style={{display:"flex",flexDirection:"column",gap:24}}>
      <div style={{display:"grid",gridTemplateColumns:"repeat(4,1fr)",gap:12}}>
        {[
          {label:"Open Positions",val:open.length,sub:`${10-open.length} slots free`,color:G.blue},
          {label:"Gross P&L",val:`${grossPnl>=0?"+":""}₹${Math.abs(grossPnl).toLocaleString("en-IN",{maximumFractionDigits:0})}`,sub:"before charges",color:grossPnl>=0?G.green:G.red},
          {label:"Net P&L (after charges)",val:`${netPnl>=0?"+":""}₹${Math.abs(netPnl).toLocaleString("en-IN",{maximumFractionDigits:0})}`,sub:"STT+Brok+GST+DP incl.",color:netPnl>=0?G.teal:G.red},
          {label:"Agent Win Rate",val:`${(wr*100).toFixed(1)}%`,sub:`${evalStats?.total_evaluated??0} evaluated`,color:wr>=0.55?G.green:wr>=0.40?G.yellow:G.red},
        ].map(({label,val,sub,color})=>(
          <div key={label} style={{background:G.surface,border:`1px solid ${G.border}`,borderRadius:8,padding:"16px 18px"}}>
            <div style={{color:G.textSec,fontSize:11,marginBottom:8}}>{label}</div>
            <div style={{color,fontSize:19,fontWeight:700,fontFamily:"monospace",marginBottom:4}}>{val}</div>
            <div style={{color:G.textMut,fontSize:10}}>{sub}</div>
          </div>
        ))}
      </div>

      <div style={{background:G.surface,border:`1px solid ${G.border}`,borderRadius:8,overflow:"hidden"}}>
        <div style={{padding:"12px 18px",borderBottom:`1px solid ${G.border}`,display:"flex",justifyContent:"space-between",alignItems:"center"}}>
          <div style={{display:"flex",alignItems:"center",gap:8}}>
            <span style={{color:G.text,fontSize:13,fontWeight:600}}>APEX Selected Stocks</span>
            <Tag label="Click for full analysis" color={G.blue}/>
          </div>
          <span style={{color:G.textMut,fontSize:10}}>Dynamic scan · 40s refresh · {NSE_UNIVERSE.length} stocks</span>
        </div>
        <div style={{display:"grid",gridTemplateColumns:"repeat(5,1fr)"}}>
          {picks.length===0?Array(5).fill(null).map((_,i)=>(
            <div key={i} style={{padding:"20px",display:"flex",alignItems:"center",justifyContent:"center",borderRight:i<4?`1px solid ${G.border}`:"none"}}>
              <span style={{color:G.textMut,fontSize:11}}>Scanning…</span>
            </div>
          )):picks.map((s,i)=>{
            const candles=candleCache[s.s];
            const price=candles?.length?(candles[candles.length-1].close??candles[candles.length-1].Close??s.base):s.price??s.base;
            const first=candles?.[0];
            const chg=first?(price-(first.close??first.Close??price))/(first.close??first.Close??price)*100:0;
            const rr=s.entry&&s.sl&&s.target?(s.target-s.entry)/(s.entry-s.sl):0;
            const sigs=candles?titanSignals(candles,s.regime??"TRENDING"):[];
            const buys=sigs.filter(x=>x.signal===1).length;
            const sells=sigs.filter(x=>x.signal===-1).length;
            const rating=computeRating(s.confidence??0.5,buys,sells,s.score??0);
            const stockNews=news.filter(n=>n.symbol===s.s||n.related?.includes(s.s)).slice(0,2);
            return (
              <div key={s.s} onClick={()=>onStock(s)}
                style={{padding:"14px 16px",borderRight:i<4?`1px solid ${G.border}`:"none",cursor:"pointer",transition:"background .12s"}}
                onMouseEnter={e=>e.currentTarget.style.background=G.surfaceHov}
                onMouseLeave={e=>e.currentTarget.style.background="transparent"}>
                <div style={{display:"flex",justifyContent:"space-between",alignItems:"center",marginBottom:4}}>
                  <div style={{display:"flex",alignItems:"center",gap:4}}>
                    <span style={{color:G.textMut,fontSize:9,fontFamily:"monospace"}}>#{i+1}</span>
                    <span style={{color:G.blue,fontWeight:700,fontSize:13,fontFamily:"monospace"}}>{s.s}</span>
                  </div>
                  <span style={{color:chg>=0?G.green:G.red,fontSize:10,fontFamily:"monospace"}}>{chg>=0?"+":""}{chg.toFixed(2)}%</span>
                </div>
                <div style={{color:G.text,fontSize:17,fontWeight:700,fontFamily:"monospace",marginBottom:2}}>₹{price.toFixed(0)}</div>
                <div style={{marginBottom:8}}><RatingBadge rating={rating}/></div>
                <div style={{display:"flex",gap:4,flexWrap:"wrap",marginBottom:6}}>
                  <Tag label={s.sid??"-"} color={G.yellow}/>
                  <Tag label={s.tt??"SWING"} color={TT_COLOR[s.tt]??G.blue}/>
                  {s.mtfVotes>0&&<Tag label={`MTF ${s.mtfVotes}/5`} color={s.mtfVotes>=4?G.green:G.teal}/>}
                </div>
                {s.selectionReason&&(
                  <div style={{color:G.textMut,fontSize:9,lineHeight:1.4,marginBottom:6,
                    padding:"4px 6px",background:G.bg,borderRadius:4,borderLeft:`2px solid ${G.blue}55`}}>
                    {s.selectionReason.slice(0,80)}{s.selectionReason.length>80?"…":""}
                  </div>
                )}
                <div style={{display:"flex",justifyContent:"space-between",marginTop:6}}>
                  <span style={{color:G.red,fontSize:9,fontFamily:"monospace"}}>SL ₹{(s.sl??0).toFixed(0)}</span>
                  <span style={{color:G.green,fontSize:9,fontFamily:"monospace"}}>TGT ₹{(s.target??0).toFixed(0)}</span>
                </div>
              </div>
            );
          })}
        </div>
      </div>

      <div style={{display:"grid",gridTemplateColumns:"200px 1fr",gap:12}}>
        <div style={{background:G.surface,border:`1px solid ${G.border}`,borderRadius:8,padding:"16px 18px"}}>
          <div style={{color:G.textSec,fontSize:11,fontWeight:600,marginBottom:12}}>Signals Now</div>
          <div style={{display:"flex",flexDirection:"column",gap:8}}>
            {[[G.green,"BUY",buy],[G.red,"SELL",sell],[G.textMut,"TOTAL",allSigs.length]].map(([color,label,val])=>(
              <div key={label} style={{display:"flex",justifyContent:"space-between"}}>
                <span style={{color:G.textSec,fontSize:11}}>{label}</span>
                <span style={{color,fontSize:14,fontWeight:700,fontFamily:"monospace"}}>{val}</span>
              </div>
            ))}
          </div>
        </div>
        <div style={{background:G.surface,border:`1px solid ${G.border}`,borderRadius:8,padding:"16px 18px"}}>
          <div style={{color:G.textSec,fontSize:11,fontWeight:600,marginBottom:12}}>NSE Universe — {NSE_UNIVERSE.length} stocks scanned</div>
          <div style={{display:"flex",gap:6,flexWrap:"wrap"}}>
            {picks.slice(0,5).map((st,i)=>{
              const candles=candleCache[st.s];
              const price=candles?.length?(candles[candles.length-1].close??candles[candles.length-1].Close??st.base):st.base;
              const first=candles?.[0];
              const chg=first?(price-(first.close??first.Close??price))/(first.close??first.Close??price)*100:0;
              return (
                <div key={st.s} onClick={()=>onStock(st)}
                  style={{background:G.blue+"14",border:`1px solid ${G.blue}44`,borderRadius:6,padding:"6px 10px",cursor:"pointer",transition:"all .12s"}}
                  onMouseEnter={e=>e.currentTarget.style.background=G.blue+"24"}
                  onMouseLeave={e=>e.currentTarget.style.background=G.blue+"14"}>
                  <div style={{color:G.blue,fontSize:10,fontWeight:700,fontFamily:"monospace"}}>{st.s}</div>
                  <div style={{color:G.text,fontSize:11,fontWeight:600,fontFamily:"monospace"}}>₹{price.toFixed(0)}</div>
                  <div style={{color:chg>=0?G.green:G.red,fontSize:9,fontFamily:"monospace"}}>{chg>=0?"+":""}{chg.toFixed(2)}%</div>
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════════════
// TAB: POSITIONS — with inner sub-tabs (Open · Progress · History)
// ═══════════════════════════════════════════════════════════════════════════
function PositionsTab({positions:rawPositions,mode,apData={}}) {
  const [showCharges,setShowCharges]=useState(null);
  const [innerTab,setInnerTab]=useState("open");

  const positions = Array.isArray(rawPositions) ? rawPositions : Object.values(rawPositions || {});
  const open=positions.filter(p=>p.status==="OPEN");
  const closed=positions.filter(p=>p.status==="CLOSED").slice(-10);

  // AP data helpers
  const apOpen    = apData?.open_positions ?? [];
  const apHist    = apData?.history        ?? [];
  const nearTgt   = apData?.near_target    ?? [];
  const nearSl    = apData?.near_sl        ?? [];
  const maxSlots  = apData?.max_positions  ?? 10;

  const INNER_TABS=[
    {id:"open",     label:`📊 Open (${open.length})`},
    {id:"progress", label:`🎯 Progress${nearTgt.length?` · ${nearTgt.length} near target`:""}`, badge:nearTgt.length},
    {id:"history",  label:`📋 History (${apHist.length})`},
  ];

  return (
    <div style={{display:"flex",flexDirection:"column",gap:0}}>

      {/* ── Inner sub-tab bar ── */}
      <div style={{display:"flex",gap:0,borderBottom:`1px solid ${G.border}`,
        background:G.surface,borderRadius:"8px 8px 0 0",overflow:"hidden",marginBottom:16}}>
        {INNER_TABS.map(t=>(
          <button key={t.id} onClick={()=>setInnerTab(t.id)} style={{
            background:"none",border:"none",cursor:"pointer",
            borderBottom:innerTab===t.id?`2px solid ${G.blueDim}`:"2px solid transparent",
            color:innerTab===t.id?G.text:G.textSec,
            padding:"9px 18px",fontSize:12,fontWeight:innerTab===t.id?600:400,
            marginBottom:-1,whiteSpace:"nowrap",transition:"color .15s",
            display:"flex",alignItems:"center",gap:5,
          }}>
            {t.label}
            {t.badge>0&&<span style={{background:G.yellow+"30",color:G.yellow,fontSize:9,fontWeight:700,padding:"1px 5px",borderRadius:10}}>{t.badge}</span>}
          </button>
        ))}
      </div>

      {/* ═══ OPEN TAB — existing table, untouched ═══ */}
      {innerTab==="open"&&(
        <div style={{display:"flex",flexDirection:"column",gap:16}}>
          {/* Open positions */}
          <div style={{background:G.surface,border:`1px solid ${G.border}`,borderRadius:8,overflow:"hidden"}}>
            <div style={{padding:"12px 18px",borderBottom:`1px solid ${G.border}`,
              display:"flex",justifyContent:"space-between",alignItems:"center"}}>
              <span style={{color:G.text,fontSize:13,fontWeight:600}}>Open Positions</span>
              <Tag label={mode==="LIVE"?"🔴 LIVE — real orders":"📄 PAPER — simulated"} color={mode==="LIVE"?G.red:G.yellow}/>
            </div>
            {open.length===0
              ?<Empty icon="📭" title="No open positions" sub="APEX selects high-confidence stocks every 40s from NSE universe. Positions appear here once confirmed."/>
              :(
                <div style={{overflowX:"auto"}}>
                  <table style={{width:"100%",borderCollapse:"collapse"}}>
                    <thead>
                      <tr style={{background:G.bg}}>
                        {["Symbol","Strategy","TT","Entry ₹","CMP ₹","SL ₹","Target ₹","Qty","Gross P&L","Net P&L","Status","Opened"].map(h=>(
                          <th key={h} style={{color:G.textSec,fontSize:10,padding:"9px 14px",
                            textAlign:"left",fontWeight:500,borderBottom:`1px solid ${G.border}`,
                            whiteSpace:"nowrap",fontFamily:"monospace"}}>{h}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {open.map(pos=>{
                        const ch=calcNetPnl(pos);
                        const monitoring=pos.tt==="LONG_TERM"||pos.tt==="SWING";
                        return (
                          <tr key={pos.id??pos.symbol} style={{borderBottom:`1px solid ${G.border}`}}
                            onMouseEnter={e=>e.currentTarget.style.background=G.surfaceHov}
                            onMouseLeave={e=>e.currentTarget.style.background="transparent"}>
                            <td style={{padding:"11px 14px"}}>
                              <div style={{color:G.text,fontWeight:700,fontSize:12,fontFamily:"monospace"}}>{pos.symbol}</div>
                              {monitoring&&<div style={{color:G.blue,fontSize:8,marginTop:2}}>📡 Monitoring</div>}
                            </td>
                            <td style={{padding:"11px 14px"}}><Tag label={pos.sid??"-"} color={G.yellow}/></td>
                            <td style={{padding:"11px 14px"}}><Tag label={pos.tt??"SWING"} color={TT_COLOR[pos.tt]??G.blue}/></td>
                            <td style={{padding:"11px 14px",color:G.textSec,fontSize:12,fontFamily:"monospace"}}>{(pos.entryPrice??0).toFixed(2)}</td>
                            <td style={{padding:"11px 14px",color:G.text,fontSize:12,fontWeight:700,fontFamily:"monospace"}}>{(pos.cp??pos.entryPrice??0).toFixed(2)}</td>
                            <td style={{padding:"11px 14px",color:G.red,fontSize:12,fontFamily:"monospace"}}>{(pos.sl??0).toFixed(2)}</td>
                            <td style={{padding:"11px 14px",color:G.green,fontSize:12,fontFamily:"monospace"}}>{(pos.target??0).toFixed(2)}</td>
                            <td style={{padding:"11px 14px",color:G.textSec,fontSize:12,fontFamily:"monospace"}}>{pos.qty}</td>
                            <td style={{padding:"11px 14px",fontFamily:"monospace"}}>
                              <span style={{color:ch.grossPnl>=0?G.green:G.red,fontSize:12,fontWeight:700}}>
                                {ch.grossPnl>=0?"+":""}₹{Math.abs(ch.grossPnl).toLocaleString("en-IN",{maximumFractionDigits:0})}
                              </span>
                            </td>
                            <td style={{padding:"11px 14px",fontFamily:"monospace"}}>
                              <div style={{color:ch.netPnl>=0?G.teal:G.red,fontSize:12,fontWeight:700}}>
                                {ch.netPnl>=0?"+":""}₹{Math.abs(ch.netPnl).toLocaleString("en-IN",{maximumFractionDigits:0})}
                              </div>
                              <div style={{color:G.textMut,fontSize:9,cursor:"pointer"}}
                                onClick={()=>setShowCharges(showCharges===pos.id?null:pos.id)}>
                                charges ₹{ch.totalCharges.toFixed(0)} {showCharges===pos.id?"▲":"▼"}
                              </div>
                              {showCharges===pos.id&&(
                                <div style={{background:G.bg,border:`1px solid ${G.border}`,borderRadius:6,
                                  padding:"8px 10px",marginTop:4,fontSize:10,color:G.textSec,minWidth:160}}>
                                  {[["Brokerage",ch.brok],["STT",ch.stt],["Exchange",ch.exc],["SEBI",ch.sebi],["Stamp",ch.stamp],["DP",ch.dp],["GST",ch.gst]].map(([l,v])=>(
                                    <div key={l} style={{display:"flex",justifyContent:"space-between",marginBottom:2}}>
                                      <span>{l}</span><span style={{fontFamily:"monospace"}}>₹{v.toFixed(2)}</span>
                                    </div>
                                  ))}
                                </div>
                              )}
                            </td>
                            <td style={{padding:"11px 14px"}}>
                              {pos.alert
                                ?<span style={{color:G.orange,fontSize:10,fontWeight:600}}>⚠ {pos.alert}</span>
                                :<span style={{color:G.textMut,fontSize:10}}>Normal</span>}
                            </td>
                            <td style={{padding:"11px 14px",color:G.textMut,fontSize:10,fontFamily:"monospace"}}>{pos.time??pos.openedAt??"-"}</td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              )}
          </div>

          {/* Recently closed */}
          {closed.length>0&&(
            <div style={{background:G.surface,border:`1px solid ${G.border}`,borderRadius:8,overflow:"hidden"}}>
              <div style={{padding:"12px 18px",borderBottom:`1px solid ${G.border}`}}>
                <span style={{color:G.text,fontSize:13,fontWeight:600}}>Recently Closed</span>
              </div>
              <table style={{width:"100%",borderCollapse:"collapse"}}>
                <thead>
                  <tr style={{background:G.bg}}>
                    {["Symbol","Entry","Exit","Qty","Net P&L","Charges","Result"].map(h=>(
                      <th key={h} style={{color:G.textSec,fontSize:10,padding:"8px 14px",textAlign:"left",
                        fontWeight:500,borderBottom:`1px solid ${G.border}`,fontFamily:"monospace"}}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {closed.map(pos=>{
                    const exit=pos.exitPrice??pos.cp??pos.entryPrice??0;
                    const ch=calcNetPnl({...pos,cp:exit});
                    return (
                      <tr key={pos.id??pos.symbol} style={{borderBottom:`1px solid ${G.border}`,opacity:.7}}
                        onMouseEnter={e=>e.currentTarget.style.background=G.surfaceHov}
                        onMouseLeave={e=>e.currentTarget.style.background="transparent"}>
                        <td style={{padding:"10px 14px",color:G.text,fontWeight:700,fontSize:12,fontFamily:"monospace"}}>{pos.symbol}</td>
                        <td style={{padding:"10px 14px",color:G.textSec,fontSize:12,fontFamily:"monospace"}}>{(pos.entryPrice??0).toFixed(2)}</td>
                        <td style={{padding:"10px 14px",color:G.text,fontSize:12,fontFamily:"monospace"}}>{exit.toFixed(2)}</td>
                        <td style={{padding:"10px 14px",color:G.textSec,fontSize:12,fontFamily:"monospace"}}>{pos.qty}</td>
                        <td style={{padding:"10px 14px",fontFamily:"monospace",fontWeight:700,
                          color:ch.netPnl>=0?G.teal:G.red,fontSize:12}}>
                          {ch.netPnl>=0?"+":""}₹{Math.abs(ch.netPnl).toLocaleString("en-IN",{maximumFractionDigits:0})}
                        </td>
                        <td style={{padding:"10px 14px",color:G.textMut,fontSize:11,fontFamily:"monospace"}}>₹{ch.totalCharges.toFixed(0)}</td>
                        <td style={{padding:"10px 14px"}}>
                          <Tag label={ch.netPnl>=0?"✓ WIN":"✗ LOSS"} color={ch.netPnl>=0?G.green:G.red}/>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {/* ═══ PROGRESS TAB ═══ */}
      {innerTab==="progress"&&(
        <div style={{display:"flex",flexDirection:"column",gap:14}}>

          {/* Slot grid */}
          <div style={{background:G.surface,border:`1px solid ${G.border}`,borderRadius:8,padding:"14px 18px"}}>
            <div style={{display:"flex",justifyContent:"space-between",alignItems:"center",marginBottom:10}}>
              <span style={{color:G.text,fontWeight:600,fontSize:12}}>Position Slots</span>
              <span style={{color:G.textSec,fontSize:11}}>
                {apData?.total_open??open.length}/{maxSlots} filled ·{" "}
                {(apData?.slots_available??maxSlots-open.length)>0
                  ?<span style={{color:G.green}}>{apData?.slots_available??maxSlots-open.length} free</span>
                  :<span style={{color:G.yellow}}>all filled — holding until targets hit</span>}
              </span>
            </div>
            <div style={{display:"flex",gap:6,flexWrap:"wrap"}}>
              {Array.from({length:maxSlots}).map((_,idx)=>{
                const pos=apOpen[idx]??open[idx];
                const sym=pos?.symbol;
                const isNT=sym&&nearTgt.includes(sym);
                const isNS=sym&&nearSl.includes(sym);
                const border=!pos?G.border:isNT?G.yellow:isNS?G.red:G.green;
                const bg=!pos?"transparent":isNT?G.yellow+"18":isNS?G.red+"18":G.green+"14";
                const color=!pos?G.textMut:isNT?G.yellow:isNS?G.red:G.green;
                const pct=pos?.pnl_pct??pos?.pnlPct;
                return (
                  <div key={idx} title={sym?`${sym}${pct!=null?` · ${pct>=0?"+":""}${pct.toFixed(1)}%`:""}`:  "Empty slot"}
                    style={{width:40,height:40,borderRadius:7,border:`1.5px solid ${border}`,background:bg,
                      display:"flex",alignItems:"center",justifyContent:"center",
                      fontSize:8,fontWeight:700,color,transition:"transform .1s",cursor:pos?"default":"default"}}
                    onMouseEnter={e=>{if(pos)e.currentTarget.style.transform="scale(1.12)";}}
                    onMouseLeave={e=>e.currentTarget.style.transform="scale(1)"}>
                    {pos?sym.slice(0,3):"·"}
                  </div>
                );
              })}
            </div>
            {(nearTgt.length>0||nearSl.length>0)&&(
              <div style={{marginTop:10,display:"flex",gap:7,flexWrap:"wrap"}}>
                {nearTgt.map(s=>(
                  <span key={s} style={{padding:"2px 8px",borderRadius:20,fontSize:10,fontWeight:700,
                    background:G.yellow+"20",color:G.yellow,border:`1px solid ${G.yellow}44`}}>🎯 {s} near target</span>
                ))}
                {nearSl.map(s=>(
                  <span key={s} style={{padding:"2px 8px",borderRadius:20,fontSize:10,fontWeight:700,
                    background:G.red+"20",color:G.red,border:`1px solid ${G.red}44`}}>⚠️ {s} near SL</span>
                ))}
              </div>
            )}
          </div>

          {/* Summary stats */}
          <div style={{display:"grid",gridTemplateColumns:"repeat(4,1fr)",gap:10}}>
            {[
              {label:"Unrealised P&L",v:apData?.total_unrealised_pnl??0,fmt:v=>`${v>=0?"+":""}₹${Math.abs(v).toLocaleString("en-IN",{maximumFractionDigits:0})}`,c:v=>(v??0)>=0?G.green:G.red},
              {label:"Realised P&L",  v:apData?.total_realised_pnl??0,  fmt:v=>`${v>=0?"+":""}₹${Math.abs(v).toLocaleString("en-IN",{maximumFractionDigits:0})}`,c:v=>(v??0)>=0?G.green:G.red},
              {label:"Win Rate",      v:apData?.win_rate_pct??0,         fmt:v=>`${(v??0).toFixed(1)}%`, c:v=>(v??0)>=55?G.green:(v??0)>=40?G.yellow:G.red},
              {label:"Capital In",    v:apData?.total_invested??0,       fmt:v=>`₹${(v??0).toLocaleString("en-IN",{maximumFractionDigits:0})}`,c:()=>G.blue},
            ].map(({label,v,fmt,c})=>(
              <div key={label} style={{background:G.surface,border:`1px solid ${G.border}`,borderRadius:8,padding:"12px 14px"}}>
                <div style={{color:G.textSec,fontSize:10,marginBottom:5,textTransform:"uppercase",letterSpacing:".4px"}}>{label}</div>
                <div style={{color:c(v),fontSize:15,fontWeight:700,fontFamily:"monospace"}}>{fmt(v)}</div>
              </div>
            ))}
          </div>

          {/* Per-position progress cards */}
          {(apOpen.length===0&&open.length===0)
            ?<div style={{background:G.surface,border:`1px solid ${G.border}`,borderRadius:8,padding:"40px",textAlign:"center",color:G.textSec,fontSize:12}}>
               📭 No open positions to track
             </div>
            :(apOpen.length>0?apOpen:open.map(p=>({
                symbol:p.symbol,entry_price:p.entryPrice??0,current_price:p.cp??p.entryPrice??0,
                target:p.target??0,stop_loss:p.sl??0,quantity:p.qty??0,
                unrealised_pnl:p.pnl??0,pnl_pct:p.pnlPct??0,
                strategy:p.sid??"",trade_type:p.tt??"SWING",days_open:0,max_days:30,
              }))).map(pos=>{
              const ep=pos.entry_price||0,curr=pos.current_price||ep;
              const tgt=pos.target||0,sl=pos.stop_loss||0;
              const totalDist=tgt-ep,doneDist=curr-ep;
              const pct=totalDist>0?Math.max(-5,Math.min(100,doneDist/totalDist*100)):0;
              const barColor=pct>=80?G.green:pct>=40?G.blueDim:pct>=0?G.yellow:G.red;
              const daysOpen=pos.days_open||0,maxDays=pos.max_days||30;
              const isNT=nearTgt.includes(pos.symbol);
              const isNS=nearSl.includes(pos.symbol);
              const cardBorder=isNT?G.yellow:isNS?G.red:G.border;
              const pnlColor=(pos.pnl_pct||pos.pnlPct||0)>=0?G.green:G.red;
              return (
                <div key={pos.symbol} style={{background:G.surface,border:`1px solid ${cardBorder}`,borderRadius:8,padding:"14px 18px"}}>
                  <div style={{display:"flex",justifyContent:"space-between",alignItems:"flex-start",marginBottom:10}}>
                    <div>
                      <span style={{color:G.text,fontWeight:700,fontSize:13,fontFamily:"monospace"}}>{pos.symbol}</span>
                      {pos.strategy&&<span style={{color:G.textMut,fontSize:10,marginLeft:8}}>{pos.strategy}</span>}
                      {pos.trade_type&&<span style={{marginLeft:6,padding:"1px 6px",borderRadius:4,fontSize:9,fontWeight:700,
                        background:(TT_COLOR[pos.trade_type]??G.blue)+"20",color:TT_COLOR[pos.trade_type]??G.blue}}>{pos.trade_type}</span>}
                      {isNT&&<span style={{marginLeft:8,padding:"1px 6px",borderRadius:10,fontSize:9,fontWeight:700,background:G.yellow+"20",color:G.yellow}}>🎯 Near Target</span>}
                      {isNS&&<span style={{marginLeft:8,padding:"1px 6px",borderRadius:10,fontSize:9,fontWeight:700,background:G.red+"20",color:G.red}}>⚠️ Near SL</span>}
                    </div>
                    <div style={{textAlign:"right"}}>
                      <span style={{color:pnlColor,fontWeight:700,fontSize:13,fontFamily:"monospace"}}>
                        {(pos.pnl_pct||pos.pnlPct||0)>=0?"+":""}{(pos.pnl_pct||pos.pnlPct||0).toFixed(2)}%
                      </span>
                      {pos.unrealised_pnl!=null&&(
                        <div style={{color:pnlColor,fontSize:10,fontFamily:"monospace"}}>
                          {pos.unrealised_pnl>=0?"+":""}₹{Math.abs(pos.unrealised_pnl).toLocaleString("en-IN",{maximumFractionDigits:0})}
                        </div>
                      )}
                    </div>
                  </div>

                  {/* Price progress bar */}
                  {tgt>0&&(
                    <>
                      <div style={{display:"flex",justifyContent:"space-between",fontSize:9,color:G.textMut,marginBottom:3}}>
                        <span>SL ₹{sl.toFixed(0)}</span>
                        <span style={{color:barColor,fontWeight:700}}>{pct.toFixed(0)}% to target</span>
                        <span>Target ₹{tgt.toFixed(0)}</span>
                      </div>
                      <div style={{height:6,background:G.border,borderRadius:3,overflow:"hidden",marginBottom:10}}>
                        <div style={{width:`${Math.max(0,pct)}%`,height:"100%",background:barColor,borderRadius:3,transition:"width .6s ease"}}/>
                      </div>
                    </>
                  )}

                  {/* Key prices row */}
                  <div style={{display:"flex",gap:18,flexWrap:"wrap",fontSize:11,alignItems:"center"}}>
                    <span style={{color:G.textSec}}>Entry <span style={{color:G.text,fontFamily:"monospace",fontWeight:600}}>₹{ep.toFixed(2)}</span></span>
                    <span style={{color:G.textSec}}>CMP <span style={{color:pnlColor,fontFamily:"monospace",fontWeight:700}}>₹{curr.toFixed(2)}</span></span>
                    <span style={{color:G.textSec}}>Target <span style={{color:G.yellow,fontFamily:"monospace"}}>₹{tgt.toFixed(2)}</span></span>
                    <span style={{color:G.textSec}}>Qty <span style={{color:G.text,fontFamily:"monospace"}}>{pos.quantity||pos.qty||0}</span></span>
                    {maxDays>0&&(
                      <span style={{marginLeft:"auto",color:daysOpen/maxDays>0.8?G.red:G.textMut,fontSize:10,display:"flex",alignItems:"center",gap:5}}>
                        Day {daysOpen}/{maxDays}
                        <span style={{display:"inline-block",width:44,height:3,background:G.border,borderRadius:2,overflow:"hidden"}}>
                          <span style={{display:"block",width:`${Math.min(100,daysOpen/maxDays*100)}%`,height:"100%",background:daysOpen/maxDays>0.8?G.red:G.textMut,borderRadius:2}}/>
                        </span>
                      </span>
                    )}
                  </div>
                </div>
              );
            })
          }
        </div>
      )}

      {/* ═══ HISTORY TAB ═══ */}
      {innerTab==="history"&&(
        <div style={{background:G.surface,border:`1px solid ${G.border}`,borderRadius:8,overflow:"hidden"}}>
          <div style={{padding:"12px 18px",borderBottom:`1px solid ${G.border}`,display:"flex",justifyContent:"space-between",alignItems:"center"}}>
            <span style={{color:G.text,fontSize:13,fontWeight:600}}>Trade History</span>
            <span style={{color:G.textSec,fontSize:11}}>
              {apData?.winning_trades??0}W · {apData?.losing_trades??0}L · Win rate {(apData?.win_rate_pct??0).toFixed(1)}%
            </span>
          </div>
          {apHist.length===0&&closed.length===0
            ?<Empty icon="📋" title="No closed trades yet" sub="Completed positions appear here once target or stop-loss is hit."/>
            :(
              <div style={{overflowX:"auto"}}>
                <table style={{width:"100%",borderCollapse:"collapse"}}>
                  <thead>
                    <tr style={{background:G.bg}}>
                      {["Symbol","Entry ₹","Exit ₹","P&L","P&L %","Result","Strategy","Days","Closed"].map(h=>(
                        <th key={h} style={{color:G.textSec,fontSize:10,padding:"9px 14px",textAlign:"left",
                          fontWeight:500,borderBottom:`1px solid ${G.border}`,whiteSpace:"nowrap",fontFamily:"monospace"}}>{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {[...[...apHist].reverse().slice(0,30),...(apHist.length===0?closed.map(p=>({
                        symbol:p.symbol,entry_price:p.entryPrice??0,current_price:p.exitPrice??p.cp??p.entryPrice??0,
                        realised_pnl:calcNetPnl({...p,cp:p.exitPrice??p.cp??p.entryPrice}).netPnl,
                        realised_pct:calcNetPnl({...p,cp:p.exitPrice??p.cp??p.entryPrice}).netPct,
                        status:"FORCE_CLOSED",strategy:p.sid??"",days_open:0,closed_at:"",
                      })):[])].map((p,idx)=>{
                      const STATUS_MAP={
                        TARGET_HIT:  [G.green, "🎯 Target"],
                        STOP_HIT:    [G.red,   "🛑 SL Hit"],
                        EXPIRED:     [G.textSec,"⏰ Expired"],
                        FORCE_CLOSED:[G.yellow,"✋ Manual"],
                      };
                      const [sc,sl]=STATUS_MAP[p.status]??[G.textSec,p.status??"-"];
                      const rpnl=p.realised_pnl||0,rpct=p.realised_pct||0;
                      const cd=p.closed_at?new Date(p.closed_at).toLocaleDateString("en-IN"):"--";
                      return (
                        <tr key={idx} style={{borderBottom:`1px solid ${G.border}`,opacity:.85}}
                          onMouseEnter={e=>e.currentTarget.style.background=G.surfaceHov}
                          onMouseLeave={e=>e.currentTarget.style.background="transparent"}>
                          <td style={{padding:"10px 14px",fontWeight:700,fontSize:12,fontFamily:"monospace",color:G.text}}>{p.symbol}</td>
                          <td style={{padding:"10px 14px",fontFamily:"monospace",color:G.textSec,fontSize:12}}>₹{(p.entry_price||0).toLocaleString("en-IN",{maximumFractionDigits:2})}</td>
                          <td style={{padding:"10px 14px",fontFamily:"monospace",color:G.text,fontSize:12}}>₹{(p.current_price||0).toLocaleString("en-IN",{maximumFractionDigits:2})}</td>
                          <td style={{padding:"10px 14px",fontFamily:"monospace",fontSize:12,fontWeight:700,color:rpnl>=0?G.teal:G.red}}>
                            {rpnl>=0?"+":""}₹{Math.abs(rpnl).toLocaleString("en-IN",{maximumFractionDigits:0})}
                          </td>
                          <td style={{padding:"10px 14px",fontFamily:"monospace",fontSize:12,color:rpct>=0?G.teal:G.red}}>
                            {rpct>=0?"+":""}{rpct.toFixed(2)}%
                          </td>
                          <td style={{padding:"10px 14px"}}>
                            <span style={{padding:"2px 7px",borderRadius:20,fontSize:10,fontWeight:700,
                              background:sc+"18",color:sc,border:`1px solid ${sc}33`}}>{sl}</span>
                          </td>
                          <td style={{padding:"10px 14px",color:G.textMut,fontSize:11}}>{p.strategy||"--"}</td>
                          <td style={{padding:"10px 14px",color:G.textMut,fontSize:11,fontFamily:"monospace"}}>{p.days_open||0}d</td>
                          <td style={{padding:"10px 14px",color:G.textMut,fontSize:10}}>{cd}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
        </div>
      )}
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════════════
// TAB: SIGNALS
// ═══════════════════════════════════════════════════════════════════════════
function SignalsTab({signals,onStock,picks}) {
  const [filter,setFilter]=useState("ALL");
  const REGIMES=["ALL","TRENDING","SIDEWAYS","VOLATILE","RISK_OFF"];
  const filtered=filter==="ALL"?signals:signals.filter(s=>s.regime===filter);
  return (
    <div style={{display:"flex",flexDirection:"column",gap:16}}>
      <div style={{display:"flex",gap:8}}>
        {REGIMES.map(r=>{
          const rc=REGIME[r]??{color:G.textSec};
          return (
            <button key={r} onClick={()=>setFilter(r)} style={{
              background:filter===r?rc.color+"22":"none",border:`1px solid ${filter===r?rc.color+"66":G.border}`,
              color:filter===r?rc.color:G.textSec,borderRadius:6,padding:"4px 12px",fontSize:11,cursor:"pointer",transition:"all .15s"}}>
              {REGIME[r]?.icon??""} {r}
            </button>
          );
        })}
      </div>
      <div style={{background:G.surface,border:`1px solid ${G.border}`,borderRadius:8,overflow:"hidden"}}>
        {filtered.length===0
          ?<Empty icon="⚔️" title="No signals for this filter" sub="TITAN runs 45+ strategies on real NSE candles every 8 seconds."/>
          :(
            <table style={{width:"100%",borderCollapse:"collapse"}}>
              <thead>
                <tr style={{background:G.bg}}>
                  {["Symbol","Strategy","Direction","Category","Confidence","Regime","Signal Reason","Time"].map(h=>(
                    <th key={h} style={{color:G.textSec,fontSize:10,padding:"9px 14px",textAlign:"left",
                      fontWeight:500,borderBottom:`1px solid ${G.border}`,fontFamily:"monospace",whiteSpace:"nowrap"}}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {filtered.slice(0,40).map((sig,idx)=>{
                  const pick=picks.find(p=>p.s===sig.symbol);
                  return (
                    <tr key={idx} style={{borderBottom:`1px solid ${G.border}`,cursor:pick?"pointer":"default"}}
                      onClick={()=>pick&&onStock(pick)}
                      onMouseEnter={e=>e.currentTarget.style.background=G.surfaceHov}
                      onMouseLeave={e=>e.currentTarget.style.background="transparent"}>
                      <td style={{padding:"10px 14px",color:G.blue,fontWeight:700,fontSize:12,fontFamily:"monospace"}}>{sig.symbol}</td>
                      <td style={{padding:"10px 14px"}}><Tag label={sig.strategy_id??sig.id??"-"} color={G.yellow}/></td>
                      <td style={{padding:"10px 14px"}}>
                        <Tag label={sig.signal===1?"BUY":sig.signal===-1?"SELL":"HOLD"}
                          color={sig.signal===1?G.green:sig.signal===-1?G.red:G.yellow}/>
                      </td>
                      <td style={{padding:"10px 14px",color:G.textSec,fontSize:11}}>{sig.category??"-"}</td>
                      <td style={{padding:"10px 14px"}}>
                        <div style={{display:"flex",alignItems:"center",gap:6}}>
                          <div style={{width:50,height:4,background:G.border,borderRadius:2,overflow:"hidden"}}>
                            <div style={{width:`${(sig.confidence??0)*100}%`,height:"100%",
                              background:(sig.confidence??0)>=0.75?G.green:(sig.confidence??0)>=0.55?G.yellow:G.red}}/>
                          </div>
                          <span style={{color:G.textSec,fontSize:10,fontFamily:"monospace"}}>{((sig.confidence??0)*100).toFixed(0)}%</span>
                        </div>
                      </td>
                      <td style={{padding:"10px 14px"}}>
                        {sig.regime&&<Tag label={sig.regime} color={REGIME[sig.regime]?.color??G.textSec}/>}
                      </td>
                      <td style={{padding:"10px 14px",color:G.textMut,fontSize:11,maxWidth:280}}>
                        <span style={{display:"block",overflow:"hidden",textOverflow:"ellipsis",whiteSpace:"nowrap"}}>{sig.reason??"-"}</span>
                      </td>
                      <td style={{padding:"10px 14px",color:G.textMut,fontSize:10,fontFamily:"monospace",whiteSpace:"nowrap"}}>{sig.ts??sig.time??"-"}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
      </div>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════════════
// TAB: NEWS
// ═══════════════════════════════════════════════════════════════════════════
function NewsTab({news,picks}) {
  const [expanded,setExpanded]=useState(null);
  const sortedNews = [...news].sort((a,b)=>{
    const ta = new Date(a.time||a.ts||0).getTime();
    const tb = new Date(b.time||b.ts||0).getTime();
    return tb - ta;
  });
  return (
    <div style={{display:"flex",flexDirection:"column",gap:0,background:G.surface,
      border:`1px solid ${G.border}`,borderRadius:8,overflow:"hidden"}}>
      <div style={{padding:"12px 18px",borderBottom:`1px solid ${G.border}`,display:"flex",justifyContent:"space-between",alignItems:"center"}}>
        <span style={{color:G.text,fontSize:13,fontWeight:600}}>Market Intelligence</span>
        <span style={{color:G.textMut,fontSize:10}}>FinBERT sentiment · HERMES agent · {news.length} items</span>
      </div>
      {sortedNews.length===0
        ?<Empty icon="📰" title="No news yet" sub="HERMES agent fetches and analyses market news every 2 minutes."/>
        :sortedNews.map((item,idx)=>{
          const pick=picks.find(p=>p.s===item.symbol);
          const sentColor=item.sentiment?.includes("BULL")?G.green:item.sentiment?.includes("BEAR")?G.red:G.yellow;
          return (
            <div key={item.id??idx} style={{borderBottom:`1px solid ${G.border}`,cursor:"pointer"}}
              onClick={()=>setExpanded(expanded===idx?null:idx)}>
              <div style={{padding:"14px 18px",display:"flex",gap:12,alignItems:"flex-start"}}
                onMouseEnter={e=>e.currentTarget.parentElement.style.background=G.surfaceHov}
                onMouseLeave={e=>e.currentTarget.parentElement.style.background="transparent"}>
                <div style={{width:3,alignSelf:"stretch",background:sentColor,borderRadius:2,flexShrink:0}}/>
                <div style={{flex:1}}>
                  <div style={{display:"flex",justifyContent:"space-between",marginBottom:4}}>
                    <div style={{display:"flex",gap:6,alignItems:"center"}}>
                      <span style={{color:G.blue,fontWeight:700,fontSize:11,fontFamily:"monospace"}}>{item.symbol}</span>
                      <Tag label={item.sentiment??"-"} color={sentColor}/>
                      <span style={{color:G.textMut,fontSize:10}}>{item.source}</span>
                    </div>
                    <span style={{color:G.textMut,fontSize:10,fontFamily:"monospace"}}>{item.time}</span>
                  </div>
                  <div style={{color:G.text,fontSize:12,lineHeight:1.5,marginBottom:4}}>{item.headline}</div>
                  {expanded===idx&&(
                    <div style={{marginTop:8,display:"flex",flexDirection:"column",gap:6}}>
                      {item.impact&&<div style={{color:G.textSec,fontSize:11,lineHeight:1.5}}>{item.impact}</div>}
                      {item.sentiment_score!=null&&(
                        <div style={{display:"flex",alignItems:"center",gap:6}}>
                          <span style={{color:G.textMut,fontSize:10}}>Sentiment score:</span>
                          <div style={{width:60,height:4,background:G.border,borderRadius:2,overflow:"hidden"}}>
                            <div style={{width:`${Math.abs(item.sentiment_score)*100}%`,height:"100%",
                              background:item.sentiment_score>=0?G.green:G.red,borderRadius:2}}/>
                          </div>
                          <span style={{color:item.sentiment_score>=0?G.green:G.red,fontSize:10,fontFamily:"monospace",fontWeight:700}}>
                            {item.sentiment_score>=0?"+":""}{(item.sentiment_score*100).toFixed(0)}%
                          </span>
                        </div>
                      )}
                      {item.url&&(
                        <a href={item.url} target="_blank" rel="noreferrer"
                          style={{color:G.blue,fontSize:10,textDecoration:"none"}}
                          onClick={e=>e.stopPropagation()}>Read full article →</a>
                      )}
                    </div>
                  )}
                </div>
              </div>
            </div>
          );
        })}
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════════════
// TAB: PERFORMANCE
// ═══════════════════════════════════════════════════════════════════════════
function PerformanceTab({evalStats,positions,agentKpi,systemState}) {
  const closed=positions.filter(p=>p.status==="CLOSED");
  const open=positions.filter(p=>p.status==="OPEN");
  const wins=closed.filter(p=>calcNetPnl({...p,cp:p.exitPrice??p.cp??p.entryPrice}).netPnl>0);
  const losses=closed.filter(p=>calcNetPnl({...p,cp:p.exitPrice??p.cp??p.entryPrice}).netPnl<=0);
  const totalNetPnl=closed.reduce((s,p)=>s+calcNetPnl({...p,cp:p.exitPrice??p.cp??p.entryPrice}).netPnl,0);
  const totalCharges=closed.reduce((s,p)=>s+calcNetPnl({...p,cp:p.exitPrice??p.cp??p.entryPrice}).totalCharges,0);
  const wr=evalStats?.win_rate??0;
  const uptime=systemState?.uptime_s??0;
  const uptimeStr=uptime>3600?`${Math.floor(uptime/3600)}h ${Math.floor((uptime%3600)/60)}m`:`${Math.floor(uptime/60)}m`;
  const sharpe=(evalStats?.total_points??0)>0?((wr-0.5)*4).toFixed(2):"—";
  const maxDD=evalStats?.max_drawdown_pct!=null?`${(evalStats.max_drawdown_pct*100).toFixed(1)}%`:"—";
  return (
    <div style={{display:"flex",flexDirection:"column",gap:20}}>
      <div style={{display:"grid",gridTemplateColumns:"repeat(6,1fr)",gap:12}}>
        {[
          {label:"Net Realised P&L",val:`${totalNetPnl>=0?"+":""}₹${Math.abs(totalNetPnl).toLocaleString("en-IN",{maximumFractionDigits:0})}`,color:totalNetPnl>=0?G.green:G.red},
          {label:"Total Trades",val:closed.length,color:G.blue},
          {label:"Win Rate",val:`${(wr*100).toFixed(1)}%`,color:wr>=0.55?G.green:wr>=0.40?G.yellow:G.red},
          {label:"Sharpe (approx)",val:sharpe,color:G.purple},
          {label:"Max Drawdown",val:maxDD,color:G.orange},
          {label:"Uptime",val:uptimeStr,color:G.teal},
        ].map(({label,val,color})=>(
          <div key={label} style={{background:G.surface,border:`1px solid ${G.border}`,borderRadius:8,padding:"14px 18px"}}>
            <div style={{color:G.textSec,fontSize:10,marginBottom:6}}>{label}</div>
            <div style={{color,fontSize:16,fontWeight:700,fontFamily:"monospace"}}>{val}</div>
          </div>
        ))}
      </div>
      <div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:16}}>
        <div style={{background:G.surface,border:`1px solid ${G.border}`,borderRadius:8,padding:"16px 18px"}}>
          <div style={{color:G.textSec,fontSize:11,fontWeight:600,marginBottom:12}}>Win / Loss Breakdown</div>
          {[[G.green,"Wins",wins.length],[G.red,"Losses",losses.length],[G.textMut,"Open",open.length]].map(([color,label,val])=>(
            <div key={label} style={{display:"flex",justifyContent:"space-between",alignItems:"center",marginBottom:8}}>
              <span style={{color:G.textSec,fontSize:11}}>{label}</span>
              <span style={{color,fontWeight:700,fontSize:14,fontFamily:"monospace"}}>{val}</span>
            </div>
          ))}
          <div style={{marginTop:8,borderTop:`1px solid ${G.border}`,paddingTop:8}}>
            <div style={{display:"flex",justifyContent:"space-between"}}>
              <span style={{color:G.textSec,fontSize:11}}>Total Charges Paid</span>
              <span style={{color:G.textMut,fontFamily:"monospace",fontSize:11}}>₹{totalCharges.toFixed(0)}</span>
            </div>
          </div>
        </div>
        <div style={{background:G.surface,border:`1px solid ${G.border}`,borderRadius:8,padding:"16px 18px"}}>
          <div style={{color:G.textSec,fontSize:11,fontWeight:600,marginBottom:12}}>Agent Performance</div>
          {Object.entries(agentKpi).slice(0,6).map(([id,kpi])=>(
            <div key={id} style={{marginBottom:8}}>
              <div style={{display:"flex",justifyContent:"space-between",marginBottom:3}}>
                <span style={{color:G.textSec,fontSize:11}}>{id}</span>
                <span style={{color:(kpi.kpi??0)>=0.70?G.green:G.yellow,fontSize:11,fontFamily:"monospace"}}>{((kpi.kpi??0)*100).toFixed(0)}%</span>
              </div>
              <KpiBar value={kpi.kpi??0} max={1} color={(kpi.kpi??0)>=0.70?G.green:G.yellow}/>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════════════
// TAB: EVALUATION
// ═══════════════════════════════════════════════════════════════════════════
function EvaluationTab({evalStats,evalHistory,agentScores}) {
  const total=evalStats?.total_evaluated??0;
  const wr=evalStats?.win_rate??0;
  return (
    <div style={{display:"flex",flexDirection:"column",gap:16}}>
      <div style={{background:G.surface,border:`1px solid ${G.border}`,borderRadius:8,padding:"16px 18px"}}>
        <div style={{color:G.text,fontSize:13,fontWeight:600,marginBottom:12}}>🔭 How LENS Evaluates Signals</div>
        <div style={{display:"grid",gridTemplateColumns:"repeat(4,1fr)",gap:12}}>
          {[
            {icon:"📡",step:"1 — Track",desc:"Every TITAN signal is logged with entry price, SL, and target when generated."},
            {icon:"⏱",step:"2 — Pending",desc:"Signal stays pending until SL or target is hit, or 24h expires."},
            {icon:"🎯",step:"3 — Score",desc:"WIN (target hit): +confidence×2 pts. LOSS (SL hit): −confidence×1 pt. Scratch: 0 pts."},
            {icon:"🧠",step:"4 — Learn",desc:"KARMA reads the evaluation report to down-weight failing strategies per regime."},
          ].map(({icon,step,desc})=>(
            <div key={step} style={{background:G.bg,borderRadius:6,padding:14}}>
              <div style={{fontSize:22,marginBottom:8}}>{icon}</div>
              <div style={{color:G.yellow,fontSize:10,fontWeight:700,marginBottom:4,fontFamily:"monospace"}}>{step}</div>
              <div style={{color:G.textSec,fontSize:11,lineHeight:1.55}}>{desc}</div>
            </div>
          ))}
        </div>
      </div>
      <div style={{display:"grid",gridTemplateColumns:"repeat(auto-fill,minmax(220px,1fr))",gap:12}}>
        {[
          {label:"Evaluated",val:total,color:G.blue},
          {label:"Wins",val:evalStats?.wins??0,color:G.green},
          {label:"Losses",val:evalStats?.losses??0,color:G.red},
          {label:"Win Rate",val:`${(wr*100).toFixed(1)}%`,color:wr>=0.55?G.green:wr>=0.40?G.yellow:G.red},
          {label:"Points",val:`${(evalStats?.total_points??0)>=0?"+":""}${(evalStats?.total_points??0).toFixed(1)}`,color:(evalStats?.total_points??0)>=0?G.green:G.red},
        ].map(({label,val,color})=>(
          <div key={label} style={{background:G.surface,border:`1px solid ${G.border}`,borderRadius:8,padding:"14px 18px"}}>
            <div style={{color:G.textSec,fontSize:11,marginBottom:6}}>{label}</div>
            <div style={{color,fontSize:20,fontWeight:700,fontFamily:"monospace"}}>{val}</div>
          </div>
        ))}
      </div>
      <div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:16}}>
        <div style={{background:G.surface,border:`1px solid ${G.border}`,borderRadius:8,overflow:"hidden"}}>
          <div style={{padding:"12px 18px",borderBottom:`1px solid ${G.border}`}}>
            <span style={{color:G.text,fontSize:13,fontWeight:600}}>Agent Leaderboard</span>
          </div>
          {Array.isArray(agentScores) && agentScores.length===0
            ?<Empty icon="🏆" title="No agent scores yet" sub="Scores appear after 5+ evaluated signals."/>
            :<table style={{width:"100%",borderCollapse:"collapse"}}>
              <thead><tr style={{background:G.bg}}>
                {["Agent","Signals","Win Rate","Points"].map(h=>(
                  <th key={h} style={{color:G.textSec,fontSize:10,padding:"8px 14px",textAlign:"left",fontWeight:500,borderBottom:`1px solid ${G.border}`}}>{h}</th>
                ))}
              </tr></thead>
              <tbody>
                {agentScores.map((a,i)=>(
                  <tr key={i} style={{borderBottom:`1px solid ${G.border}`}}>
                    <td style={{padding:"9px 14px",color:G.text,fontWeight:700,fontSize:12}}>{a.agent}</td>
                    <td style={{padding:"9px 14px",color:G.textSec,fontSize:11,fontFamily:"monospace"}}>{a.signals??0}</td>
                    <td style={{padding:"9px 14px"}}>
                      <span style={{color:(a.win_rate??0)>=0.55?G.green:(a.win_rate??0)>=0.40?G.yellow:G.red,fontFamily:"monospace",fontSize:11}}>
                        {((a.win_rate??0)*100).toFixed(0)}%
                      </span>
                    </td>
                    <td style={{padding:"9px 14px",color:(a.points??0)>=0?G.green:G.red,fontFamily:"monospace",fontSize:11}}>
                      {(a.points??0)>=0?"+":""}{(a.points??0).toFixed(1)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>}
        </div>
        <div style={{background:G.surface,border:`1px solid ${G.border}`,borderRadius:8,overflow:"hidden"}}>
          <div style={{padding:"12px 18px",borderBottom:`1px solid ${G.border}`}}>
            <span style={{color:G.text,fontSize:13,fontWeight:600}}>By Regime</span>
          </div>
          <div style={{padding:"16px 18px"}}>
            {Object.entries(evalStats?.by_regime??{}).map(([regime,stats])=>{
              const wr2=(stats.wins??0)/Math.max(stats.trades??1,1);
              return (
                <div key={regime} style={{marginBottom:10}}>
                  <div style={{display:"flex",justifyContent:"space-between",marginBottom:3}}>
                    <span style={{color:REGIME[regime]?.color??G.textSec,fontSize:11,fontWeight:600}}>
                      {REGIME[regime]?.icon} {regime}
                    </span>
                    <span style={{color:wr2>=0.55?G.green:wr2>=0.40?G.yellow:G.red,fontSize:11,fontFamily:"monospace"}}>
                      {(wr2*100).toFixed(0)}% · {stats.trades??0} trades
                    </span>
                  </div>
                  <KpiBar value={wr2} max={1} color={wr2>=0.55?G.green:wr2>=0.40?G.yellow:G.red}/>
                </div>
              );
            })}
            {Object.keys(evalStats?.by_regime??{}).length===0&&(
              <div style={{color:G.textMut,fontSize:11,textAlign:"center",padding:"20px 0"}}>No regime data yet</div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════════════
// TAB: AGENTS
// ═══════════════════════════════════════════════════════════════════════════
const AGENT_LIST=[
  {id:"ZEUS",icon:"⚡",color:"#f59e0b",role:"COO",desc:"Health check, orchestration"},
  {id:"ORACLE",icon:"🔮",color:"#8b5cf6",role:"Macro",desc:"FII/DII, economic context"},
  {id:"ATLAS",icon:"🌍",color:"#06b6d4",role:"Sector",desc:"Sector rotation selection"},
  {id:"SIGMA",icon:"📊",color:"#10b981",role:"Scoring",desc:"8-factor stock ranking"},
  {id:"APEX",icon:"🎯",color:"#f43f5e",role:"Portfolio",desc:"Top-5 final selection"},
  {id:"NEXUS",icon:"📡",color:"#3b82f6",role:"Regime",desc:"XGBoost market state"},
  {id:"HERMES",icon:"📰",color:"#a78bfa",role:"News",desc:"FinBERT sentiment"},
  {id:"TITAN",icon:"⚔️",color:"#f0883e",role:"Strategy",desc:"45+ strategy engine"},
  {id:"GUARDIAN",icon:"🛡️",color:"#ef4444",role:"Risk",desc:"Kill switch, position limits"},
  {id:"MERCURY",icon:"🚀",color:"#39c5cf",role:"Executor",desc:"OpenAlgo order routing"},
  {id:"LENS",icon:"🔭",color:"#84cc16",role:"Evaluator",desc:"Signal scoring, win rate"},
  {id:"KARMA",icon:"🧠",color:"#ec4899",role:"RL",desc:"PPO learns from LENS data"},
];

// ═══════════════════════════════════════════════════════════════════════════
// DATA SOURCES PANEL — shown inside Agents tab
// ═══════════════════════════════════════════════════════════════════════════
const SOURCE_META={
  upstox:     {icon:"🔗",label:"Upstox",    desc:"Primary broker feed · Level 1 + candles"},
  openalgo:   {icon:"🌐",label:"OpenAlgo",  desc:"Bridge to any Indian broker"},
  yfinance:   {icon:"📈",label:"yfinance",  desc:"Yahoo Finance fallback · NSE data"},
  nse_direct: {icon:"🏛️",label:"NSE Direct",desc:"NSE website scraper"},
  stooq:      {icon:"📊",label:"Stooq",     desc:"Polish/Indian market data mirror"},
  twelve_data:{icon:"💎",label:"Twelve Data",desc:"Professional data API"},
  finnhub:    {icon:"🦔",label:"Finnhub",   desc:"Global market data + news"},
  alpha_vantage:{icon:"🔬",label:"Alpha Vantage",desc:"Fundamentals + time-series"},
};

function DataSourcesPanel({dataSources}) {
  const entries=Object.entries(dataSources??{});
  if(entries.length===0){
    return (
      <div style={{background:G.surface,border:`1px solid ${G.border}`,borderRadius:8,padding:"16px 18px"}}>
        <div style={{color:G.text,fontSize:13,fontWeight:600,marginBottom:12,display:"flex",alignItems:"center",gap:8}}>
          <span>📡</span> Data Sources
          <span style={{color:G.textMut,fontSize:10,fontWeight:400}}>— connect backend to see live status</span>
        </div>
        <div style={{display:"grid",gridTemplateColumns:"repeat(auto-fill,minmax(220px,1fr))",gap:10}}>
          {Object.entries(SOURCE_META).map(([key,meta])=>(
            <div key={key} style={{background:G.bg,border:`1px solid ${G.border}`,borderRadius:7,padding:"12px 14px",
              display:"flex",gap:10,alignItems:"flex-start"}}>
              <span style={{fontSize:18,flexShrink:0}}>{meta.icon}</span>
              <div style={{flex:1,minWidth:0}}>
                <div style={{display:"flex",justifyContent:"space-between",alignItems:"center",marginBottom:2}}>
                  <span style={{color:G.textSec,fontWeight:700,fontSize:12}}>{meta.label}</span>
                  <span style={{padding:"1px 7px",borderRadius:20,fontSize:9,fontWeight:700,
                    background:G.border,color:G.textMut}}>OFFLINE</span>
                </div>
                <div style={{color:G.textMut,fontSize:10,lineHeight:1.4}}>{meta.desc}</div>
              </div>
            </div>
          ))}
        </div>
      </div>
    );
  }

  // Priority waterfall order
  const ORDER=["upstox","openalgo","yfinance","nse_direct","stooq","twelve_data","finnhub","alpha_vantage"];
  const sorted=[...entries].sort((a,b)=>{
    const ai=ORDER.indexOf(a[0]),bi=ORDER.indexOf(b[0]);
    return (ai===-1?99:ai)-(bi===-1?99:bi);
  });

  const active=sorted.filter(([,v])=>v.status==="active").length;
  const errored=sorted.filter(([,v])=>v.status==="error").length;

  return (
    <div style={{background:G.surface,border:`1px solid ${G.border}`,borderRadius:8,padding:"16px 18px"}}>
      <div style={{display:"flex",justifyContent:"space-between",alignItems:"center",marginBottom:14}}>
        <div style={{display:"flex",alignItems:"center",gap:8}}>
          <span style={{color:G.text,fontSize:13,fontWeight:600}}>📡 Data Sources</span>
          <span style={{color:G.textMut,fontSize:10}}>Priority waterfall: first active source wins</span>
        </div>
        <div style={{display:"flex",gap:8}}>
          <span style={{padding:"2px 8px",borderRadius:20,fontSize:10,fontWeight:700,
            background:G.green+"20",color:G.green,border:`1px solid ${G.green}33`}}>{active} active</span>
          {errored>0&&<span style={{padding:"2px 8px",borderRadius:20,fontSize:10,fontWeight:700,
            background:G.red+"20",color:G.red,border:`1px solid ${G.red}33`}}>{errored} error</span>}
        </div>
      </div>

      {/* Waterfall priority bar */}
      <div style={{display:"flex",gap:3,marginBottom:14,alignItems:"center"}}>
        <span style={{color:G.textMut,fontSize:9,marginRight:4,whiteSpace:"nowrap"}}>Live feed:</span>
        {sorted.map(([key,info],idx)=>{
          const meta=SOURCE_META[key]??{icon:"📦",label:key};
          const isActive=info.status==="active";
          const isErr=info.status==="error";
          const color=isActive?G.green:isErr?G.red:G.textMut;
          const bg=isActive?G.green+"20":isErr?G.red+"18":G.border+"80";
          return (
            <div key={key} style={{display:"flex",alignItems:"center",gap:3}}>
              {idx>0&&<span style={{color:G.textMut,fontSize:10,opacity:.5}}>→</span>}
              <span title={`${meta.label}: ${info.status}`} style={{padding:"2px 8px",borderRadius:4,fontSize:10,fontWeight:700,
                background:bg,color,border:`1px solid ${color}44`,whiteSpace:"nowrap"}}>
                {meta.icon} {meta.label}
              </span>
            </div>
          );
        })}
      </div>

      {/* Source cards grid */}
      <div style={{display:"grid",gridTemplateColumns:"repeat(auto-fill,minmax(240px,1fr))",gap:10}}>
        {sorted.map(([key,info],idx)=>{
          const meta=SOURCE_META[key]??{icon:"📦",label:key,desc:"Data source"};
          const isActive=info.status==="active";
          const isErr=info.status==="error";
          const isDisabled=info.status==="disabled";
          const statusColor=isActive?G.green:isErr?G.red:G.textMut;
          const statusLabel=isActive?"● ACTIVE":isErr?"✕ ERROR":isDisabled?"○ DISABLED":"○ INACTIVE";
          const cardBorder=isActive?G.green+"30":isErr?G.red+"30":G.border;
          return (
            <div key={key} style={{background:G.bg,border:`1px solid ${cardBorder}`,borderRadius:7,padding:"12px 14px"}}>
              <div style={{display:"flex",justifyContent:"space-between",alignItems:"flex-start",marginBottom:6}}>
                <div style={{display:"flex",gap:8,alignItems:"center"}}>
                  <span style={{fontSize:18}}>{meta.icon}</span>
                  <div>
                    <div style={{display:"flex",alignItems:"center",gap:5}}>
                      <span style={{color:G.text,fontWeight:700,fontSize:12}}>{meta.label}</span>
                      <span style={{color:G.textMut,fontSize:9,fontFamily:"monospace"}}>#{idx+1}</span>
                    </div>
                    <div style={{color:G.textMut,fontSize:9,marginTop:1}}>{meta.desc}</div>
                  </div>
                </div>
                <span style={{fontSize:10,fontWeight:700,color:statusColor,whiteSpace:"nowrap",
                  padding:"1px 7px",borderRadius:20,background:statusColor+"18",border:`1px solid ${statusColor}33`}}>
                  {statusLabel}
                </span>
              </div>

              {/* Stats row */}
              <div style={{display:"flex",gap:12,flexWrap:"wrap",marginTop:6}}>
                {info.requests_today!=null&&(
                  <div>
                    <div style={{color:G.textMut,fontSize:8,marginBottom:1}}>REQUESTS TODAY</div>
                    <div style={{color:G.text,fontFamily:"monospace",fontSize:11,fontWeight:600}}>{info.requests_today.toLocaleString()}</div>
                  </div>
                )}
                {info.requests!=null&&info.requests_today==null&&(
                  <div>
                    <div style={{color:G.textMut,fontSize:8,marginBottom:1}}>TOTAL REQUESTS</div>
                    <div style={{color:G.text,fontFamily:"monospace",fontSize:11,fontWeight:600}}>{info.requests.toLocaleString()}</div>
                  </div>
                )}
                {info.latency_ms!=null&&(
                  <div>
                    <div style={{color:G.textMut,fontSize:8,marginBottom:1}}>LATENCY</div>
                    <div style={{color:info.latency_ms<200?G.green:info.latency_ms<800?G.yellow:G.red,
                      fontFamily:"monospace",fontSize:11,fontWeight:600}}>{info.latency_ms}ms</div>
                  </div>
                )}
                {info.last_success&&(
                  <div>
                    <div style={{color:G.textMut,fontSize:8,marginBottom:1}}>LAST OK</div>
                    <div style={{color:G.textSec,fontSize:10}}>{new Date(info.last_success).toLocaleTimeString("en-IN",{hour12:false})}</div>
                  </div>
                )}
                {info.symbols_supported!=null&&(
                  <div>
                    <div style={{color:G.textMut,fontSize:8,marginBottom:1}}>SYMBOLS</div>
                    <div style={{color:G.blue,fontFamily:"monospace",fontSize:11,fontWeight:600}}>{info.symbols_supported}</div>
                  </div>
                )}
              </div>

              {/* Error message */}
              {isErr&&info.error&&(
                <div style={{marginTop:6,padding:"4px 8px",background:G.red+"12",borderRadius:4,
                  color:G.red,fontSize:10,lineHeight:1.4,fontFamily:"monospace"}}>{info.error}</div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

function AgentsTab({agentKpi,events,karmaStats,dataSources}) {
  const EVT_COLOR={SIGNAL:G.orange,ORDER:G.blue,SELECTION:G.red,REGIME:G.purple,HEALTH:G.green,MACRO:G.cyan,RISK:G.red,LEARN:G.purple,PERF:G.green,EXEC:G.teal,SYSTEM:G.blue};
  return (
    <div style={{display:"flex",flexDirection:"column",gap:20}}>
      <div style={{display:"grid",gridTemplateColumns:"repeat(auto-fill,minmax(280px,1fr))",gap:12}}>
        {AGENT_LIST.map(a=>{
          const kpi=agentKpi[a.id]??{kpi:0.72,cycles:0};
          return (
            <div key={a.id} style={{background:G.surface,border:`1px solid ${G.border}`,borderRadius:8,padding:"16px 18px"}}>
              <div style={{display:"flex",justifyContent:"space-between",alignItems:"flex-start",marginBottom:12}}>
                <div style={{display:"flex",gap:10,alignItems:"center"}}>
                  <span style={{fontSize:20}}>{a.icon}</span>
                  <div>
                    <div style={{color:a.color,fontWeight:700,fontSize:13}}>{a.id}</div>
                    <div style={{color:G.textMut,fontSize:10}}>{a.role}</div>
                  </div>
                </div>
                <div style={{display:"flex",alignItems:"center",gap:5}}>
                  <div style={{width:6,height:6,borderRadius:"50%",background:G.green}}/>
                  <span style={{color:G.textSec,fontSize:10,fontFamily:"monospace"}}>{((kpi.kpi??0)*100).toFixed(0)}%</span>
                </div>
              </div>
              <div style={{color:G.textSec,fontSize:11,marginBottom:10,lineHeight:1.4}}>{a.desc}</div>
              <KpiBar value={kpi.kpi??0} max={1} color={a.color}/>
              <div style={{color:G.textMut,fontSize:9,marginTop:5,fontFamily:"monospace"}}>{kpi.cycles??0} cycles</div>
            </div>
          );
        })}
      </div>

      {karmaStats&&(
        <div style={{background:G.surface,border:`1px solid ${G.border}`,borderRadius:8,padding:"16px 18px"}}>
          <div style={{color:G.text,fontSize:13,fontWeight:600,marginBottom:12,display:"flex",alignItems:"center",gap:8}}>
            <span>🧠</span> KARMA Intelligence
          </div>
          <div style={{display:"grid",gridTemplateColumns:"repeat(auto-fill,minmax(160px,1fr))",gap:10}}>
            {[
              {label:"Episodes",val:karmaStats.episodes??0,color:G.blue},
              {label:"PPO Win Rate",val:`${((karmaStats.win_rate??0)*100).toFixed(1)}%`,color:(karmaStats.win_rate??0)>=0.55?G.green:G.yellow},
              {label:"Best Strategy",val:karmaStats.best_strategy??"-",color:G.yellow},
              {label:"Training",val:karmaStats.training_active?"Active":"Scheduled",color:karmaStats.training_active?G.green:G.textSec},
            ].map(({label,val,color})=>(
              <div key={label} style={{background:G.bg,borderRadius:6,padding:"10px 12px"}}>
                <div style={{color:G.textMut,fontSize:9,marginBottom:4}}>{label}</div>
                <div style={{color,fontSize:12,fontWeight:700,fontFamily:"monospace"}}>{val}</div>
              </div>
            ))}
          </div>
        </div>
      )}

      <DataSourcesPanel dataSources={dataSources}/>

      <div style={{background:G.surface,border:`1px solid ${G.border}`,borderRadius:8,overflow:"hidden"}}>
        <div style={{padding:"12px 18px",borderBottom:`1px solid ${G.border}`,display:"flex",justifyContent:"space-between",alignItems:"center"}}>
          <span style={{color:G.text,fontSize:13,fontWeight:600}}>Event Bus</span>
          <div style={{display:"flex",alignItems:"center",gap:6}}>
            <div style={{width:6,height:6,borderRadius:"50%",background:G.green,boxShadow:`0 0 6px ${G.green}`}}/>
            <Num n={events.length}/>
          </div>
        </div>
        <div style={{maxHeight:300,overflowY:"auto"}}>
          {events.length===0
            ?<div style={{padding:"24px",color:G.textMut,fontSize:11,textAlign:"center"}}>Waiting for agent events…</div>
            :events.slice(0,40).map((ev,i)=>{
              const color=EVT_COLOR[ev.type]??G.textSec;
              return (
                <div key={i} style={{display:"flex",gap:12,padding:"8px 18px",borderBottom:`1px solid ${G.border}`,alignItems:"center"}}
                  onMouseEnter={e=>e.currentTarget.style.background=G.surfaceHov}
                  onMouseLeave={e=>e.currentTarget.style.background="transparent"}>
                  <div style={{width:2,alignSelf:"stretch",background:color,borderRadius:2,flexShrink:0}}/>
                  <span style={{color,fontWeight:700,fontSize:10,fontFamily:"monospace",minWidth:60}}>{ev.agent}</span>
                  <span style={{color:G.textSec,fontSize:11,flex:1,lineHeight:1.4}}>{ev.msg}</span>
                  <span style={{color:G.textMut,fontSize:9,fontFamily:"monospace",whiteSpace:"nowrap"}}>{ev.ts}</span>
                </div>
              );
            })}
        </div>
      </div>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════════════
// TAB: MACRO / EXTERNAL FACTORS
// ═══════════════════════════════════════════════════════════════════════════
function MacroTab({macro}) {
  const biasColor = macro.macro_bias==="BULLISH"?G.green:macro.macro_bias==="BEARISH"?G.red:G.yellow;
  const riskColor = macro.risk_level==="LOW"?G.green:macro.risk_level==="MEDIUM"?G.yellow:G.red;
  
  return (
    <div style={{display:"flex",flexDirection:"column",gap:16}}>
      <div style={{background:G.surface,border:`1px solid ${G.border}`,borderRadius:8,padding:"16px 18px"}}>
        <div style={{color:G.text,fontSize:14,fontWeight:600,marginBottom:12}}>🌍 Global Macro & External Factors</div>
        
        <div style={{display:"grid",gridTemplateColumns:"repeat(4,1fr)",gap:12,marginBottom:16}}>
          {[
            {label:"Macro Bias",val:macro.macro_bias??"NEUTRAL",color:biasColor},
            {label:"Risk Level",val:macro.risk_level??"MEDIUM",color:riskColor},
            {label:"Size Multiplier",val:`${(macro.size_mult??1).toFixed(2)}x`,color:G.blue},
            {label:"Regime Hint",val:macro.regime_hint??"SIDEWAYS",color:G.purple},
          ].map(({label,val,color})=>(
            <div key={label} style={{background:G.bg,borderRadius:6,padding:"10px 12px",border:`1px solid ${G.border}`}}>
              <div style={{color:G.textMut,fontSize:9,marginBottom:4}}>{label}</div>
              <div style={{color,fontSize:14,fontWeight:700,fontFamily:"monospace"}}>{val}</div>
            </div>
          ))}
        </div>

        <div style={{display:"grid",gridTemplateColumns:"repeat(3,1fr)",gap:12}}>
          {[
            {label:"India VIX (Fear Gauge)",val:macro.vix?macro.vix.toFixed(2):"15.00",sub:macro.vix>20?"High Volatility":"Normal Bias"},
            {label:"FII Flow (Cr)",val:macro.fii_flow_cr!=null?`${macro.fii_flow_cr>=0?"+":""}${macro.fii_flow_cr.toFixed(0)}`:"0",color:macro.fii_flow_cr>=0?G.green:G.red,sub:macro.fii_flow_cr>=0?"Bullish Net Inflow":"Bearish Net Outflow"},
            {label:"USD/INR",val:macro.usdinr?macro.usdinr.toFixed(2):"83.30",sub:macro.usdinr>84?"Rupee weakening (Bearish)":"Stable Currency"},
            {label:"S&P 500 Daily Return",val:macro.spx_ret_pct!=null?`${macro.spx_ret_pct>=0?"+":""}${macro.spx_ret_pct.toFixed(2)}%`:"0.00%",color:macro.spx_ret_pct>=0?G.green:G.red,sub:"US Market sentiment mirror"},
            {label:"Brent Crude Return",val:macro.crude_ret_pct!=null?`${macro.crude_ret_pct>=0?"+":""}${macro.crude_ret_pct.toFixed(2)}%`:"0.00%",color:macro.crude_ret_pct<0?G.green:G.red,sub:macro.crude_ret_pct>2?"Inflationary pressure":"Stable Energy Prices"},
            {label:"US Fed Action / Impact",val:"HOLD",color:G.yellow,sub:"Terminal rate priced in"}
          ].map(({label,val,color,sub})=>(
            <div key={label} style={{background:G.bg,borderRadius:6,padding:"12px 14px",borderLeft:`3px solid ${color??G.blue}`}}>
              <div style={{color:G.textSec,fontSize:11,marginBottom:4}}>{label}</div>
              <div style={{color:color??G.text,fontSize:18,fontWeight:700,fontFamily:"monospace"}}>{val}</div>
              <div style={{color:G.textMut,fontSize:10,marginTop:4}}>{sub}</div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════════════
// STOCK MODAL
// ═══════════════════════════════════════════════════════════════════════════
function StockModal({stock,onClose,candles,quotes,signals,fundamentals,news,mode}) {
  const [tab,setTab]=useState("overview");
  if(!stock) return null;
  const q=quotes?.[stock.s]??{};
  const price=+(q.ltp??stock.price??stock.base??0);
  const change24h=q.change_pct??stock.chgPct??0;
  const ind=candles?.length>=15?indicators(candles):null;
  const candlePatterns=candles?detectCandlePatterns(candles):[];
  const volAnalysis=candles?computeVolumeAnalysis(candles):null;
  const stockSigs=candles?titanSignals(candles,stock.regime??"TRENDING"):signals??[];
  const buySigs=stockSigs.filter(s=>s.signal===1);
  const sellSigs=stockSigs.filter(s=>s.signal===-1);
  const rating=computeRating(stock.confidence??0.5,buySigs.length,sellSigs.length,stock.score??0);
  const tabs=[
    {id:"overview",label:"Overview"},
    {id:"indicators",label:"Indicators"},
    {id:"signals",label:`Signals (${stockSigs.length})`},
    {id:"fundamentals",label:"Fundamentals"}
  ];
  return (
    <div style={{position:"fixed",inset:0,background:"rgba(0,0,0,.75)",zIndex:100,
      display:"flex",alignItems:"center",justifyContent:"center",padding:20}}
      onClick={e=>{if(e.target===e.currentTarget)onClose();}}>
      <div style={{background:G.surface,border:`1px solid ${G.border}`,borderRadius:12,
        width:"100%",maxWidth:840,maxHeight:"90vh",overflowY:"auto",position:"relative"}}>
        <button onClick={onClose} style={{position:"sticky",top:14,float:"right",marginRight:14,
          background:"none",border:"none",color:G.textSec,fontSize:18,cursor:"pointer",zIndex:1}}>✕</button>

        {/* Header */}
        <div style={{padding:"20px 24px 0"}}>
          <div style={{display:"flex",justifyContent:"space-between",alignItems:"flex-start",marginBottom:12}}>
            <div>
              <div style={{display:"flex",alignItems:"center",gap:10,marginBottom:4}}>
                <span style={{color:G.text,fontWeight:700,fontSize:22,fontFamily:"monospace"}}>{stock.s}</span>
                <RatingBadge rating={rating} size="lg"/>
                <Tag label={mode==="LIVE"?"🔴 LIVE":"📄 PAPER"} color={mode==="LIVE"?G.red:G.yellow}/>
              </div>
              <div style={{color:G.textSec,fontSize:12}}>{stock.n} · {stock.sec}</div>
            </div>
            <div style={{textAlign:"right"}}>
              <div style={{color:G.text,fontSize:24,fontWeight:700,fontFamily:"monospace"}}>₹{price.toFixed(2)}</div>
              <div style={{color:change24h>=0?G.green:G.red,fontSize:12,fontFamily:"monospace"}}>{change24h>=0?"+":""}{change24h.toFixed(2)}%</div>
            </div>
          </div>
          <div style={{display:"grid",gridTemplateColumns:"repeat(4,1fr)",gap:10,marginBottom:16}}>
            {[
              {label:"Entry",val:stock.entry?`₹${stock.entry.toFixed(2)}`:"—",color:G.text,sub:"Suggested entry"},
              {label:"Target",val:stock.target?`₹${stock.target.toFixed(2)}`:"—",color:G.green,sub:stock.target?`+${((stock.target-price)/price*100).toFixed(1)}% upside`:""},
              {label:"Stop Loss",val:stock.sl?`₹${stock.sl.toFixed(2)}`:"—",color:G.red,sub:stock.sl?`${((price-stock.sl)/price*100).toFixed(1)}% risk`:""},
              {label:"R:R",val:stock.entry&&stock.sl&&stock.target?`1:${((stock.target-stock.entry)/(stock.entry-stock.sl)).toFixed(2)}`:"—",color:G.purple,sub:"Reward-to-risk"},
            ].map(({label,val,color,sub})=>(
              <div key={label}>
                <div style={{color:G.textMut,fontSize:9,fontFamily:"monospace"}}>{label}</div>
                <div style={{color,fontSize:12,fontWeight:700,fontFamily:"monospace"}}>{val}</div>
                <div style={{color:G.textMut,fontSize:8}}>{sub}</div>
              </div>
            ))}
          </div>
          <div style={{display:"flex",borderBottom:`1px solid ${G.border}`,background:G.bg}}>
            {tabs.map(t=>(
              <button key={t.id} onClick={()=>setTab(t.id)} style={{
                background:"none",border:"none",borderBottom:tab===t.id?`2px solid ${G.blue}`:"2px solid transparent",
                color:tab===t.id?G.text:G.textSec,padding:"10px 20px",fontSize:12,
                cursor:"pointer",fontWeight:tab===t.id?600:400,marginBottom:-1,transition:"color .15s"}}>
                {t.label}
              </button>
            ))}
          </div>
        </div>

        <div style={{padding:"20px 24px"}}>
          {tab==="overview"&&(
            <div style={{display:"flex",flexDirection:"column",gap:16}}>
              {stock.selectionReason&&(
                <div style={{background:G.bg,border:`1px solid ${G.green}30`,borderRadius:8,padding:"14px 18px"}}>
                  <div style={{color:G.text,fontWeight:700,fontSize:13,marginBottom:8}}>🎯 Why APEX Selected This Stock</div>
                  <div style={{color:G.textSec,fontSize:12,lineHeight:1.6}}>{stock.selectionReason}</div>
                </div>
              )}
              {candlePatterns.length>0&&(
                <div style={{background:G.bg,border:`1px solid ${G.border}`,borderRadius:8,padding:"14px 18px"}}>
                  <div style={{color:G.text,fontWeight:700,fontSize:13,marginBottom:10}}>🕯 Candle Patterns</div>
                  <div style={{display:"flex",gap:8,flexWrap:"wrap"}}>
                    {candlePatterns.map((pat,i)=>(
                      <div key={i} style={{background:G.surface,border:`1px solid ${G.border}`,borderRadius:6,padding:"8px 12px"}}>
                        <div style={{display:"flex",alignItems:"center",gap:6,marginBottom:4}}>
                          <span style={{fontSize:16}}>{pat.icon}</span>
                          <span style={{color:pat.type==="bull"?G.green:pat.type==="bear"?G.red:G.yellow,fontWeight:700,fontSize:11}}>{pat.name}</span>
                        </div>
                        <div style={{color:G.textMut,fontSize:10,lineHeight:1.4,maxWidth:200}}>{pat.desc.slice(0,100)}…</div>
                      </div>
                    ))}
                  </div>
                </div>
              )}
              {volAnalysis&&(
                <div style={{background:G.bg,border:`1px solid ${G.border}`,borderRadius:8,padding:"14px 18px"}}>
                  <div style={{color:G.text,fontWeight:700,fontSize:13,marginBottom:10}}>📊 Volume Analysis</div>
                  <div style={{display:"grid",gridTemplateColumns:"repeat(4,1fr)",gap:12}}>
                    {[
                      {label:"Vol Ratio",val:`${volAnalysis.volRatio}×`,color:volAnalysis.volRatio>1.5?G.green:volAnalysis.volRatio<0.7?G.red:G.yellow},
                      {label:"OBV Trend",val:volAnalysis.obvTrend,color:volAnalysis.obvTrend==="RISING"?G.green:G.red},
                      {label:"PV Confirm",val:volAnalysis.pvConfirm?"✓ Yes":"✗ No",color:volAnalysis.pvConfirm?G.green:G.red},
                      {label:"Phase",val:volAnalysis.accumulation?"Accumulation":volAnalysis.distribution?"Distribution":"Neutral",color:volAnalysis.accumulation?G.green:volAnalysis.distribution?G.red:G.yellow},
                    ].map(({label,val,color})=>(
                      <div key={label}>
                        <div style={{color:G.textMut,fontSize:9,marginBottom:3}}>{label}</div>
                        <div style={{color,fontSize:12,fontWeight:700,fontFamily:"monospace"}}>{val}</div>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}
          {tab==="indicators"&&(
            <div>
              {!ind
                ?<Empty icon="📈" title="No indicators" sub="Not enough candle data to compute indicators."/>
                :<div style={{display:"grid",gridTemplateColumns:"repeat(2,1fr)",gap:12}}>
                  {[
                    {id:"RSI (14)",val:ind.rsi[ind.n-1]?.toFixed(1),desc:"Relative Strength Index measures momentum. >70 Overbought, <30 Oversold. High impact on mean-reversion strategies."},
                    {id:"ADX (14)",val:ind.adx[ind.n-1]?.toFixed(1),desc:"Average Directional Index measures trend strength. >25 Strong Trend, <20 Sideways. Confirms breakouts."},
                    {id:"MACD",val:ind.macd[ind.n-1]?.toFixed(2),desc:"Moving Average Convergence Divergence. Positive=Bullish trend, Negative=Bearish trend."},
                    {id:"MACD Histogram",val:ind.mh[ind.n-1]?.toFixed(2),desc:"MACD Line minus Signal Line. Rising=Increasing bullish momentum."},
                    {id:"ATR (14)",val:`₹${ind.atr[ind.n-1]?.toFixed(2)}`,desc:"Average True Range measures absolute volatility. Used mathematically for Stop Loss sizing."},
                    {id:"VWAP",val:`₹${ind.vwap[ind.n-1]?.toFixed(2)}`,desc:"Volume Weighted Average Price. Institutional benchmark for intraday/swing trend identification."},
                    {id:"BB Width",val:`${(ind.bbw[ind.n-1]*100)?.toFixed(1)}%`,desc:"Bollinger Band Width. <2% implies extreme compression and an imminent breakout."},
                    {id:"Statistical Z-Score",val:((ind.c[ind.n-1]-ind.sma20[ind.n-1])/ind.atr[ind.n-1])?.toFixed(2),desc:"Distance from 20-SMA in standard deviations (ATRized). >2 indicates extreme optimism."},
                  ].map(({id,val,desc})=>(
                    <div key={id} style={{background:G.bg,border:`1px solid ${G.border}`,borderRadius:6,padding:"14px 16px",position:"relative",cursor:"help"}}
                         onMouseEnter={(e)=>{const t=e.currentTarget.querySelector('.tooltip');if(t)t.style.display='block';}}
                         onMouseLeave={(e)=>{const t=e.currentTarget.querySelector('.tooltip');if(t)t.style.display='none';}}>
                      <div style={{display:"flex",justifyContent:"space-between",alignItems:"center",marginBottom:4}}>
                        <span style={{color:G.textSec,fontSize:11,fontWeight:600}}>{id} <span style={{fontSize:10}}>ℹ️</span></span>
                        <span style={{color:G.text,fontSize:15,fontWeight:700,fontFamily:"monospace"}}>{val}</span>
                      </div>
                      <div className="tooltip" style={{display:"none",position:"absolute",top:"100%",left:0,zIndex:100,background:G.surfaceHov,border:`1px solid ${G.borderMid}`,padding:"10px 14px",borderRadius:6,color:G.text,fontSize:11,width:"100%",boxShadow:"0 8px 16px rgba(0,0,0,0.6)",marginTop:4,lineHeight:1.5}}>
                        <strong style={{color:G.blue}}>{id} Definition</strong><br/>
                        {desc}
                      </div>
                    </div>
                  ))}
                </div>}
            </div>
          )}
          {tab==="signals"&&(
            <div>
              {stockSigs.length===0
                ?<Empty icon="⚔️" title="No signals" sub="Not enough candle data to compute signals."/>
                :<table style={{width:"100%",borderCollapse:"collapse"}}>
                  <thead><tr style={{background:G.bg}}>
                    {["Strategy","Direction","Confidence","Reason"].map(h=>(
                      <th key={h} style={{color:G.textSec,fontSize:10,padding:"8px 14px",textAlign:"left",fontWeight:500,borderBottom:`1px solid ${G.border}`}}>{h}</th>
                    ))}
                  </tr></thead>
                  <tbody>
                    {stockSigs.map((sig,i)=>(
                      <tr key={i} style={{borderBottom:`1px solid ${G.border}`}}>
                        <td style={{padding:"9px 14px"}}><Tag label={sig.id??"-"} color={G.yellow}/></td>
                        <td style={{padding:"9px 14px"}}><Tag label={sig.signal===1?"BUY":"SELL"} color={sig.signal===1?G.green:G.red}/></td>
                        <td style={{padding:"9px 14px",color:G.textSec,fontSize:11,fontFamily:"monospace"}}>{((sig.confidence??0)*100).toFixed(0)}%</td>
                        <td style={{padding:"9px 14px",color:G.textMut,fontSize:11}}>{sig.reason}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>}
            </div>
          )}
          {tab==="fundamentals"&&(
            <div>
              {!fundamentals
                ?<Empty icon="📋" title="No fundamentals" sub="Start backend for live fundamental data from screener.in."/>
                :<div style={{display:"grid",gridTemplateColumns:"repeat(3,1fr)",gap:12}}>
                  {Object.entries(fundamentals).map(([key,val])=>(
                    <div key={key} style={{background:G.bg,borderRadius:6,padding:"10px 12px"}}>
                      <div style={{color:G.textMut,fontSize:9,marginBottom:3}}>{key}</div>
                      <div style={{color:G.text,fontSize:12,fontWeight:600,fontFamily:"monospace"}}>{val}</div>
                    </div>
                  ))}
                </div>}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════════════
// MAIN APP
// ═══════════════════════════════════════════════════════════════════════════
export default function App() {
  const [tab,setTab]               = useState("overview");
  const [connStatus,setConn]       = useState("connecting");
  const [now,setNow]               = useState(new Date());
  const [regime,setRegime]         = useState("TRENDING");
  const [indices,setIndices]       = useState({nifty:24148,banknifty:51832,vix:14.2,market_open:false});
  const [quotes,setQuotes]         = useState({});
  const [picks,setPicks]           = useState([]);
  const [positions,setPos]         = useState([]);
  const [candleCache,setCaches]    = useState({});
  const [allSigs,setAllSigs]       = useState([]);
  const [evalStats,setEvalStats]   = useState({});
  const [evalHistory,setHistory]   = useState([]);
  const [agentScores,setAgtScores] = useState([]);
  const [agentKpi,setAgentKpi]     = useState({});
  const [karmaStats,setKarmaStats] = useState({});
  const [fundamentals,setFundamentals] = useState({});
  const [news,setNews]             = useState([]);
  const [macro,setMacro]           = useState({});
  const [events,setEvents]         = useState([]);
  const [selectedStock,setSelected]= useState(null);
  const [ NSE_UNIVERSE, setNseUniverse ] = useState([]);
  const [systemState,setSysState]  = useState({status:"RUNNING",mode:"PAPER",iteration:0,uptime_s:0,initial_capital:1000000});

  // ── NEW: Active Portfolio state ──────────────────────────────────────────
  const [apData,setApData]=useState({
    open_positions:[],total_open:0,max_positions:10,slots_available:10,
    total_invested:0,total_unrealised_pnl:0,total_realised_pnl:0,
    win_rate_pct:0,total_trades:0,winning_trades:0,losing_trades:0,
    near_target:[],near_sl:[],history:[],blocked_symbols:[],
  });
  const [dataSources,setDataSources]=useState({});

  // ── Refs ────────────────────────────────────────────────────────────────
  const cRef=useRef(candleCache);   cRef.current=candleCache;
  const pRef=useRef(positions);     pRef.current=positions;
  const rRef=useRef(regime);        rRef.current=regime;
  const qRef=useRef(quotes);        qRef.current=quotes;
  const connRef=useRef(connStatus); connRef.current=connStatus;
  const startTs=useRef(Date.now());

  const addEvt=useCallback((type,agent,msg)=>{
    setEvents(prev=>[{type,agent,msg,ts:new Date().toLocaleTimeString("en-IN",{hour12:false})},...prev.slice(0,99)]);
  },[]);

  // ── Clock ──────────────────────────────────────────────────────────────
  useEffect(()=>{const t=setInterval(()=>setNow(new Date()),1000);return()=>clearInterval(t);},[]);

  // ── Uptime ────────────────────────────────────────────────────────────
  useEffect(()=>{
    const t=setInterval(()=>setSysState(prev=>({...prev,uptime_s:Math.floor((Date.now()-startTs.current)/1000)})),5000);
    return()=>clearInterval(t);
  },[]);

  // ── Backend WS ─────────────────────────────────────────────────────────
  useEffect(()=>{
    let ws,alive=true;
    const connect=()=>{
      try {
        const protocol = window.location.protocol === "https:" ? "wss" : "ws";
        const host = window.location.host || "localhost:8001";
        ws=new WebSocket(`${protocol}://${host}/ws`);
        ws.onopen=()=>{if(alive){setConn("live");addEvt("SYSTEM","WS","Connected to AlphaZero backend");}};
        ws.onmessage=e=>{
          const msg=JSON.parse(e.data);
          if(msg.quotes)     setQuotes(msg.quotes);
          if(msg.indices)    setIndices(msg.indices);
          if(msg.regime)     setRegime(msg.regime);
          if(msg.karma)      setKarmaStats(msg.karma);
          if(msg.fundamentals) setFundamentals(prev=>({...prev,...msg.fundamentals}));
          if(msg.news)       setNews(msg.news);
          if(msg.macro)      setMacro(msg.macro);
          if(msg.eval_stats) setEvalStats(msg.eval_stats);
          if(msg.agent_scores) setAgtScores(msg.agent_scores);
          if(msg.agent_kpi)  setAgentKpi(msg.agent_kpi);
          if(msg.system)     setSysState(msg.system);
          if(msg.picks)      setPicks(msg.picks);
          if(msg.positions)  setPos(msg.positions);
          if(msg.signals)    setAllSigs(msg.signals);
        };
        ws.onclose=()=>{if(alive){setConn("offline");setTimeout(()=>{if(alive)connect();},5000);}};
        ws.onerror=()=>{if(alive)setConn("offline");};
        const ping=setInterval(()=>{if(ws.readyState===1)ws.send(JSON.stringify({type:"PING"}));},20000);
        ws._ping=ping;
      } catch{if(alive)setConn("offline");}
    };
    connect();
    return()=>{alive=false;ws?.close();clearInterval(ws?._ping);};
  },[addEvt]);

  // ── Active Portfolio + Data Sources REST fetch ────────────────────────
  useEffect(()=>{
    const f=async()=>{
      try{const r=await fetch(`${BACKEND}/portfolio`);if(r.ok)setApData(await r.json());}catch{}
      try{const r=await fetch(`${BACKEND}/sources`);if(r.ok)setDataSources(await r.json());}catch{}
    };
    f();const t=setInterval(f,15000);return()=>clearInterval(t);
  },[]);

  // ── Regime drift + demo data when offline ─────────────────────────────
  useEffect(()=>{
    if(connStatus==="live") return;
    setKarmaStats({episodes:847,win_rate:0.61,best_strategy:"T2 Triple EMA",
      training_active:new Date().getHours()<9||new Date().getHours()>=18,last_training:"21:00 IST"});
    const REGIMES=["TRENDING","SIDEWAYS","VOLATILE","RISK_OFF"];
    const t=setInterval(()=>{
      setRegime(REGIMES[Math.floor(Math.random()*4)]);
      setIndices(prev=>({...prev,
        nifty:+(prev.nifty*(0.999+Math.random()*.002)).toFixed(2),
        banknifty:+(prev.banknifty*(0.999+Math.random()*.002)).toFixed(2),
        vix:+(prev.vix*(0.998+Math.random()*.004)).toFixed(1),
        market_open:new Date().getHours()>=9&&new Date().getHours()<16&&new Date().getDay()>=1&&new Date().getDay()<=5,
      }));
      setAgentKpi(prev=>{
        const updated={...prev};
        AGENT_LIST.forEach(a=>{updated[a.id]={kpi:0.55+Math.random()*.35,cycles:(updated[a.id]?.cycles??0)+1};});
        return updated;
      });
    },12000);
    return()=>clearInterval(t);
  },[connStatus]);

  // ── Candle fetch ──────────────────────────────────────────────────────
  const getCandles=useCallback(async(symbol)=>{
    if(cRef.current[symbol]) return cRef.current[symbol];
    if(connRef.current==="live"){
      try{
        const r=await fetch(`${BACKEND}/candles/${symbol}`);
        const d=await r.json();
        if(d?.candles?.length){
          const norm=d.candles.map(c=>({...c,close:c.close??c.Close??0}));
          setCaches(p=>({...p,[symbol]:norm}));
          return norm;
        }
      }catch{}
    }
    const st=NSE_UNIVERSE.find(x=>x.s===symbol) || DEMO_UNIVERSE.find(x=>x.s===symbol);
    const base=st?.base??1000;
    const syn=[];
    let px=base*(1+(Math.random()-.5)*.05);
    for(let i=0;i<100;i++){
      const d=(Math.random()-.495)*base*.008,o=px;
      px=Math.max(base*.7,px+d);
      const rng=Math.abs(d)+Math.random()*base*.004;
      syn.push({open:o,close:px,high:Math.max(o,px)+Math.random()*rng*.5,low:Math.min(o,px)-Math.random()*rng*.5,volume:Math.floor(Math.random()*800000+200000)});
    }
    setCaches(p=>({...p,[symbol]:syn}));
    return syn;
  },[NSE_UNIVERSE]);

  // ── APEX stock selection ───────────────────────────────────────────────
  const runSelect=useCallback(async()=>{
    if(connRef.current==="live") return;
    const cr=rRef.current;
    const results=await Promise.all(DEMO_UNIVERSE.map(async(st)=>{
      const cdl=await getCandles(st.s);
      const ind=cdl.length>=15?indicators(cdl):null;
      const Li=ind?ind.n-1:-1;
      const liveQ=qRef.current[st.s];
      const price=+(liveQ?.ltp??(cdl.length?(cdl[cdl.length-1].close??st.base):st.base)).toFixed(2);
      const atr=ind&&Li>=0?ind.atr[Li]:price*.013;
      const first=cdl[0];
      const chg=first?(price-(first.close??first.Close??price))/(first.close??first.Close??price)*100:0;
      const mf=Math.max(0,Math.min(1,chg/3+.5));
      const tf=ind&&Li>=0?Math.min(1,ind.adx[Li]/50):.3+Math.random()*.3;
      const rf=ind&&Li>=0?(ind.rsi[Li]>38&&ind.rsi[Li]<68?.7+Math.random()*.2:.3):.5;
      const ef=ind&&Li>=0?(ind.e20[Li]>ind.e50[Li]?.7+Math.random()*.25:.3):.5;
      const vf=.4+Math.random()*.5,nf=.35+Math.random()*.6,fii=.25+Math.random()*.7,earn=.35+Math.random()*.55;
      const score=+(mf*.20+tf*.15+rf*.15+ef*.15+earn*.15+vf*.10+nf*.10+fii*.05).toFixed(3);
      const tt=ind&&Li>=0&&ind.adx[Li]>40?"SHORT_TERM":cr==="TRENDING"&&tf>.55?"LONG_TERM":"SWING";
      const pools={TRENDING:["T1 EMA Cross","T2 Triple EMA","T4 MACD","T5 ADX","T7 Donchian","B2 Vol Breakout"],SIDEWAYS:["M1 RSI Rev","M2 BB Bounce","M3 BB Squeeze","V1 VWAP Cross","S1 Z-Score"],VOLATILE:["M1 RSI Rev","M2 BB Bounce","V1 VWAP Cross"],RISK_OFF:["M1 RSI Rev"]};
      const pool=pools[cr]??pools.TRENDING;
      const ss=pool[Math.floor(Math.random()*pool.length)];
      const [sid,...sname]=ss.split(" ");
      const stockSigs=cdl?titanSignals(cdl,cr):[];
      const buys=stockSigs.filter(x=>x.signal===1).length;
      const sells=stockSigs.filter(x=>x.signal===-1).length;
      const mtfVotes=Math.floor(Math.random()*3)+2;
      const topReason=stockSigs[0]?.reason??"Momentum aligning with regime";
      const confidence=+(score*.5+(buys-sells)/Math.max(buys+sells,1)*.3+mtfVotes/5*.2).toFixed(3);
      const entry=price,target=+(price*(1+atr/price*2.5)).toFixed(2),sl=+(price*(1-atr/price*1.2)).toFixed(2);
      return {...st,price,chgPct:chg,score,confidence,tt,sid,sname:sname.join(" "),
        entry,target,sl,regime:cr,mtfVotes,
        selectionReason:`SIGMA Score ${score.toFixed(3)}. ${topReason}. MTF: ${mtfVotes}/5 aligned. R:R ${((target-entry)/(entry-sl)).toFixed(2)}.`};
    }));
    const top5=results.sort((a,b)=>b.score-a.score).slice(0,5);
    setPicks(top5);
    const sigs=results.flatMap(st=>{
      const cdl=cRef.current[st.s];
      return cdl?titanSignals(cdl,cr).map(s=>({...s,symbol:st.s,regime:cr,ts:new Date().toLocaleTimeString("en-IN",{hour12:false})})):[];
    });
    setAllSigs(sigs);
  },[getCandles, NSE_UNIVERSE]);

  useEffect(()=>{
    runSelect();
    const t=setInterval(runSelect,40000);
    return()=>clearInterval(t);
  },[runSelect]);

  // ── Demo signal events ─────────────────────────────────────────────────
  useEffect(()=>{
    const run=()=>{
      const top=allSigs[0];
      if(top){addEvt("SIGNAL","TITAN",`${top.signal===1?"BUY":"SELL"} (${(top.confidence*100).toFixed(0)}%) · ${top.reason}`);}
    };
    const t=setInterval(run,10000);
    return()=>clearInterval(t);
  },[allSigs,addEvt]);

  // ── News generation ────────────────────────────────────────────────────
  useEffect(()=>{
    if(picks.length>0&&connStatus!=="live")setNews(generateDemoNews(picks));
  },[picks,connStatus]);

  // ── Fundamentals fetch ─────────────────────────────────────────────────
  useEffect(()=>{
    if(connStatus!=="live") return;
    picks.forEach(async st=>{
      if(fundamentals[st.s]) return;
      try{const r=await fetch(`${BACKEND}/fundamentals/${st.s}`);const d=await r.json();setFundamentals(prev=>({...prev,[st.s]:d}));}catch{}
    });
  },[picks,connStatus,fundamentals]);

  // ── Eval stats fetch ───────────────────────────────────────────────────
  useEffect(()=>{
    if(connStatus!=="live") return;
    const f=async()=>{
      try{
        const [sr,hr,ar]=await Promise.all([
          fetch(`${BACKEND}/evaluation/stats`).then(r=>r.json()),
          fetch(`${BACKEND}/evaluation/history?limit=30`).then(r=>r.json()),
          fetch(`${BACKEND}/evaluation/agents`).then(r=>r.json()),
        ]);
        setEvalStats(sr);setHistory(hr);setAgtScores(ar);
      }catch{}
    };
    f();const t=setInterval(f,30000);return()=>clearInterval(t);
  },[connStatus]);

  // ── Fetch NSE_UNIVERSE from backend ────────────────────────────────────
  useEffect(()=>{
    const loadUniverse=async()=>{
      try{
        const r=await fetch(`${BACKEND}/api/universe`);
        const d=await r.json();
        if(Array.isArray(d)&&d.length>0) setNseUniverse(d);
        else throw new Error("Invalid universe format");
      }catch(e){
        console.warn("Using local universe fallback:",e);
      }
    };
    loadUniverse();
  },[]);

  // ── Net P&L ───────────────────────────────────────────────────────────
  const openPositions=positions.filter(p=>p.status==="OPEN");
  const netPnlTotal=openPositions.reduce((s,p)=>s+calcNetPnl(p).netPnl,0);
  const closedPnl=positions.filter(p=>p.status==="CLOSED").reduce((s,p)=>s+calcNetPnl({...p,cp:p.exitPrice??p.cp??p.entryPrice}).netPnl,0);
  const totalNetPnl=netPnlTotal+closedPnl;

  const tabCounts={pos:openPositions.length,sigs:allSigs.length,news:news.length,eval:evalStats?.total_evaluated??0};

  return (
    <div style={{background:G.bg,color:G.text,height:"100vh",width:"100vw",
      fontFamily:"'SF Mono','Fira Code','JetBrains Mono',Consolas,monospace",
      fontSize:13,display:"flex",flexDirection:"column",overflow:"hidden"}}>

      <ConnBanner status={connStatus}/>
      <TopNav regime={regime} indices={indices} paperPnl={totalNetPnl} time={now} connStatus={connStatus} mode={systemState.mode} initial_capital={systemState.initial_capital}/>
      <TabBar active={tab} setActive={setTab} counts={tabCounts}/>

      <div style={{flex:1,padding:"20px 24px",width:"100%",overflowY:"auto",overflowX:"hidden"}}>
        {tab==="overview"&&
          <OverviewTab picks={picks} positions={positions} allSigs={allSigs}
            evalStats={evalStats} indices={indices} candleCache={candleCache}
            news={news} onStock={setSelected}/>}
        {tab==="positions"&&
          <PositionsTab positions={positions} mode={systemState.mode} apData={apData}/>}
        {tab==="signals"&&
          <SignalsTab signals={allSigs} onStock={setSelected} picks={picks}/>}
        {tab==="news"&&
          <NewsTab news={news} picks={picks}/>}
        {tab==="macro"&&
          <MacroTab macro={macro}/>}
        {tab==="performance"&&
          <PerformanceTab evalStats={evalStats} positions={positions} agentKpi={agentKpi} systemState={systemState}/>}
        {tab==="evaluation"&&
          <EvaluationTab evalStats={evalStats} evalHistory={evalHistory} agentScores={agentScores}/>}
        {tab==="agents"&&
          <AgentsTab agentKpi={agentKpi} events={events} karmaStats={karmaStats} dataSources={dataSources}/>}
      </div>

      <footer style={{borderTop:`1px solid ${G.border}`,background:G.surface,
        padding:"14px 24px",display:"flex",justifyContent:"space-between",alignItems:"center"}}>
        <div style={{display:"flex",gap:16,alignItems:"center"}}>
          <div style={{display:"flex",alignItems:"center",gap:6}}>
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none">
              <polygon points="12,2 22,20 2,20" fill={G.green} opacity=".9"/>
              <polygon points="12,6 19,19 5,19" fill={G.bg}/>
            </svg>
            <span style={{color:G.text,fontWeight:700,fontSize:11}}>AlphaZero Capital</span>
          </div>
          <span style={{color:G.textMut,fontSize:10}}>{VERSION}</span>
          <span style={{color:G.border}}>·</span>
          <span style={{color:G.textMut,fontSize:10}}>Created by <span style={{color:G.textSec,fontWeight:600}}>{AUTHOR}</span></span>
        </div>
        <div style={{display:"flex",gap:14,alignItems:"center"}}>
          <span style={{color:G.textMut,fontSize:10,fontFamily:"monospace"}}>
            {(connStatus==="live"?picks.length:DEMO_UNIVERSE.length)} stocks · {AGENT_LIST.length} agents · NSE/BSE
          </span>
          <div style={{width:1,height:12,background:G.border}}/>
          <span style={{color:G.textMut,fontSize:10}}>
            {systemState.mode==="LIVE"
              ?<span style={{color:G.red}}>🔴 LIVE — real orders via OpenAlgo</span>
              :<span style={{color:G.yellow}}>📄 PAPER — all strategies run, no real orders</span>}
          </span>
          <div style={{width:1,height:12,background:G.border}}/>
          <span style={{color:G.textMut,fontSize:10,fontFamily:"monospace"}}>{now.toLocaleTimeString("en-IN",{hour12:false})} IST</span>
        </div>
      </footer>

      {selectedStock&&(
        <StockModal stock={selectedStock} onClose={()=>setSelected(null)}
          candles={candleCache[selectedStock.s]} quotes={quotes}
          signals={allSigs.filter(s=>s.symbol===selectedStock.s)}
          fundamentals={fundamentals[selectedStock.s]}
          news={news} mode={systemState.mode}/>
      )}

      <style>{`
        @keyframes spin{from{transform:rotate(0)}to{transform:rotate(360deg)}}
        @keyframes pulse{0%,100%{opacity:1}50%{opacity:.4}}
        ::-webkit-scrollbar{width:5px;height:5px}
        ::-webkit-scrollbar-track{background:${G.bg}}
        ::-webkit-scrollbar-thumb{background:${G.border};border-radius:3px}
        ::-webkit-scrollbar-thumb:hover{background:${G.borderMid}}
        *{box-sizing:border-box}
      `}</style>
    </div>
  );
}
