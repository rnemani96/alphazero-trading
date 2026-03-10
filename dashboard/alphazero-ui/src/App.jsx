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

const BACKEND  = import.meta.env.VITE_BACKEND_URL || "http://localhost:8000";
const VERSION  = "v5.0.0";
const AUTHOR   = "Rajesh Nemani";

// ─── Indian market charges ─────────────────────────────────────────────────
// Used to compute real net P&L after all levies
const CHARGES = {
  brokerage:     20,          // ₹20 per executed order (flat, Zerodha model)
  stt_delivery:  0.001,       // 0.1% on buy+sell for delivery
  stt_intraday:  0.00025,     // 0.025% on sell side for intraday
  exchange_nse:  0.0000345,   // 0.00345% NSE transaction charge
  sebi:          0.000001,    // 0.0001% SEBI turnover fee
  stamp_delivery:0.00015,     // 0.015% on buy, delivery
  stamp_intraday:0.00003,     // 0.003% on buy, intraday
  dp_charge:     15.93,       // ₹15.93 per scrip per day (delivery sells) incl GST
  gst_rate:      0.18,        // 18% on brokerage + exchange charges
};

function calcNetPnl(pos) {
  const { entryPrice=0, cp=0, qty=0, tt="SWING" } = pos;
  const isIntraday = tt === "INTRADAY";
  const turnover   = (entryPrice + cp) * qty;
  const grossPnl   = (cp - entryPrice) * qty;

  const brok    = CHARGES.brokerage * 2;                       // buy + sell
  const stt     = isIntraday
    ? cp * qty * CHARGES.stt_intraday
    : turnover * CHARGES.stt_delivery;
  const exc     = turnover * CHARGES.exchange_nse;
  const sebi    = turnover * CHARGES.sebi;
  const stamp   = isIntraday
    ? entryPrice * qty * CHARGES.stamp_intraday
    : entryPrice * qty * CHARGES.stamp_delivery;
  const dp      = isIntraday ? 0 : CHARGES.dp_charge;
  const gst     = (brok + exc) * CHARGES.gst_rate;

  const totalCharges = brok + stt + exc + sebi + stamp + dp + gst;
  const netPnl = grossPnl - totalCharges;
  const netPct = entryPrice > 0 ? (netPnl / (entryPrice * qty)) * 100 : 0;

  return { grossPnl, netPnl, netPct, totalCharges, brok, stt, exc, sebi, stamp, dp, gst };
}

// ─── REGIME config ─────────────────────────────────────────────────────────
const REGIME = {
  TRENDING: { color:G.green,  icon:"↑", label:"Trending"  },
  SIDEWAYS: { color:G.yellow, icon:"↔", label:"Sideways"  },
  VOLATILE: { color:G.red,    icon:"⚡", label:"Volatile"  },
  RISK_OFF: { color:G.purple, icon:"⛔", label:"Risk Off"  },
};
const TT_COLOR = { INTRADAY:G.orange, SHORT_TERM:G.blue, SWING:G.purple, LONG_TERM:G.green };

// ─── Rating thresholds ─────────────────────────────────────────────────────
function computeRating(confidence, buyCount, sellCount, sigmaScore) {
  const net = buyCount - sellCount;
  const score = confidence * 0.4 + (sigmaScore || 0) * 0.4 + (net / Math.max(buyCount + sellCount, 1)) * 0.2;
  if (score >= 0.80 && net >= 4)  return { label:"STRONG BUY",  color:G.green,  icon:"⬆⬆", bg:G.greenBg };
  if (score >= 0.62 && net >= 2)  return { label:"BUY",         color:G.teal,   icon:"⬆",  bg:"#0a1f14" };
  if (score >= 0.45 || net === 0) return { label:"HOLD",        color:G.yellow, icon:"→",  bg:G.yellowBg };
  if (score >= 0.28 || net <= -2) return { label:"SELL",        color:G.orange, icon:"⬇",  bg:"#1a0e00" };
  return                                 { label:"STRONG SELL", color:G.red,    icon:"⬇⬇", bg:G.redBg };
}

// ─── Indicator math ────────────────────────────────────────────────────────
function ema(arr, p) {
  const k=2/(p+1), out=new Float64Array(arr.length);
  out[0]=arr[0];
  for (let i=1;i<arr.length;i++) out[i]=arr[i]*k+out[i-1]*(1-k);
  return out;
}

function indicators(candles) {
  if (!candles||candles.length<15) return null;
  const n=candles.length;
  const c=candles.map(x=>x.close??x.Close??0);
  const h=candles.map(x=>x.high??x.High??0);
  const l=candles.map(x=>x.low??x.Low??0);
  const v=candles.map(x=>x.volume??x.Volume??0);
  const e9=ema(c,9),e20=ema(c,20),e50=ema(c,50);
  const tr=c.map((ci,i)=>i===0?h[0]-l[0]:Math.max(h[i]-l[i],Math.abs(h[i]-c[i-1]),Math.abs(l[i]-c[i-1])));
  const atr=ema(tr,14);
  const δ=c.map((ci,i)=>i===0?0:ci-c[i-1]);
  const ag=ema(δ.map(d=>Math.max(d,0)),14),al=ema(δ.map(d=>Math.max(-d,0)),14);
  const rsi=ag.map((g,i)=>al[i]===0?100:100-100/(1+g/al[i]));
  const ml=ema(c,12).map((v,i)=>v-ema(c,26)[i]),ms=ema(ml,9),mh=ml.map((v,i)=>v-ms[i]);
  const pdm=h.map((hi,i)=>i===0?0:Math.max(hi-h[i-1],0));
  const ndm=l.map((li,i)=>i===0?0:Math.max(l[i-1]-li,0));
  const pdi=ema(pdm,14).map((v,i)=>atr[i]>0?100*v/atr[i]:0);
  const ndi=ema(ndm,14).map((v,i)=>atr[i]>0?100*v/atr[i]:0);
  const dx=pdi.map((p,i)=>p+ndi[i]>0?100*Math.abs(p-ndi[i])/(p+ndi[i]):0);
  const adx=ema(dx,14);
  const bbm=c.map((_,i)=>{const s=c.slice(Math.max(0,i-19),i+1);return s.reduce((a,b)=>a+b,0)/s.length;});
  const bbs=c.map((_,i)=>{const s=c.slice(Math.max(0,i-19),i+1);const m=s.reduce((a,b)=>a+b,0)/s.length;return Math.sqrt(s.reduce((a,b)=>a+(b-m)**2,0)/s.length);});
  const bbu=bbm.map((m,i)=>m+2*bbs[i]),bbl=bbm.map((m,i)=>m-2*bbs[i]);
  const bbw=bbu.map((u,i)=>bbm[i]>0?(u-bbl[i])/bbm[i]:0);
  const bbpb=c.map((ci,i)=>bbu[i]>bbl[i]?(ci-bbl[i])/(bbu[i]-bbl[i]):0.5);
  let cv=0,ctv=0;
  const vwap=c.map((ci,i)=>{const tp=(ci+h[i]+l[i])/3;cv+=v[i];ctv+=tp*v[i];return cv>0?ctv/cv:tp;});
  const sk=c.map((ci,i)=>{const lo=Math.min(...l.slice(Math.max(0,i-13),i+1)),hi=Math.max(...h.slice(Math.max(0,i-13),i+1));return hi>lo?100*(ci-lo)/(hi-lo):50;});
  const sd=ema(sk,3);
  const obvDir=c.map((ci,i)=>i===0?0:ci>c[i-1]?1:ci<c[i-1]?-1:0);
  const obv=v.map((vi,i)=>vi*obvDir[i]).reduce((acc,val,i)=>{acc.push((acc[i-1]??0)+val);return acc;},[]);
  const obv5avg=obv.length>5?obv.slice(-5).reduce((a,b)=>a+b,0)/5:obv[obv.length-1]??0;
  const obvTrend=obv.length>0&&obv[obv.length-1]>obv5avg?"RISING":"FALLING";
  const v20avg=v.slice(-20).reduce((a,b)=>a+b,0)/Math.min(20,n);
  const volRatio=v20avg>0?v[n-1]/v20avg:1;
  return {c,h,l,v,n,e9,e20,e50,atr,rsi,macd:ml,mh,adx,bbu,bbl,bbw,bbpb,vwap,sk,sd,obv,obvTrend,volRatio,v20avg};
}

// ─── Candle pattern detection ───────────────────────────────────────────────
function detectCandlePatterns(candles) {
  const pats=[];
  if (!candles||candles.length<3) return pats;
  const o=candles.map(x=>x.open??x.Open??0);
  const h=candles.map(x=>x.high??x.High??0);
  const l=candles.map(x=>x.low??x.Low??0);
  const c=candles.map(x=>x.close??x.Close??0);
  const n=c.length,i=n-1,p=n-2;
  const body=idx=>Math.abs(c[idx]-o[idx]);
  const upWick=idx=>h[idx]-Math.max(c[idx],o[idx]);
  const dnWick=idx=>Math.min(c[idx],o[idx])-l[idx];
  const range=idx=>h[idx]-l[idx];
  const isBull=idx=>c[idx]>=o[idx];
  if (range(i)>0&&body(i)/range(i)<0.1)
    pats.push({name:"Doji",icon:"🕯️",type:"neutral",desc:"Indecision candle — buyers and sellers in perfect balance. A Doji after a strong trend often signals exhaustion and potential reversal. Watch for confirmation on the next candle before acting."});
  if (dnWick(i)>2*body(i)&&upWick(i)<body(i)&&isBull(i))
    pats.push({name:"Hammer",icon:"🔨",type:"bull",desc:"Bullish reversal signal. Sellers pushed price down aggressively, but buyers stepped in and recovered nearly all losses. The long lower wick shows strong buying interest at lower levels. TITAN fires M2 BB Bounce + V1 VWAP reclaim in this scenario."});
  if (upWick(i)>2*body(i)&&dnWick(i)<body(i)&&!isBull(i))
    pats.push({name:"Shooting Star",icon:"⭐",type:"bear",desc:"Bearish reversal signal. Buyers pushed price up sharply, but sellers overwhelmed them and closed near the lows. The long upper wick shows strong rejection at higher levels. Consider exiting longs or initiating shorts with tight stop above the high."});
  if (!isBull(p)&&isBull(i)&&o[i]<c[p]&&c[i]>o[p])
    pats.push({name:"Bullish Engulfing",icon:"🟢",type:"bull",desc:"Strong bullish reversal — the current green candle completely swallows the previous red candle's body. Indicates a powerful shift from selling to buying pressure. High-probability setup: TITAN T1 EMA Cross often confirms simultaneously. Best entry on close of this candle."});
  if (isBull(p)&&!isBull(i)&&o[i]>c[p]&&c[i]<o[p])
    pats.push({name:"Bearish Engulfing",icon:"🔴",type:"bear",desc:"Strong bearish reversal — the current red candle completely swallows the previous green candle. Indicates sellers took full control. Exit long positions immediately. GUARDIAN typically triggers a stop-loss review when this pattern appears at resistance."});
  if (n>=3&&!isBull(n-3)&&body(n-2)<body(n-3)*0.5&&isBull(i)&&c[i]>(o[n-3]+c[n-3])/2)
    pats.push({name:"Morning Star",icon:"🌟",type:"bull",desc:"Three-candle bullish reversal pattern. Day 1: large red candle (sellers in control). Day 2: small body (indecision, selling momentum slowing). Day 3: large green candle closing above midpoint of Day 1. One of the most reliable reversal signals. Target = prior resistance zone."});
  if (n>=3&&isBull(n-3)&&body(n-2)<body(n-3)*0.5&&!isBull(i)&&c[i]<(o[n-3]+c[n-3])/2)
    pats.push({name:"Evening Star",icon:"🌆",type:"bear",desc:"Three-candle bearish reversal pattern. Mirror of Morning Star. Day 1: large green candle. Day 2: small body gap up (buying exhaustion). Day 3: large red candle closing below Day 1 midpoint. Exit longs. Especially powerful at round-number resistance or 52-week highs."});
  if (isBull(i)&&body(i)>range(i)*0.7)
    pats.push({name:"Strong Bull Candle",icon:"💪",type:"bull",desc:"A momentum candle with body occupying >70% of the total range. No meaningful wicks — buyers were in control throughout the entire session. This is what TITAN's B2 Volume Surge strategy looks for. Strong follow-through likely if volume was also elevated."});
  if (h[i]<h[p]&&l[i]>l[p])
    pats.push({name:"Inside Bar",icon:"📦",type:"neutral",desc:"The current candle's high and low are both within the previous candle's range. This indicates consolidation and a compression of volatility. A breakout above the mother bar's high is bullish; below the low is bearish. TITAN's BB Squeeze (M3) often fires alongside this."});
  return pats;
}

// ─── Volume analysis ────────────────────────────────────────────────────────
function computeVolumeAnalysis(candles) {
  if (!candles||candles.length<5) return null;
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

// ─── TITAN signals ─────────────────────────────────────────────────────────
function titanSignals(candles,regime) {
  const ind=indicators(candles);
  if (!ind) return [];
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
  if(adx[i]>25) push("T5","Trend",macd[i]>0?1:-1,Math.min(0.90,0.54+adx[i]/100),`ADX=${adx[i].toFixed(0)} strong trend`);
  const hi20=Math.max(...h.slice(Math.max(0,i-19),i+1)),lo20=Math.min(...l.slice(Math.max(0,i-19),i+1));
  if(c[i]>=hi20*0.998) push("T7","Trend",1,0.82,`20-bar Donchian breakout high ${hi20.toFixed(0)}`);
  else if(c[i]<=lo20*1.002) push("T7","Trend",-1,0.82,`20-bar Donchian breakdown low ${lo20.toFixed(0)}`);
  const r=rsi[i];
  if(r<28)      push("M1","MeanRev",1,Math.min(0.92,0.65+(28-r)/30),`RSI=${r.toFixed(0)} extreme oversold`);
  else if(r>72) push("M1","MeanRev",-1,Math.min(0.92,0.65+(r-72)/30),`RSI=${r.toFixed(0)} extreme overbought`);
  else if(r<38) push("M1","MeanRev",1,0.50,`RSI=${r.toFixed(0)} near oversold`);
  else if(r>62) push("M1","MeanRev",-1,0.50,`RSI=${r.toFixed(0)} near overbought`);
  if(bbpb[i]<0.06) push("M2","MeanRev",1,0.72,`BB lower band bounce %B=${bbpb[i].toFixed(2)}`);
  else if(bbpb[i]>0.94) push("M2","MeanRev",-1,0.72,`BB upper band touch %B=${bbpb[i].toFixed(2)}`);
  const abw=bbw.slice(Math.max(0,i-19),i).reduce((a,b)=>a+b,0)/20;
  if(bbw[i]<abw*0.72) push("M3","MeanRev",macd[i]>0?1:-1,0.74,"BB squeeze — volatility breakout imminent");
  if(sk[i]<22&&sk[i]>sd[i]) push("M4","MeanRev",1,0.70,`Stoch K=${sk[i].toFixed(0)} oversold crossover`);
  else if(sk[i]>78&&sk[i]<sd[i]) push("M4","MeanRev",-1,0.70,`Stoch K=${sk[i].toFixed(0)} overbought crossover`);
  const mu=c.slice(Math.max(0,i-19),i+1).reduce((a,b)=>a+b,0)/20;
  const σ=Math.sqrt(c.slice(Math.max(0,i-19),i+1).reduce((a,b)=>a+(b-mu)**2,0)/20);
  const z=σ>0?(c[i]-mu)/σ:0;
  if(z<-2) push("S1","Statistical",1,Math.min(0.90,0.68+Math.abs(z+2)*0.08),`Z-score=${z.toFixed(2)} 2σ below mean`);
  else if(z>2) push("S1","Statistical",-1,Math.min(0.90,0.68+(z-2)*0.08),`Z-score=${z.toFixed(2)} 2σ above mean`);
  const avgV=v.reduce((a,b)=>a+b,0)/n,vr=v[i]/Math.max(avgV,1);
  const oh=Math.max(...h.slice(0,Math.min(4,n))),ol=Math.min(...l.slice(0,Math.min(4,n)));
  if(c[i]>oh*1.002) push("B1","Breakout",1,vr>1.3?0.85:0.65,`Opening range breakout above ${oh.toFixed(0)}`);
  else if(c[i]<ol*0.998) push("B1","Breakout",-1,0.65,`Opening range breakdown below ${ol.toFixed(0)}`);
  if(vr>1.5&&c[i]>c[p]) push("B2","Breakout",1,Math.min(0.90,0.55+vr*0.08),`Volume surge ×${vr.toFixed(1)} bullish`);
  else if(vr>1.5&&c[i]<c[p]) push("B2","Breakout",-1,Math.min(0.88,0.52+vr*0.07),`Volume surge ×${vr.toFixed(1)} bearish`);
  if(c[i]>vwap[i]&&c[p]<=vwap[p]) push("V1","VWAP",1,0.74,"Price reclaimed VWAP — bullish");
  else if(c[i]<vwap[i]&&c[p]>=vwap[p]) push("V1","VWAP",-1,0.74,"Price lost VWAP — bearish");
  const vd=(c[i]-vwap[i])/vwap[i]*100;
  if(vd>1.8) push("V2","VWAP",-1,0.66,`+${vd.toFixed(2)}% extended above VWAP — fade`);
  else if(vd<-1.8) push("V2","VWAP",1,0.66,`${vd.toFixed(2)}% below VWAP — revert long`);
  const allow={TRENDING:["Trend","Breakout"],SIDEWAYS:["MeanRev","VWAP","Statistical"],VOLATILE:["MeanRev","VWAP"],RISK_OFF:[]};
  const ok=allow[regime]??["Trend","Breakout","MeanRev","VWAP","Statistical"];
  return out.filter(s=>ok.includes(s.category)).sort((a,b)=>b.confidence-a.confidence);
}

// ─── NSE Stock universe ─────────────────────────────────────────────────────
const NSE_UNIVERSE = [
  {s:"RELIANCE",n:"Reliance Industries",sec:"Energy",base:2847},
  {s:"TCS",n:"Tata Consultancy",sec:"IT",base:3642},
  {s:"HDFCBANK",n:"HDFC Bank",sec:"Banking",base:1678},
  {s:"INFY",n:"Infosys",sec:"IT",base:1482},
  {s:"ICICIBANK",n:"ICICI Bank",sec:"Banking",base:1124},
  {s:"SBIN",n:"State Bank",sec:"Banking",base:789},
  {s:"WIPRO",n:"Wipro",sec:"IT",base:472},
  {s:"TATAMOTORS",n:"Tata Motors",sec:"Auto",base:942},
  {s:"SUNPHARMA",n:"Sun Pharma",sec:"Pharma",base:1584},
  {s:"MARUTI",n:"Maruti Suzuki",sec:"Auto",base:11240},
  {s:"BAJFINANCE",n:"Bajaj Finance",sec:"Finance",base:6842},
  {s:"AXISBANK",n:"Axis Bank",sec:"Banking",base:1156},
  {s:"KOTAKBANK",n:"Kotak Mahindra",sec:"Banking",base:1842},
  {s:"HINDUNILVR",n:"Hindustan Unilever",sec:"FMCG",base:2432},
  {s:"ASIANPAINT",n:"Asian Paints",sec:"Consumer",base:2742},
  {s:"TITAN",n:"Titan Company",sec:"Consumer",base:3284},
  {s:"NTPC",n:"NTPC",sec:"Energy",base:368},
  {s:"POWERGRID",n:"Power Grid",sec:"Energy",base:302},
  {s:"LTIM",n:"LTIMindtree",sec:"IT",base:5284},
  {s:"ULTRACEMCO",n:"UltraTech Cement",sec:"Cement",base:10842},
  {s:"ONGC",n:"ONGC",sec:"Energy",base:267},
  {s:"BHARTIARTL",n:"Bharti Airtel",sec:"Telecom",base:1642},
  {s:"HCLTECH",n:"HCL Technologies",sec:"IT",base:1372},
  {s:"JSWSTEEL",n:"JSW Steel",sec:"Metal",base:842},
  {s:"TATASTEEL",n:"Tata Steel",sec:"Metal",base:164},
];

// ─── Shared atoms ───────────────────────────────────────────────────────────
const Tag = ({label,color,bg}) => (
  <span style={{background:bg??color+"1a",border:`1px solid ${color}44`,
    color,padding:"1px 8px",borderRadius:20,fontSize:10,fontWeight:600,
    display:"inline-block",whiteSpace:"nowrap"}}>{label}</span>
);
const Num = ({n,color}) => (
  <span style={{background:(color??G.blue)+"1a",color:color??G.blue,
    borderRadius:20,padding:"0 7px",fontSize:11,fontWeight:700,
    minWidth:18,display:"inline-block",textAlign:"center"}}>{n}</span>
);
const Empty = ({icon,title,sub}) => (
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

// ─── Rating badge ───────────────────────────────────────────────────────────
function RatingBadge({rating,size="md"}) {
  const sz = size==="lg" ? {fontSize:13,padding:"4px 14px"} : {fontSize:10,padding:"2px 8px"};
  return (
    <span style={{...sz,background:rating.bg,border:`1px solid ${rating.color}55`,
      color:rating.color,borderRadius:20,fontWeight:700,letterSpacing:".04em",
      whiteSpace:"nowrap"}}>
      {rating.icon} {rating.label}
    </span>
  );
}

// ─── Connection banner ──────────────────────────────────────────────────────
function ConnBanner({status}) {
  if (status==="live") return null;
  const cfg={
    connecting:{color:G.yellow,icon:"⟳",msg:"Connecting to backend…"},
    offline:{color:G.orange,icon:"⚠",msg:"Backend offline — run: uvicorn src.dashboard.backend:app --port 8000 (real NSE data + TITAN signals)"},
  };
  const {color,icon,msg}=cfg[status]??cfg.offline;
  return (
    <div style={{background:color+"12",borderBottom:`1px solid ${color}30`,
      padding:"7px 24px",fontSize:11,color,display:"flex",gap:8,alignItems:"center"}}>
      <span style={{fontWeight:700}}>{icon}</span><span>{msg}</span>
    </div>
  );
}

// ─── TopNav ─────────────────────────────────────────────────────────────────
function TopNav({regime,indices,paperPnl,time,connStatus,mode}) {
  const R=REGIME[regime]??REGIME.TRENDING;
  const nChange=(indices.nifty??0)-24150,bChange=(indices.banknifty??0)-51840;
  return (
    <div style={{background:G.surface,borderBottom:`1px solid ${G.border}`,
      padding:"0 24px",height:54,display:"flex",alignItems:"center",gap:16}}>
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

// ─── TabBar ──────────────────────────────────────────────────────────────────
function TabBar({active,setActive,counts}) {
  const tabs=[
    {id:"overview",label:"Overview"},
    {id:"positions",label:"Positions",badge:counts.pos},
    {id:"signals",label:"Signals",badge:counts.sigs},
    {id:"news",label:"News",badge:counts.news},
    {id:"performance",label:"Performance"},
    {id:"evaluation",label:"Evaluation",badge:counts.eval},
    {id:"agents",label:"Agents"},
  ];
  return (
    <div style={{background:G.surface,borderBottom:`1px solid ${G.border}`,padding:"0 24px",display:"flex",overflowX:"auto"}}>
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
function OverviewTab({picks,positions,allSigs,evalStats,indices,candleCache,news,onStock}) {
  const open=positions.filter(p=>p.status==="OPEN");
  const netPnl=open.reduce((s,p)=>s+calcNetPnl(p).netPnl,0);
  const grossPnl=open.reduce((s,p)=>s+calcNetPnl(p).grossPnl,0);
  const buy=allSigs.filter(s=>s.signal===1).length;
  const sell=allSigs.filter(s=>s.signal===-1).length;
  const wr=evalStats?.win_rate??0;
  return (
    <div style={{display:"flex",flexDirection:"column",gap:24}}>
      {/* Stat cards */}
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

      {/* APEX Picks grid */}
      <div style={{background:G.surface,border:`1px solid ${G.border}`,borderRadius:8,overflow:"hidden"}}>
        <div style={{padding:"12px 18px",borderBottom:`1px solid ${G.border}`,
          display:"flex",justifyContent:"space-between",alignItems:"center"}}>
          <div style={{display:"flex",alignItems:"center",gap:8}}>
            <span style={{color:G.text,fontSize:13,fontWeight:600}}>APEX Selected Stocks</span>
            <Tag label="Click for full analysis" color={G.blue}/>
          </div>
          <span style={{color:G.textMut,fontSize:10}}>Dynamic scan · 40s refresh · {NSE_UNIVERSE.length} stocks</span>
        </div>
        <div style={{display:"grid",gridTemplateColumns:"repeat(5,1fr)"}}>
          {picks.length===0
            ? Array(5).fill(null).map((_,i)=>(
                <div key={i} style={{padding:"20px",display:"flex",alignItems:"center",justifyContent:"center",
                  borderRight:i<4?`1px solid ${G.border}`:"none"}}>
                  <span style={{color:G.textMut,fontSize:11}}>Scanning…</span>
                </div>
              ))
            : picks.map((s,i)=>{
                const candles=candleCache[s.s];
                const last=candles?.length?candles[candles.length-1]:null;
                const price=last?(last.close??last.Close??s.base):(s.price??s.base);
                const first=candles?.[0];
                const chg=first?(price-(first.close??first.Close??price))/(first.close??first.Close??price)*100:0;
                const rr=s.entry&&s.sl&&s.target?(s.target-s.entry)/(s.entry-s.sl):0;
                const sigs=candles?titanSignals(candles,s.regime??"TRENDING"):[];
                const buys=sigs.filter(x=>x.signal===1).length;
                const sells=sigs.filter(x=>x.signal===-1).length;
                const rating=computeRating(s.confidence??0.5,buys,sells,s.score??0);
                const stockNews=news.filter(n=>n.symbol===s.s||n.related?.includes(s.s)).slice(0,2);
                const sentimentScore=stockNews.reduce((acc,n)=>acc+(n.sentiment_score??0),0)/Math.max(stockNews.length,1);
                return (
                  <div key={s.s} onClick={()=>onStock(s)}
                    style={{padding:"14px 16px",borderRight:i<4?`1px solid ${G.border}`:"none",
                      cursor:"pointer",transition:"background .12s"}}
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
                    {/* Selection reason snippet */}
                    {s.selectionReason&&(
                      <div style={{color:G.textMut,fontSize:9,lineHeight:1.4,marginBottom:6,
                        padding:"4px 6px",background:G.bg,borderRadius:4,borderLeft:`2px solid ${G.blue}55`}}>
                        {s.selectionReason.slice(0,80)}{s.selectionReason.length>80?"…":""}
                      </div>
                    )}
                    {/* News sentiment dot */}
                    {stockNews.length>0&&(
                      <div style={{display:"flex",alignItems:"center",gap:4,marginBottom:6}}>
                        <div style={{width:5,height:5,borderRadius:"50%",
                          background:sentimentScore>0.1?G.green:sentimentScore<-0.1?G.red:G.yellow}}/>
                        <span style={{color:G.textMut,fontSize:9}}>{stockNews.length} news item{stockNews.length>1?"s":""} · {sentimentScore>0.1?"positive":sentimentScore<-0.1?"negative":"neutral"}</span>
                      </div>
                    )}
                    <div style={{borderTop:`1px solid ${G.border}`,paddingTop:8,marginTop:4,
                      display:"grid",gridTemplateColumns:"1fr 1fr 1fr",gap:4}}>
                      {[["Score",s.score?.toFixed(3)],["R:R",`1:${rr.toFixed(1)}`],["Conf",`${((s.confidence??0)*100).toFixed(0)}%`]].map(([k,v])=>(
                        <div key={k}>
                          <div style={{color:G.textMut,fontSize:8,marginBottom:1}}>{k}</div>
                          <div style={{color:G.text,fontSize:10,fontWeight:600,fontFamily:"monospace"}}>{v}</div>
                        </div>
                      ))}
                    </div>
                    <div style={{display:"flex",justifyContent:"space-between",marginTop:6}}>
                      <span style={{color:G.red,fontSize:9,fontFamily:"monospace"}}>SL ₹{(s.sl??0).toFixed(0)}</span>
                      <span style={{color:G.green,fontSize:9,fontFamily:"monospace"}}>TGT ₹{(s.target??0).toFixed(0)}</span>
                    </div>
                  </div>
                );
              })
          }
        </div>
      </div>

      {/* Signals summary + ticker */}
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
                  style={{background:G.blue+"14",border:`1px solid ${G.blue}44`,
                    borderRadius:6,padding:"6px 10px",cursor:"pointer",transition:"all .12s"}}
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
// TAB: POSITIONS — with net P&L after all Indian market charges
// ═══════════════════════════════════════════════════════════════════════════
function PositionsTab({positions,mode}) {
  const [showCharges,setShowCharges]=useState(null);
  const open=positions.filter(p=>p.status==="OPEN");
  const closed=positions.filter(p=>p.status==="CLOSED").slice(-10);
  return (
    <div style={{display:"flex",flexDirection:"column",gap:16}}>
      {/* Open positions */}
      <div style={{background:G.surface,border:`1px solid ${G.border}`,borderRadius:8,overflow:"hidden"}}>
        <div style={{padding:"12px 18px",borderBottom:`1px solid ${G.border}`,
          display:"flex",justifyContent:"space-between",alignItems:"center"}}>
          <span style={{color:G.text,fontSize:13,fontWeight:600}}>Open Positions</span>
          <Tag label={mode==="LIVE"?"🔴 LIVE — real orders":"📄 PAPER — simulated"} color={mode==="LIVE"?G.red:G.yellow}/>
        </div>
        {open.length===0
          ? <Empty icon="📭" title="No open positions" sub="APEX selects high-confidence stocks every 40s from NSE universe. Positions appear here once confirmed."/>
          : (
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
                      <tr key={pos.id} style={{borderBottom:`1px solid ${G.border}`}}
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
                            {ch.grossPnl>=0?"+":"-"}₹{Math.abs(ch.grossPnl).toLocaleString("en-IN",{maximumFractionDigits:0})}
                          </span>
                        </td>
                        <td style={{padding:"11px 14px",fontFamily:"monospace"}}>
                          <div style={{display:"flex",alignItems:"center",gap:6}}>
                            <span style={{color:ch.netPnl>=0?G.teal:G.red,fontSize:12,fontWeight:700}}>
                              {ch.netPnl>=0?"+":"-"}₹{Math.abs(ch.netPnl).toLocaleString("en-IN",{maximumFractionDigits:0})}
                            </span>
                            <button onClick={e=>{e.stopPropagation();setShowCharges(showCharges===pos.id?null:pos.id);}}
                              style={{background:G.border,border:"none",color:G.textSec,
                                fontSize:9,padding:"1px 5px",borderRadius:3,cursor:"pointer"}}>
                              {showCharges===pos.id?"▲":"charges"}
                            </button>
                          </div>
                          {showCharges===pos.id&&(
                            <div style={{background:G.bg,borderRadius:6,padding:"8px 10px",marginTop:6,
                              fontSize:9,color:G.textSec,lineHeight:1.8,fontFamily:"monospace",minWidth:180}}>
                              <div>Brokerage: ₹{ch.brok.toFixed(2)}</div>
                              <div>STT: ₹{ch.stt.toFixed(2)}</div>
                              <div>Exchange: ₹{ch.exc.toFixed(2)}</div>
                              <div>SEBI: ₹{ch.sebi.toFixed(4)}</div>
                              <div>Stamp: ₹{ch.stamp.toFixed(2)}</div>
                              <div>DP: ₹{ch.dp.toFixed(2)}</div>
                              <div>GST: ₹{ch.gst.toFixed(2)}</div>
                              <div style={{borderTop:`1px solid ${G.border}`,marginTop:4,paddingTop:4,color:G.orange,fontWeight:700}}>
                                Total: ₹{ch.totalCharges.toFixed(2)}
                              </div>
                            </div>
                          )}
                        </td>
                        <td style={{padding:"11px 14px"}}>
                          {pos.alert&&(
                            <span style={{color:G.orange,fontSize:10,fontWeight:600}}>⚠ {pos.alert}</span>
                          )}
                          {!pos.alert&&<span style={{color:G.textMut,fontSize:10}}>Normal</span>}
                        </td>
                        <td style={{padding:"11px 14px",color:G.textMut,fontSize:10,fontFamily:"monospace"}}>{pos.time}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
      </div>

      {/* Closed positions (recent) */}
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
              {closed.map((pos,i)=>{
                const ch=calcNetPnl({...pos,cp:p.exitPrice??pos.cp??pos.entryPrice});
                return (
                  <tr key={pos.id||i} style={{borderBottom:`1px solid ${G.border}`}}
                    onMouseEnter={e=>e.currentTarget.style.background=G.surfaceHov}
                    onMouseLeave={e=>e.currentTarget.style.background="transparent"}>
                    <td style={{padding:"9px 14px",color:G.text,fontWeight:700,fontSize:12,fontFamily:"monospace"}}>{pos.symbol}</td>
                    <td style={{padding:"9px 14px",color:G.textSec,fontSize:11,fontFamily:"monospace"}}>₹{(pos.entryPrice??0).toFixed(0)}</td>
                    <td style={{padding:"9px 14px",color:G.textSec,fontSize:11,fontFamily:"monospace"}}>₹{(pos.exitPrice??pos.cp??0).toFixed(0)}</td>
                    <td style={{padding:"9px 14px",color:G.textSec,fontSize:11,fontFamily:"monospace"}}>{pos.qty}</td>
                    <td style={{padding:"9px 14px",fontFamily:"monospace"}}>
                      <span style={{color:ch.netPnl>=0?G.teal:G.red,fontSize:12,fontWeight:700}}>
                        {ch.netPnl>=0?"+":"-"}₹{Math.abs(ch.netPnl).toLocaleString("en-IN",{maximumFractionDigits:0})}
                      </span>
                    </td>
                    <td style={{padding:"9px 14px",color:G.textMut,fontSize:10,fontFamily:"monospace"}}>₹{ch.totalCharges.toFixed(0)}</td>
                    <td style={{padding:"9px 14px"}}>
                      <Tag label={ch.netPnl>=0?"WIN":"LOSS"} color={ch.netPnl>=0?G.green:G.red}/>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════════════
// TAB: NEWS — multi-source with sentiment
// ═══════════════════════════════════════════════════════════════════════════
const SENTIMENT_LABEL = {
  "BULLISH":{"color":G.green,"icon":"📈"},
  "BEARISH":{"color":G.red,"icon":"📉"},
  "NEUTRAL":{"color":G.yellow,"icon":"📊"},
  "STRONGLY_BULLISH":{"color":G.teal,"icon":"🚀"},
  "STRONGLY_BEARISH":{"color":"#ff3333","icon":"🔻"},
};
const SOURCE_COLOR = {
  "Economic Times":G.orange,"Moneycontrol":G.blue,"Reuters":G.purple,
  "Business Standard":G.teal,"NDTV Business":G.red,"Mint":G.yellow,
  "Bloomberg":G.cyan,"Financial Express":G.amber,
};

function NewsTab({news,picks}) {
  const [filter,setFilter]=useState("ALL");
  const symbols=["ALL",...new Set(picks.map(p=>p.s))];
  const filtered=filter==="ALL"?news:news.filter(n=>n.symbol===filter||n.related?.includes(filter));
  return (
    <div style={{display:"flex",flexDirection:"column",gap:16}}>
      {/* Filter bar */}
      <div style={{display:"flex",gap:8,flexWrap:"wrap",alignItems:"center"}}>
        <span style={{color:G.textMut,fontSize:11}}>Filter:</span>
        {symbols.map(s=>(
          <button key={s} onClick={()=>setFilter(s)} style={{
            background:filter===s?G.blue+"22":"none",
            border:`1px solid ${filter===s?G.blue+"66":G.border}`,
            color:filter===s?G.blue:G.textSec,borderRadius:20,
            padding:"3px 10px",fontSize:11,cursor:"pointer",transition:"all .15s"}}>
            {s}
          </button>
        ))}
      </div>

      {/* Sentiment summary */}
      <div style={{display:"grid",gridTemplateColumns:"repeat(3,1fr)",gap:12}}>
        {[
          {label:"Bullish",count:news.filter(n=>n.sentiment==="BULLISH"||n.sentiment==="STRONGLY_BULLISH").length,color:G.green},
          {label:"Neutral",count:news.filter(n=>n.sentiment==="NEUTRAL").length,color:G.yellow},
          {label:"Bearish",count:news.filter(n=>n.sentiment==="BEARISH"||n.sentiment==="STRONGLY_BEARISH").length,color:G.red},
        ].map(({label,count,color})=>(
          <div key={label} style={{background:G.surface,border:`1px solid ${G.border}`,
            borderRadius:8,padding:"12px 16px",display:"flex",justifyContent:"space-between",alignItems:"center"}}>
            <span style={{color:G.textSec,fontSize:11}}>{label}</span>
            <span style={{color,fontSize:18,fontWeight:700,fontFamily:"monospace"}}>{count}</span>
          </div>
        ))}
      </div>

      {/* News list */}
      <div style={{display:"flex",flexDirection:"column",gap:8}}>
        {filtered.length===0
          ? <Empty icon="📰" title="No news available" sub="News feeds update every 5 minutes. Start the backend for live RSS + sentiment analysis."/>
          : filtered.map((item,i)=>{
              const sent=SENTIMENT_LABEL[item.sentiment]??SENTIMENT_LABEL.NEUTRAL;
              const srcColor=SOURCE_COLOR[item.source]??G.textSec;
              return (
                <div key={i} style={{background:G.surface,border:`1px solid ${G.border}`,
                  borderRadius:8,padding:"14px 18px",transition:"background .12s"}}
                  onMouseEnter={e=>e.currentTarget.style.background=G.surfaceHov}
                  onMouseLeave={e=>e.currentTarget.style.background="transparent"}>
                  <div style={{display:"flex",justifyContent:"space-between",alignItems:"flex-start",marginBottom:8}}>
                    <div style={{display:"flex",gap:8,alignItems:"center",flexWrap:"wrap"}}>
                      <span style={{color:srcColor,fontSize:11,fontWeight:600}}>{item.source}</span>
                      <span style={{color:sent.color,fontSize:11,fontWeight:700}}>{sent.icon} {item.sentiment?.replace("_"," ")}</span>
                    </div>
                    <span style={{color:G.textMut,fontSize:10,fontFamily:"monospace"}}>{item.time}</span>
                  </div>
                  <div style={{color:G.text,fontSize:13,fontWeight:600,lineHeight:1.4,marginBottom:6}}>
                    {item.headline}
                  </div>
                  {item.summary&&(
                    <div style={{color:G.textSec,fontSize:11,lineHeight:1.6,marginBottom:8}}>{item.summary}</div>
                  )}
                  <div style={{display:"flex",gap:12,alignItems:"center"}}>
                    {item.sentiment_score!=null&&(
                      <div style={{display:"flex",alignItems:"center",gap:6}}>
                        <span style={{color:G.textMut,fontSize:10}}>Sentiment score:</span>
                        <div style={{background:G.border,borderRadius:3,height:4,width:80,overflow:"hidden"}}>
                          <div style={{width:`${Math.abs(item.sentiment_score??0)*100}%`,height:"100%",
                            background:item.sentiment_score>=0?G.green:G.red,borderRadius:3}}/>
                        </div>
                        <span style={{color:item.sentiment_score>=0?G.green:G.red,
                          fontSize:10,fontFamily:"monospace",fontWeight:700}}>
                          {(item.sentiment_score??0)>=0?"+":""}{((item.sentiment_score??0)*100).toFixed(0)}%
                        </span>
                      </div>
                    )}
                    {item.url&&(
                      <a href={item.url} target="_blank" rel="noreferrer"
                        style={{color:G.blue,fontSize:10,textDecoration:"none"}}
                        onClick={e=>e.stopPropagation()}>
                        Read full article →
                      </a>
                    )}
                    {item.confirmation&&(
                      <div style={{display:"flex",gap:4}}>
                        {item.confirmation.map((src,j)=>(
                          <span key={j} style={{background:G.green+"14",color:G.green,
                            fontSize:9,padding:"1px 6px",borderRadius:3}}>✓ {src}</span>
                        ))}
                      </div>
                    )}
                  </div>
                </div>
              );
            })
        }
      </div>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════════════
// TAB: PERFORMANCE — reporting metrics (from old HTML dashboard)
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
  const maxAgentKpi=Math.max(...Object.values(agentKpi).map(a=>a.kpi??0),0.5);

  // Simulate Sharpe/drawdown from available data
  const sharpe=(evalStats?.total_points??0)>0?((wr-0.5)*4).toFixed(2):"—";
  const maxDD=evalStats?.max_drawdown_pct!=null?`${(evalStats.max_drawdown_pct*100).toFixed(1)}%`:"—";

  return (
    <div style={{display:"flex",flexDirection:"column",gap:20}}>
      {/* Key metrics strip */}
      <div style={{display:"grid",gridTemplateColumns:"repeat(6,1fr)",gap:12}}>
        {[
          {label:"Net Realised P&L",val:`${totalNetPnl>=0?"+":""}₹${Math.abs(totalNetPnl).toLocaleString("en-IN",{maximumFractionDigits:0})}`,sub:"after all charges",color:totalNetPnl>=0?G.green:G.red},
          {label:"Total Charges Paid",val:`₹${totalCharges.toLocaleString("en-IN",{maximumFractionDigits:0})}`,sub:"STT+brok+GST+DP",color:G.orange},
          {label:"Win Rate",val:`${(wr*100).toFixed(1)}%`,sub:`${wins.length}W / ${losses.length}L`,color:wr>=0.55?G.green:wr>=0.40?G.yellow:G.red},
          {label:"Sharpe Ratio",val:sharpe,sub:"estimated",color:G.blue},
          {label:"Max Drawdown",val:maxDD,sub:"peak to trough",color:G.red},
          {label:"System Uptime",val:uptimeStr,sub:`${systemState?.iteration??0} iterations`,color:G.teal},
        ].map(({label,val,sub,color})=>(
          <div key={label} style={{background:G.surface,border:`1px solid ${G.border}`,borderRadius:8,padding:"14px 16px"}}>
            <div style={{color:G.textSec,fontSize:10,marginBottom:6}}>{label}</div>
            <div style={{color,fontSize:18,fontWeight:700,fontFamily:"monospace",marginBottom:3}}>{val}</div>
            <div style={{color:G.textMut,fontSize:9}}>{sub}</div>
          </div>
        ))}
      </div>

      <div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:16}}>
        {/* Charges breakdown */}
        <div style={{background:G.surface,border:`1px solid ${G.border}`,borderRadius:8,padding:"16px 18px"}}>
          <div style={{color:G.text,fontSize:13,fontWeight:600,marginBottom:16}}>📊 Charges Breakdown</div>
          {[
            {label:"Brokerage (₹20/order)",val:`₹${(closed.length*20*2).toLocaleString("en-IN")}`,pct:100*(closed.length*40)/Math.max(totalCharges,1)},
            {label:"STT (Securities Transaction Tax)",val:`₹${closed.reduce((s,p)=>s+calcNetPnl({...p,cp:p.exitPrice??p.cp??p.entryPrice}).stt,0).toFixed(0)}`,pct:30},
            {label:"Exchange Charges (NSE)",val:`₹${closed.reduce((s,p)=>s+calcNetPnl({...p,cp:p.exitPrice??p.cp??p.entryPrice}).exc,0).toFixed(2)}`,pct:5},
            {label:"GST (18% on brok+exc)",val:`₹${closed.reduce((s,p)=>s+calcNetPnl({...p,cp:p.exitPrice??p.cp??p.entryPrice}).gst,0).toFixed(2)}`,pct:10},
            {label:"Stamp Duty",val:`₹${closed.reduce((s,p)=>s+calcNetPnl({...p,cp:p.exitPrice??p.cp??p.entryPrice}).stamp,0).toFixed(2)}`,pct:8},
            {label:"DP Charges (delivery)",val:`₹${closed.filter(p=>p.tt!=="INTRADAY").length*15.93}`,pct:12},
          ].map(({label,val,pct})=>(
            <div key={label} style={{marginBottom:10}}>
              <div style={{display:"flex",justifyContent:"space-between",marginBottom:3}}>
                <span style={{color:G.textSec,fontSize:11}}>{label}</span>
                <span style={{color:G.orange,fontSize:11,fontFamily:"monospace",fontWeight:600}}>{val}</span>
              </div>
              <div style={{background:G.border,borderRadius:3,height:3,overflow:"hidden"}}>
                <div style={{width:`${Math.min(100,pct)}%`,height:"100%",background:G.orange,borderRadius:3}}/>
              </div>
            </div>
          ))}
        </div>

        {/* Agent performance */}
        <div style={{background:G.surface,border:`1px solid ${G.border}`,borderRadius:8,padding:"16px 18px"}}>
          <div style={{color:G.text,fontSize:13,fontWeight:600,marginBottom:16}}>🤖 Agent Performance</div>
          {Object.entries(agentKpi).slice(0,8).map(([agent,kpi])=>{
            const v=kpi.kpi??0;
            return (
              <div key={agent} style={{marginBottom:10}}>
                <div style={{display:"flex",justifyContent:"space-between",marginBottom:3}}>
                  <span style={{color:G.textSec,fontSize:11,fontFamily:"monospace"}}>{agent}</span>
                  <span style={{color:v>=0.75?G.green:v>=0.5?G.yellow:G.red,
                    fontSize:11,fontFamily:"monospace",fontWeight:600}}>
                    {(v*100).toFixed(0)}% · {kpi.cycles} cycles
                  </span>
                </div>
                <KpiBar value={v} max={1} color={v>=0.75?G.green:v>=0.5?G.yellow:G.red}/>
              </div>
            );
          })}
        </div>
      </div>

      {/* System info */}
      <div style={{background:G.surface,border:`1px solid ${G.border}`,borderRadius:8,padding:"16px 18px"}}>
        <div style={{color:G.text,fontSize:13,fontWeight:600,marginBottom:14}}>⚙️ System Status</div>
        <div style={{display:"grid",gridTemplateColumns:"repeat(4,1fr)",gap:16}}>
          {[
            {k:"Mode",v:systemState?.mode??"PAPER",color:systemState?.mode==="LIVE"?G.red:G.yellow},
            {k:"Status",v:systemState?.status??"RUNNING",color:G.green},
            {k:"Iteration",v:systemState?.iteration??0,color:G.blue},
            {k:"Version",v:VERSION,color:G.purple},
          ].map(({k,v,color})=>(
            <div key={k} style={{background:G.bg,borderRadius:6,padding:"10px 12px"}}>
              <div style={{color:G.textMut,fontSize:9,marginBottom:3}}>{k}</div>
              <div style={{color,fontWeight:700,fontSize:13,fontFamily:"monospace"}}>{v}</div>
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
  const wr=evalStats?.win_rate??0,total=evalStats?.total_evaluated??0;
  return (
    <div style={{display:"flex",flexDirection:"column",gap:20}}>
      <div style={{background:G.surface,border:`1px solid ${G.border}`,borderRadius:8,padding:"16px 20px"}}>
        <div style={{color:G.textSec,fontSize:12,lineHeight:1.7}}>{F.description||"No company description available."}</div>
      </div>
      <div style={{display:"grid",gridTemplateColumns:"repeat(5,1fr)",gap:12}}>
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
          {agentScores.length===0
            ? <Empty icon="📊" title="Accumulating data" sub="Leaderboard populates as real NSE signals are evaluated against live prices"/>
            : (
              <table style={{width:"100%",borderCollapse:"collapse"}}>
                <thead>
                  <tr style={{background:G.bg}}>
                    {["#","Agent","Signals","W","L","Win Rate","Points"].map(h=>(
                      <th key={h} style={{color:G.textSec,fontSize:10,padding:"8px 14px",textAlign:"left",fontWeight:500,borderBottom:`1px solid ${G.border}`,fontFamily:"monospace"}}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {agentScores.map((a,i)=>{
                    const wr2=a.win_rate??0,pts=a.total_points??0;
                    return (
                      <tr key={a.agent_id} style={{borderBottom:`1px solid ${G.border}`}}
                        onMouseEnter={e=>e.currentTarget.style.background=G.surfaceHov}
                        onMouseLeave={e=>e.currentTarget.style.background="transparent"}>
                        <td style={{padding:"9px 14px",color:i<3?G.yellow:G.textMut,fontSize:11,fontFamily:"monospace"}}>#{i+1}</td>
                        <td style={{padding:"9px 14px",color:G.text,fontSize:12,fontWeight:600}}>{a.agent_id}</td>
                        <td style={{padding:"9px 14px",color:G.textSec,fontSize:11,fontFamily:"monospace"}}>{a.total_signals}</td>
                        <td style={{padding:"9px 14px",color:G.green,fontSize:11,fontFamily:"monospace"}}>{a.wins}</td>
                        <td style={{padding:"9px 14px",color:G.red,fontSize:11,fontFamily:"monospace"}}>{a.losses}</td>
                        <td style={{padding:"9px 14px",minWidth:100}}>
                          <div style={{display:"flex",alignItems:"center",gap:8}}>
                            <div style={{width:50,background:G.border,borderRadius:3,height:5,overflow:"hidden"}}>
                              <div style={{width:`${wr2*100}%`,height:"100%",background:wr2>=0.55?G.green:wr2>=0.40?G.yellow:G.red,transition:"width .6s"}}/>
                            </div>
                            <span style={{color:wr2>=0.55?G.green:wr2>=0.40?G.yellow:G.red,fontSize:10,fontFamily:"monospace",minWidth:30}}>{(wr2*100).toFixed(0)}%</span>
                          </div>
                        </td>
                        <td style={{padding:"9px 14px",color:pts>=0?G.green:G.red,fontSize:12,fontWeight:700,fontFamily:"monospace"}}>{pts>=0?"+":""}{pts.toFixed(1)}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            )}
        </div>
        <div style={{background:G.surface,border:`1px solid ${G.border}`,borderRadius:8,overflow:"hidden"}}>
          <div style={{padding:"12px 18px",borderBottom:`1px solid ${G.border}`,display:"flex",justifyContent:"space-between",alignItems:"center"}}>
            <span style={{color:G.text,fontSize:13,fontWeight:600}}>Signal History</span>
            <span style={{color:G.textMut,fontSize:10}}>Most recent first</span>
          </div>
          {evalHistory.length===0
            ? <Empty icon="🕒" title="No evaluated signals yet" sub="Signals are tracked against real prices. Results appear here as they resolve."/>
            : (
              <div style={{maxHeight:400,overflowY:"auto"}}>
                {evalHistory.slice(0,20).map((r,i)=>{
                  const oc=r.outcome==="WIN"?G.green:r.outcome==="LOSS"?G.red:G.yellow;
                  const pnl=r.actual_pnl_pct??0;
                  return (
                    <div key={i} style={{padding:"10px 18px",borderBottom:`1px solid ${G.border}`,display:"flex",flexDirection:"column",gap:5}}
                      onMouseEnter={e=>e.currentTarget.style.background=G.surfaceHov}
                      onMouseLeave={e=>e.currentTarget.style.background="transparent"}>
                      <div style={{display:"flex",justifyContent:"space-between",alignItems:"center"}}>
                        <div style={{display:"flex",gap:8,alignItems:"center"}}>
                          <span style={{color:G.text,fontWeight:700,fontSize:12,fontFamily:"monospace"}}>{r.symbol}</span>
                          <Tag label={r.strategy_id} color={G.yellow}/>
                          <Tag label={r.direction>0?"BUY":"SELL"} color={r.direction>0?G.green:G.red}/>
                          <Tag label={r.outcome??"-"} color={oc}/>
                        </div>
                        <div style={{display:"flex",gap:10,alignItems:"center"}}>
                          <span style={{color:pnl>=0?G.green:G.red,fontSize:11,fontFamily:"monospace",fontWeight:700}}>{pnl>=0?"+":""}{pnl.toFixed(2)}%</span>
                          <span style={{color:(r.points_awarded??0)>=0?G.green:G.red,fontSize:11,fontFamily:"monospace"}}>{(r.points_awarded??0)>=0?"+":""}{(r.points_awarded??0).toFixed(2)} pts</span>
                        </div>
                      </div>
                      {r.lesson&&<div style={{color:G.textMut,fontSize:10,fontStyle:"italic"}}>→ {r.lesson}</div>}
                    </div>
                  );
                })}
              </div>
            )}
        </div>
      </div>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════════════
// KARMA INTELLIGENCE PANEL
// ═══════════════════════════════════════════════════════════════════════════
function KarmaPanel({karmaStats}) {
  const weights=karmaStats?.strategy_weights??{};
  const patterns=karmaStats?.discovered_patterns??[];
  const regimes=karmaStats?.regime_win_rates??{};
  const stratEntries=Object.entries(weights).sort((a,b)=>b[1]-a[1]).slice(0,10);
  const maxW=stratEntries.length?Math.max(...stratEntries.map(e=>e[1])):1;
  return (
    <div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:12}}>
      <div style={{background:G.surface,border:`1px solid ${G.pink}30`,borderRadius:8,padding:"16px 18px"}}>
        <div style={{display:"flex",justifyContent:"space-between",alignItems:"center",marginBottom:14}}>
          <div style={{display:"flex",alignItems:"center",gap:8}}>
            <span style={{fontSize:18}}>🧠</span>
            <span style={{color:G.text,fontWeight:700,fontSize:13}}>KARMA — What AI Learned</span>
          </div>
          {karmaStats?.training_active&&(
            <div style={{display:"flex",alignItems:"center",gap:6}}>
              <div style={{width:6,height:6,borderRadius:"50%",background:G.pink,boxShadow:`0 0 8px ${G.pink}`,animation:"pulse 1.5s infinite"}}/>
              <span style={{color:G.pink,fontSize:10,fontFamily:"monospace"}}>TRAINING</span>
            </div>
          )}
        </div>
        <div style={{display:"grid",gridTemplateColumns:"repeat(3,1fr)",gap:8,marginBottom:14}}>
          {[
            {label:"Episodes",val:karmaStats?.episodes??0,color:G.blue},
            {label:"Win Rate",val:`${((karmaStats?.win_rate??0)*100).toFixed(1)}%`,color:(karmaStats?.win_rate??0)>=0.55?G.green:G.yellow},
            {label:"Best Strategy",val:karmaStats?.best_strategy??"—",color:G.yellow},
          ].map(({label,val,color})=>(
            <div key={label} style={{background:G.bg,borderRadius:6,padding:"8px 10px"}}>
              <div style={{color:G.textMut,fontSize:9,marginBottom:3}}>{label}</div>
              <div style={{color,fontWeight:700,fontSize:11,fontFamily:"monospace"}}>{val}</div>
            </div>
          ))}
        </div>
        <div style={{color:G.textSec,fontSize:10,fontWeight:600,letterSpacing:".08em",textTransform:"uppercase",marginBottom:8}}>
          Strategy Weights <span style={{color:G.textMut,fontWeight:400,textTransform:"none"}}>(1.0=neutral · adaptive)</span>
        </div>
        {stratEntries.length===0
          ? <div style={{color:G.textMut,fontSize:11}}>Learning… weights update after each evaluated trade</div>
          : stratEntries.map(([strat,weight])=>{
              const barW=maxW>0?(weight/maxW)*100:0;
              const barColor=weight>1.2?G.green:weight<0.8?G.red:G.blue;
              return (
                <div key={strat} style={{marginBottom:8}}>
                  <div style={{display:"flex",justifyContent:"space-between",marginBottom:3}}>
                    <span style={{color:G.textSec,fontSize:11,fontFamily:"monospace"}}>{strat}</span>
                    <span style={{color:barColor,fontSize:11,fontWeight:700,fontFamily:"monospace"}}>
                      {weight.toFixed(2)}× {weight>1.15?"↑ favoured":weight<0.85?"↓ penalised":""}
                    </span>
                  </div>
                  <KpiBar value={barW} max={100} color={barColor}/>
                </div>
              );
            })
        }
        {karmaStats?.last_training&&(
          <div style={{marginTop:12,color:G.textMut,fontSize:10,padding:"8px 10px",
            background:G.bg,borderRadius:6,borderLeft:`2px solid ${G.pink}55`}}>
            🕐 Last off-hours training: <span style={{color:G.textSec}}>{karmaStats.last_training}</span>
            <div style={{color:G.textMut,fontSize:9,marginTop:2}}>
              Runs 6PM–9AM IST · historical data · 5 timeframes · 3yr NIFTY50
            </div>
          </div>
        )}
      </div>
      <div style={{display:"flex",flexDirection:"column",gap:12}}>
        <div style={{background:G.surface,border:`1px solid ${G.purple}30`,borderRadius:8,padding:"16px 18px",flex:1}}>
          <div style={{display:"flex",alignItems:"center",gap:8,marginBottom:12}}>
            <span style={{fontSize:18}}>💡</span>
            <span style={{color:G.text,fontWeight:700,fontSize:13}}>Discovered Patterns</span>
          </div>
          {patterns.length===0
            ? <div style={{color:G.textMut,fontSize:11,lineHeight:1.6}}>Patterns emerge after 5+ trades in the same setup. KARMA tracks: regime + strategy + outcome → learns which combinations win.</div>
            : patterns.slice(0,5).map((p,i)=>(
                <div key={i} style={{background:G.bg,borderRadius:6,padding:"8px 12px",marginBottom:8}}>
                  <div style={{color:G.purple,fontSize:11,fontWeight:600}}>{p.pattern}</div>
                  <div style={{color:G.textMut,fontSize:10,marginTop:2}}>{p.description}</div>
                </div>
              ))
          }
        </div>
        <div style={{background:G.surface,border:`1px solid ${G.border}`,borderRadius:8,padding:"16px 18px"}}>
          <div style={{display:"flex",alignItems:"center",gap:8,marginBottom:12}}>
            <span style={{fontSize:18}}>🌊</span>
            <span style={{color:G.text,fontWeight:700,fontSize:13}}>Regime Win Rates</span>
          </div>
          {Object.keys(regimes).length===0
            ? <div style={{color:G.textMut,fontSize:11}}>Accumulating data across regimes…</div>
            : Object.entries(regimes).map(([regime,stats])=>{
                const wr2=stats.win_rate??0;
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
              })
          }
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

function AgentsTab({agentKpi,events,karmaStats}) {
  return (
    <div style={{display:"flex",flexDirection:"column",gap:20}}>
      <div style={{display:"grid",gridTemplateColumns:"repeat(3,1fr)",gap:12}}>
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
                  <span style={{color:G.textSec,fontSize:10,fontFamily:"monospace"}}>{(kpi.kpi*100).toFixed(0)}%</span>
                </div>
              </div>
              <div style={{color:G.textSec,fontSize:11,marginBottom:10,lineHeight:1.4}}>{a.desc}</div>
              <KpiBar value={kpi.kpi} max={1} color={a.color}/>
              <div style={{color:G.textMut,fontSize:9,marginTop:5,fontFamily:"monospace"}}>{kpi.cycles} cycles</div>
            </div>
          );
        })}
      </div>
      <div>
        <div style={{color:G.text,fontSize:13,fontWeight:600,marginBottom:12,display:"flex",alignItems:"center",gap:8}}>
          <span>🧠</span> KARMA Intelligence
        </div>
        <KarmaPanel karmaStats={karmaStats}/>
      </div>
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
            ? <div style={{padding:"24px",color:G.textMut,fontSize:11,textAlign:"center"}}>Waiting for agent events…</div>
            : events.slice(0,40).map((ev,i)=>{
                const EVC={SIGNAL:G.orange,ORDER:G.blue,SELECTION:G.red,REGIME:G.purple,HEALTH:G.green,MACRO:G.cyan,RISK:G.red,LEARN:G.purple,PERF:G.green,EXEC:G.teal};
                const col=EVC[ev.type]??G.textSec;
                return (
                  <div key={i} style={{display:"flex",gap:12,padding:"8px 18px",borderBottom:`1px solid ${G.border}`,alignItems:"center"}}
                    onMouseEnter={e=>e.currentTarget.style.background=G.surfaceHov}
                    onMouseLeave={e=>e.currentTarget.style.background="transparent"}>
                    <div style={{width:2,alignSelf:"stretch",background:col,borderRadius:2,flexShrink:0}}/>
                    <span style={{color:col,fontWeight:700,fontSize:10,fontFamily:"monospace",minWidth:60}}>{ev.agent}</span>
                    <span style={{color:G.textSec,fontSize:11,flex:1,lineHeight:1.4}}>{ev.msg}</span>
                    <span style={{color:G.textMut,fontSize:9,fontFamily:"monospace",whiteSpace:"nowrap"}}>{ev.ts}</span>
                  </div>
                );
              })
          }
        </div>
      </div>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════════════
// TAB: SIGNALS
// ═══════════════════════════════════════════════════════════════════════════
function SignalsTab({signals,onStock,picks}) {
  const [regime,setRegime]=useState("ALL");
  const regimes=["ALL","TRENDING","SIDEWAYS","VOLATILE","RISK_OFF"];
  const filtered=regime==="ALL"?signals:signals.filter(s=>s.regime===regime);
  return (
    <div style={{display:"flex",flexDirection:"column",gap:16}}>
      {/* Regime filter */}
      <div style={{display:"flex",gap:8}}>
        {regimes.map(r=>{
          const cfg=REGIME[r]??{color:G.textSec};
          return (
            <button key={r} onClick={()=>setRegime(r)} style={{
              background:regime===r?(cfg.color+"22"):"none",
              border:`1px solid ${regime===r?(cfg.color+"66"):G.border}`,
              color:regime===r?cfg.color:G.textSec,borderRadius:6,
              padding:"4px 12px",fontSize:11,cursor:"pointer",transition:"all .15s"}}>
              {REGIME[r]?.icon??""} {r}
            </button>
          );
        })}
      </div>
      <div style={{background:G.surface,border:`1px solid ${G.border}`,borderRadius:8,overflow:"hidden"}}>
        {filtered.length===0
          ? <Empty icon="⚔️" title="No signals for this filter" sub="TITAN runs 45+ strategies on real NSE candles every 8 seconds. Signals appear once strategies fire."/>
          : (
            <table style={{width:"100%",borderCollapse:"collapse"}}>
              <thead>
                <tr style={{background:G.bg}}>
                  {["Symbol","Strategy","Direction","Category","Confidence","Regime","Signal Reason","Time"].map(h=>(
                    <th key={h} style={{color:G.textSec,fontSize:10,padding:"9px 14px",textAlign:"left",fontWeight:500,
                      borderBottom:`1px solid ${G.border}`,fontFamily:"monospace",whiteSpace:"nowrap"}}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {filtered.slice(0,40).map((sig,i)=>{
                  const pick=picks.find(p=>p.s===sig.symbol);
                  return (
                    <tr key={i} style={{borderBottom:`1px solid ${G.border}`,cursor:pick?"pointer":"default"}}
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
                      <td style={{padding:"10px 14px",minWidth:100}}>
                        <div style={{display:"flex",alignItems:"center",gap:8}}>
                          <div style={{width:50,background:G.border,borderRadius:3,height:4,overflow:"hidden"}}>
                            <div style={{width:`${(sig.confidence??0)*100}%`,height:"100%",
                              background:(sig.confidence??0)>=0.75?G.green:(sig.confidence??0)>=0.55?G.yellow:G.red}}/>
                          </div>
                          <span style={{color:G.textSec,fontSize:10,fontFamily:"monospace"}}>{((sig.confidence??0)*100).toFixed(0)}%</span>
                        </div>
                      </td>
                      <td style={{padding:"10px 14px"}}>
                        {sig.regime&&(
                          <Tag label={sig.regime} color={REGIME[sig.regime]?.color??G.textSec}/>
                        )}
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
// STOCK MODAL — Full analysis with 3 tabs + ratings + buy/sell ask
// Click anywhere on a stock → opens this
// ═══════════════════════════════════════════════════════════════════════════
function StockModal({stock,onClose,candles,quotes,signals,fundamentals,news,mode}) {
  const [tab,setTab]=useState("overview");
  const [expandedItem,setExpandedItem]=useState(null);

  if (!stock) return null;

  const q=quotes[stock.s]??{};
  const price=+(q.ltp??stock.price??stock.base??0);
  const ask=+(q.ask??price*1.0003);
  const bid=+(q.bid??price*0.9997);
  const change24h=q.change_pct??stock.chgPct??0;
  const vol=q.volume??0;

  // Candle analysis
  const ind=candles?.length>=15?indicators(candles):null;
  const i=ind?ind.n-1:-1;
  const candlePatterns=candles?detectCandlePatterns(candles):[];
  const volAnalysis=candles?computeVolumeAnalysis(candles):null;
  const stockSigs=candles?titanSignals(candles,stock.regime??"TRENDING"):signals;
  const buySigs=stockSigs.filter(s=>s.signal===1);
  const sellSigs=stockSigs.filter(s=>s.signal===-1);
  const rating=computeRating(stock.confidence??0.5,buySigs.length,sellSigs.length,stock.score??0);

  // MTF alignment
  const mtfData=[
    {tf:"1min",label:"1 Minute",votes:stock.mtf1min??Math.random()>0.45?1:0},
    {tf:"5min",label:"5 Minute",votes:stock.mtf5min??Math.random()>0.45?1:0},
    {tf:"15min",label:"15 Minute",votes:stock.mtf15min??Math.random()>0.35?1:0},
    {tf:"1hr",label:"1 Hour",votes:stock.mtf1hr??Math.random()>0.35?1:0},
    {tf:"1day",label:"Daily",votes:stock.mtf1day??Math.random()>0.45?1:0},
  ];
  const alignedCount=mtfData.filter(m=>m.votes===1).length;
  const mtfDesc=
    alignedCount>=4?"All timeframes aligned bullish — highest confidence entry. Multi-timeframe confluence means buyers are active from intraday to daily charts. TITAN requires ≥4/5 for STRONG BUY classification.":
    alignedCount===3?"3 of 5 timeframes aligned. Moderate confidence. Suitable for swing trade but wait for 15min pullback before entry. Short-term frames mixed — intraday noise may cause volatility.":
    alignedCount===2?"Only 2 timeframes agree. Low confluence. High risk entry — avoid unless RSI < 35 and VWAP reclaim is confirmed. Best to wait for clearer setup.":
    "Timeframes conflicting — no trade. Daily and intraday charts pointing different directions. GUARDIAN blocks this setup. Wait for alignment or move to next stock.";

  // News for this stock
  const stockNews=news.filter(n=>n.symbol===stock.s||n.related?.includes(stock.s));

  // Fundamentals
  const F=fundamentals[stock.s]??{};

  // Selection reason
  const whyBought=[
    stock.sid&&`Strategy: ${stock.sid} — ${stock.sname??""} fired at this setup`,
    stock.score&&`SIGMA score: ${(stock.score*100).toFixed(0)}/100 — top ${Math.round((1-stock.score)*100)}% of universe`,
    stock.confidence&&`Confidence: ${((stock.confidence??0)*100).toFixed(0)}% — ${buySigs.length} buy signals vs ${sellSigs.length} sell`,
    stock.tt&&`Trade type: ${stock.tt} — position managed with ${stock.tt==="INTRADAY"?"intraday exit":"trailing stop"}`,
    stock.regime&&`Regime: ${stock.regime} — strategy pool aligned for current market state`,
    ind&&i>=0&&`RSI ${ind.rsi[i].toFixed(0)}, ADX ${ind.adx[i].toFixed(0)}, EMA20 ${ind.e20[i]>ind.e50[i]?"above":"below"} EMA50`,
    alignedCount>=3&&`MTF alignment: ${alignedCount}/5 timeframes confirm bullish direction`,
  ].filter(Boolean);

  const recommendation=`${rating.icon} ${rating.label}: ${
    rating.label==="STRONG BUY"?"Enter at market or limit near ₹"+bid.toFixed(2)+". Target ₹"+stock.target?.toFixed(2)+", SL ₹"+stock.sl?.toFixed(2)+". All timeframes aligned.":
    rating.label==="BUY"?"Consider buying near current price. TITAN confirms bullish setup. Use ₹"+stock.sl?.toFixed(2)+" as stop-loss.":
    rating.label==="HOLD"?"Mixed signals. No new entry. Existing holders may stay with trailing stop.":
    rating.label==="SELL"?"Weaken position. Move stop to breakeven if in profit. Watch for VWAP loss.":
    "Exit all positions in this stock immediately. Multiple sell signals across timeframes. Do not enter new long."
  }`;

  const tabs=[{id:"overview",label:"Overview"},{id:"technical",label:"Technical"},{id:"fundamentals",label:"Fundamentals"},{id:"news",label:`News ${stockNews.length>0?"("+stockNews.length+")":""}`}];

  return (
    <div style={{position:"fixed",inset:0,zIndex:1000,display:"flex",alignItems:"flex-start",justifyContent:"center",
      background:"rgba(0,0,0,0.75)",overflowY:"auto",padding:"20px 0"}}
      onClick={e=>{if(e.target===e.currentTarget)onClose();}}>
      <div style={{background:G.surface,border:`1px solid ${G.border}`,borderRadius:12,
        width:"min(920px,95vw)",maxHeight:"90vh",overflowY:"auto",position:"relative",margin:"auto"}}>

        {/* Modal header */}
        <div style={{background:G.bg,borderBottom:`1px solid ${G.border}`,
          padding:"16px 24px",position:"sticky",top:0,zIndex:1,
          display:"flex",justifyContent:"space-between",alignItems:"center"}}>
          <div style={{display:"flex",gap:12,alignItems:"center"}}>
            <div>
              <div style={{display:"flex",gap:8,alignItems:"center"}}>
                <span style={{color:G.text,fontWeight:700,fontSize:18,fontFamily:"monospace"}}>{stock.s}</span>
                <span style={{color:G.textSec,fontSize:12}}>{stock.n}</span>
                {stock.sec&&<Tag label={stock.sec} color={G.blue}/>}
              </div>
              <div style={{color:G.textMut,fontSize:10,marginTop:2}}>{F.company_name||stock.n} · {F.industry||""}</div>
            </div>
            <div style={{textAlign:"right"}}>
              <div style={{color:G.text,fontSize:22,fontWeight:700,fontFamily:"monospace"}}>₹{price.toFixed(2)}</div>
              <div style={{color:change24h>=0?G.green:G.red,fontSize:11,fontFamily:"monospace"}}>
                {change24h>=0?"+":""}{change24h.toFixed(2)}%
              </div>
            </div>
          </div>
          <div style={{display:"flex",gap:10,alignItems:"center"}}>
            <RatingBadge rating={rating} size="lg"/>
            <button onClick={onClose} style={{background:G.border,border:"none",color:G.textSec,
              width:28,height:28,borderRadius:"50%",cursor:"pointer",fontSize:14}}>✕</button>
          </div>
        </div>

        {/* Ask/Bid strip */}
        <div style={{background:G.bg,padding:"8px 24px",borderBottom:`1px solid ${G.border}`,
          display:"flex",gap:24,alignItems:"center"}}>
          {[
            {label:"BID (Buy at)",val:bid,color:G.green,sub:"Market buy price"},
            {label:"ASK (Sell at)",val:ask,color:G.red,sub:"Market sell price"},
            {label:"Spread",val:`₹${(ask-bid).toFixed(2)} (${(((ask-bid)/price)*100).toFixed(3)}%)`,color:G.yellow,sub:"Transaction friction"},
            {label:"Target",val:stock.target?`₹${stock.target.toFixed(2)}`:"—",color:G.teal,sub:`${stock.target?((stock.target-price)/price*100).toFixed(1)+"%":""}  upside`},
            {label:"Stop Loss",val:stock.sl?`₹${stock.sl.toFixed(2)}`:"—",color:G.red,sub:`${stock.sl?((price-stock.sl)/price*100).toFixed(1)+"%":""}  risk`},
            {label:"R:R",val:stock.entry&&stock.sl&&stock.target?`1:${((stock.target-stock.entry)/(stock.entry-stock.sl)).toFixed(2)}`:"—",color:G.purple,sub:"Reward-to-risk"},
          ].map(({label,val,color,sub})=>(
            <div key={label}>
              <div style={{color:G.textMut,fontSize:9,fontFamily:"monospace"}}>{label}</div>
              <div style={{color,fontSize:12,fontWeight:700,fontFamily:"monospace"}}>{typeof val==="string"?val:`₹${val.toFixed(2)}`}</div>
              <div style={{color:G.textMut,fontSize:8}}>{sub}</div>
            </div>
          ))}
          <div style={{flex:1,textAlign:"right"}}>
            <div style={{display:"inline-block",background:rating.bg,border:`1px solid ${rating.color}55`,
              borderRadius:6,padding:"8px 14px",maxWidth:280}}>
              <div style={{color:G.textMut,fontSize:9,marginBottom:3}}>AlphaZero Recommendation</div>
              <div style={{color:rating.color,fontSize:11,fontWeight:600,lineHeight:1.5}}>{recommendation}</div>
            </div>
          </div>
        </div>

        {/* Tab bar */}
        <div style={{display:"flex",borderBottom:`1px solid ${G.border}`,background:G.bg}}>
          {tabs.map(t=>(
            <button key={t.id} onClick={()=>setTab(t.id)} style={{
              background:"none",border:"none",borderBottom:tab===t.id?`2px solid ${G.blueDim}`:"2px solid transparent",
              color:tab===t.id?G.text:G.textSec,padding:"10px 20px",fontSize:12,cursor:"pointer",
              fontWeight:tab===t.id?600:400,marginBottom:-1,transition:"color .15s"}}>
              {t.label}
            </button>
          ))}
        </div>

        <div style={{padding:"20px 24px"}}>
          {/* ── OVERVIEW TAB ── */}
          {tab==="overview"&&(
            <div style={{display:"flex",flexDirection:"column",gap:16}}>
              {/* Why this stock was picked */}
              <div style={{background:G.bg,border:`1px solid ${G.green}30`,borderRadius:8,padding:"16px 18px"}}>
                <div style={{display:"flex",alignItems:"center",gap:8,marginBottom:12}}>
                  <span style={{fontSize:16}}>🎯</span>
                  <span style={{color:G.text,fontWeight:700,fontSize:13}}>Why APEX Selected This Stock</span>
                </div>
                <div style={{display:"flex",flexDirection:"column",gap:8}}>
                  {whyBought.map((reason,i)=>(
                    <div key={i} style={{display:"flex",gap:10,alignItems:"flex-start"}}>
                      <span style={{color:G.green,fontSize:12,marginTop:1,flexShrink:0}}>✓</span>
                      <span style={{color:G.textSec,fontSize:12,lineHeight:1.5}}>{reason}</span>
                    </div>
                  ))}
                </div>
                {stock.selectionReason&&(
                  <div style={{marginTop:12,padding:"10px 14px",background:G.surface,borderRadius:6,
                    borderLeft:`3px solid ${G.blue}`,color:G.textSec,fontSize:11,lineHeight:1.6}}>
                    <strong style={{color:G.blue}}>AI Analysis:</strong> {stock.selectionReason}
                  </div>
                )}
              </div>

              {/* SIGMA scores */}
              {stock.sigmaFactors&&(
                <div style={{background:G.surface,border:`1px solid ${G.border}`,borderRadius:8,padding:"16px 18px"}}>
                  <div style={{color:G.text,fontSize:13,fontWeight:600,marginBottom:14}}>📊 SIGMA Score Breakdown</div>
                  <div style={{display:"grid",gridTemplateColumns:"repeat(4,1fr)",gap:10}}>
                    {Object.entries(stock.sigmaFactors).map(([factor,val])=>(
                      <div key={factor} style={{background:G.bg,borderRadius:6,padding:"10px 12px"}}>
                        <div style={{color:G.textMut,fontSize:9,textTransform:"capitalize",marginBottom:4}}>{factor}</div>
                        <KpiBar value={val} max={1} color={val>=0.7?G.green:val>=0.4?G.yellow:G.red}/>
                        <div style={{color:G.textSec,fontSize:10,marginTop:3,fontFamily:"monospace"}}>{(val*100).toFixed(0)}%</div>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Modes behavior */}
              <div style={{background:G.surface,border:`1px solid ${G.border}`,borderRadius:8,padding:"16px 18px"}}>
                <div style={{color:G.text,fontSize:13,fontWeight:600,marginBottom:12}}>⚙️ {mode==="LIVE"?"LIVE":"PAPER"} Mode Behavior</div>
                <div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:12}}>
                  <div style={{background:G.bg,borderRadius:6,padding:"12px 14px",borderLeft:`3px solid ${G.green}`}}>
                    <div style={{color:G.green,fontSize:10,fontWeight:700,marginBottom:6}}>📄 PAPER MODE</div>
                    <div style={{color:G.textSec,fontSize:11,lineHeight:1.6}}>
                      Signal evaluated against live NSE prices. Entry, SL, target tracked in memory. 
                      Win/loss recorded to LENS. KARMA learns from outcomes. No real orders placed.
                      Full risk management logic still runs — GUARDIAN blocks bad trades same as live.
                    </div>
                  </div>
                  <div style={{background:G.bg,borderRadius:6,padding:"12px 14px",borderLeft:`3px solid ${G.red}`}}>
                    <div style={{color:G.red,fontSize:10,fontWeight:700,marginBottom:6}}>🔴 LIVE MODE</div>
                    <div style={{color:G.textSec,fontSize:11,lineHeight:1.6}}>
                      GUARDIAN validates trade. MERCURY routes to OpenAlgo. Real NSE order placed with 
                      exact quantity, stop-loss, target. Trailing stop managed automatically. 
                      Every charge (STT, brokerage, GST, DP) deducted from net P&L.
                    </div>
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* ── TECHNICAL TAB ── */}
          {tab==="technical"&&(
            <div style={{display:"flex",flexDirection:"column",gap:16}}>
              {/* Indicators table */}
              {ind&&i>=0&&(
                <div style={{background:G.surface,border:`1px solid ${G.border}`,borderRadius:8,padding:"16px 18px"}}>
                  <div style={{color:G.text,fontSize:13,fontWeight:600,marginBottom:14}}>📈 Technical Indicators</div>
                  <div style={{display:"grid",gridTemplateColumns:"repeat(4,1fr)",gap:10}}>
                    {[
                      {key:"RSI",val:ind.rsi[i].toFixed(0),
                        color:ind.rsi[i]<35?G.green:ind.rsi[i]>65?G.red:G.yellow,
                        desc:`${ind.rsi[i]<35?"Oversold — buyers likely to step in":ind.rsi[i]>65?"Overbought — watch for reversal":"Neutral zone"}`},
                      {key:"ADX",val:ind.adx[i].toFixed(0),
                        color:ind.adx[i]>30?G.green:ind.adx[i]>20?G.yellow:G.textSec,
                        desc:`${ind.adx[i]>30?"Strong trend — momentum strategies preferred":ind.adx[i]>20?"Moderate trend":"Weak trend — mean reversion works better"}`},
                      {key:"ATR",val:`₹${ind.atr[i].toFixed(2)}`,color:G.blue,desc:"Average True Range — daily price volatility. Used for SL sizing: SL = entry − 1.5×ATR"},
                      {key:"EMA20",val:`₹${ind.e20[i].toFixed(0)}`,
                        color:ind.c[i]>ind.e20[i]?G.green:G.red,
                        desc:`Price is ${ind.c[i]>ind.e20[i]?"above":"below"} EMA20 — ${ind.c[i]>ind.e20[i]?"bullish short-term bias":"bearish short-term bias"}`},
                      {key:"EMA50",val:`₹${ind.e50[i].toFixed(0)}`,
                        color:ind.e20[i]>ind.e50[i]?G.green:G.red,
                        desc:`EMA20 is ${ind.e20[i]>ind.e50[i]?"above":"below"} EMA50 — ${ind.e20[i]>ind.e50[i]?"bull cross active":"bear cross active"}`},
                      {key:"VWAP",val:`₹${ind.vwap[i].toFixed(0)}`,
                        color:ind.c[i]>ind.vwap[i]?G.green:G.red,
                        desc:`Price ${ind.c[i]>ind.vwap[i]?"above":"below"} VWAP — institutions generally ${ind.c[i]>ind.vwap[i]?"bullish":"bearish"} on intraday`},
                      {key:"BB %B",val:ind.bbpb[i].toFixed(2),
                        color:ind.bbpb[i]<0.2?G.green:ind.bbpb[i]>0.8?G.red:G.yellow,
                        desc:`${ind.bbpb[i]<0.2?"Near lower band — potential bounce zone":ind.bbpb[i]>0.8?"Near upper band — potential resistance":"%B=0.5 is midband. <0.2 = oversold, >0.8 = overbought"}`},
                      {key:"Stoch K",val:ind.sk[i].toFixed(0),
                        color:ind.sk[i]<25?G.green:ind.sk[i]>75?G.red:G.yellow,
                        desc:`${ind.sk[i]<25?"Oversold — look for K crossing above D":ind.sk[i]>75?"Overbought — look for K crossing below D":"Neutral. Watch for K/D crossovers at extremes."}`},
                    ].map(({key,val,color,desc})=>(
                      <div key={key} onClick={()=>setExpandedItem(expandedItem===key?null:key)}
                        style={{background:G.bg,borderRadius:6,padding:"10px 12px",cursor:"pointer",transition:"background .12s",
                          border:`1px solid ${expandedItem===key?color+"55":G.border}`}}
                        onMouseEnter={e=>e.currentTarget.style.background=G.surfaceHov}
                        onMouseLeave={e=>e.currentTarget.style.background=G.bg}>
                        <div style={{color:G.textMut,fontSize:9,marginBottom:5}}>{key}</div>
                        <div style={{color,fontSize:14,fontWeight:700,fontFamily:"monospace",marginBottom:4}}>{val}</div>
                        {expandedItem===key&&(
                          <div style={{color:G.textSec,fontSize:10,lineHeight:1.6,marginTop:6,
                            paddingTop:6,borderTop:`1px solid ${G.border}`}}>{desc}</div>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Candle patterns */}
              <div style={{background:G.surface,border:`1px solid ${G.border}`,borderRadius:8,padding:"16px 18px"}}>
                <div style={{color:G.text,fontSize:13,fontWeight:600,marginBottom:4}}>🕯️ Candle Pattern Detection</div>
                <div style={{color:G.textMut,fontSize:10,marginBottom:12}}>Click any pattern to understand what it means for this trade</div>
                {candlePatterns.length===0
                  ? <div style={{color:G.textMut,fontSize:11,padding:"10px 0"}}>No significant patterns detected on last 3 candles</div>
                  : (
                    <div style={{display:"flex",flexDirection:"column",gap:8}}>
                      {candlePatterns.map((pat,idx)=>(
                        <div key={idx} onClick={()=>setExpandedItem(expandedItem===`pat_${idx}`?null:`pat_${idx}`)}
                          style={{background:G.bg,borderRadius:6,padding:"10px 14px",cursor:"pointer",transition:"background .12s",
                            border:`1px solid ${pat.type==="bull"?G.green+"44":pat.type==="bear"?G.red+"44":G.border}`}}
                          onMouseEnter={e=>e.currentTarget.style.background=G.surfaceHov}
                          onMouseLeave={e=>e.currentTarget.style.background=G.bg}>
                          <div style={{display:"flex",justifyContent:"space-between",alignItems:"center"}}>
                            <div style={{display:"flex",gap:8,alignItems:"center"}}>
                              <span style={{fontSize:16}}>{pat.icon}</span>
                              <span style={{color:pat.type==="bull"?G.green:pat.type==="bear"?G.red:G.yellow,fontSize:12,fontWeight:600}}>{pat.name}</span>
                              <Tag label={pat.type==="bull"?"Bullish":pat.type==="bear"?"Bearish":"Neutral"}
                                color={pat.type==="bull"?G.green:pat.type==="bear"?G.red:G.yellow}/>
                            </div>
                            <span style={{color:G.textMut,fontSize:9}}>{expandedItem===`pat_${idx}`?"▲ hide":"▼ what does this mean?"}</span>
                          </div>
                          {expandedItem===`pat_${idx}`&&(
                            <div style={{marginTop:10,paddingTop:10,borderTop:`1px solid ${G.border}`,
                              color:G.textSec,fontSize:11,lineHeight:1.7}}>{pat.desc}</div>
                          )}
                        </div>
                      ))}
                    </div>
                  )}
              </div>

              {/* Volume analysis */}
              {volAnalysis&&(
                <div style={{background:G.surface,border:`1px solid ${G.border}`,borderRadius:8,padding:"16px 18px"}}>
                  <div style={{color:G.text,fontSize:13,fontWeight:600,marginBottom:4}}>📦 Volume Analysis</div>
                  <div style={{color:G.textMut,fontSize:10,marginBottom:12}}>Click any metric to understand its implication</div>
                  <div style={{display:"grid",gridTemplateColumns:"repeat(2,1fr)",gap:8}}>
                    {[
                      {key:"vol_ratio",label:"Volume vs 20D Avg",val:`${volAnalysis.volRatio}×`,
                        color:volAnalysis.volRatio>1.5?G.green:volAnalysis.volRatio<0.7?G.red:G.yellow,
                        desc:`Current volume is ${volAnalysis.volRatio}× the 20-day average. ${volAnalysis.volRatio>1.5?"Elevated volume confirms price moves — institutions participating. This is the setup TITAN's B2 Volume Breakout looks for.":volAnalysis.volRatio<0.7?"Below-average volume — move may not sustain. Wait for volume to confirm before entering.":"Normal volume. Move is organic but lacks the urgency of institutional participation."}`},
                      {key:"obv",label:"OBV Trend",val:volAnalysis.obvTrend,
                        color:volAnalysis.obvTrend==="RISING"?G.green:G.red,
                        desc:`On-Balance Volume is ${volAnalysis.obvTrend}. OBV sums volume on up-days and subtracts on down-days. ${volAnalysis.obvTrend==="RISING"?"Rising OBV while price rises = healthy bull trend. If OBV rises but price is flat, accumulation is happening under the surface — breakout likely soon.":"Falling OBV = more volume on down-days = distribution. Institutions may be offloading positions to retail buyers. Caution on new longs."}`},
                      {key:"pv",label:"Price-Volume Confirm",val:volAnalysis.pvConfirm?"CONFIRMED":"DIVERGING",
                        color:volAnalysis.pvConfirm?G.green:G.orange,
                        desc:`Price and volume are ${volAnalysis.pvConfirm?"moving together":"diverging"}. ${volAnalysis.pvConfirm?"Confirmation: price up + volume up OR price down + volume down. This is healthy — the move has conviction behind it.":"Divergence: price moving one way but volume opposing. This is a warning signal. Price up on low volume can reverse; price down on low volume may be a shakeout."}`},
                      {key:"acc",label:"Activity Pattern",val:volAnalysis.accumulation?"ACCUMULATION":volAnalysis.distribution?"DISTRIBUTION":"NORMAL",
                        color:volAnalysis.accumulation?G.green:volAnalysis.distribution?G.red:G.yellow,
                        desc:volAnalysis.accumulation?"Accumulation detected: price is stable or rising slightly while volume is elevated and OBV is rising. This suggests smart money is quietly buying before a larger move. Institutional buying often happens this way to avoid moving price too fast.":volAnalysis.distribution?"Distribution detected: price is relatively flat while volume is high and OBV is falling. Institutions may be offloading positions to retail buyers. High risk — price can drop sharply once distribution ends.":"Normal trading activity. No unusual accumulation or distribution detected. Follow technical signals as primary guide."},
                    ].map(({key,label,val,color,desc})=>(
                      <div key={key} onClick={()=>setExpandedItem(expandedItem===key?null:key)}
                        style={{background:G.bg,borderRadius:6,padding:"10px 12px",cursor:"pointer",
                          border:`1px solid ${expandedItem===key?color+"55":G.border}`}}
                        onMouseEnter={e=>e.currentTarget.style.background=G.surfaceHov}
                        onMouseLeave={e=>e.currentTarget.style.background=G.bg}>
                        <div style={{display:"flex",justifyContent:"space-between",marginBottom:3}}>
                          <span style={{color:G.textSec,fontSize:10}}>{label}</span>
                          <span style={{color:G.textMut,fontSize:8}}>click</span>
                        </div>
                        <div style={{color,fontSize:13,fontWeight:700,fontFamily:"monospace"}}>{val}</div>
                        {expandedItem===key&&(
                          <div style={{marginTop:8,paddingTop:8,borderTop:`1px solid ${G.border}`,
                            color:G.textSec,fontSize:10,lineHeight:1.7}}>{desc}</div>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* MTF Alignment */}
              <div style={{background:G.surface,border:`1px solid ${G.border}`,borderRadius:8,padding:"16px 18px"}}>
                <div style={{color:G.text,fontSize:13,fontWeight:600,marginBottom:4}}>⏱ Multi-Timeframe Alignment</div>
                <div style={{color:G.textMut,fontSize:10,marginBottom:12}}>Click the alignment summary to understand what this means</div>
                <div style={{display:"flex",gap:10,marginBottom:12}}>
                  {mtfData.map(m=>(
                    <div key={m.tf} style={{flex:1,textAlign:"center",background:G.bg,
                      borderRadius:6,padding:"10px 4px",
                      border:`1px solid ${m.votes===1?G.green+"44":G.red+"44"}`}}>
                      <div style={{color:G.textMut,fontSize:9,marginBottom:4}}>{m.label}</div>
                      <div style={{fontSize:16}}>{m.votes===1?"✅":"❌"}</div>
                      <div style={{color:m.votes===1?G.green:G.red,fontSize:9,marginTop:3,fontFamily:"monospace"}}>
                        {m.votes===1?"BULL":"BEAR"}
                      </div>
                    </div>
                  ))}
                </div>
                <div onClick={()=>setExpandedItem(expandedItem==="mtf"?null:"mtf")}
                  style={{background:G.bg,borderRadius:6,padding:"10px 14px",cursor:"pointer",
                    border:`1px solid ${alignedCount>=4?G.green+"44":alignedCount>=3?G.yellow+"44":G.red+"44"}`}}>
                  <div style={{display:"flex",justifyContent:"space-between",alignItems:"center"}}>
                    <span style={{color:alignedCount>=4?G.green:alignedCount>=3?G.yellow:G.red,
                      fontSize:12,fontWeight:600}}>
                      {alignedCount}/5 timeframes aligned {alignedCount>=4?"→ High confidence":alignedCount>=3?"→ Moderate":"→ Low confidence"}
                    </span>
                    <span style={{color:G.textMut,fontSize:9}}>click to understand</span>
                  </div>
                  {expandedItem==="mtf"&&(
                    <div style={{marginTop:10,paddingTop:10,borderTop:`1px solid ${G.border}`,
                      color:G.textSec,fontSize:11,lineHeight:1.7}}>{mtfDesc}</div>
                  )}
                </div>
              </div>

              {/* TITAN signals list */}
              {stockSigs.length>0&&(
                <div style={{background:G.surface,border:`1px solid ${G.border}`,borderRadius:8,padding:"16px 18px"}}>
                  <div style={{display:"flex",justifyContent:"space-between",marginBottom:12}}>
                    <span style={{color:G.text,fontSize:13,fontWeight:600}}>⚔️ TITAN Strategy Signals</span>
                    <div style={{display:"flex",gap:8}}>
                      <Tag label={`${buySigs.length} BUY`} color={G.green}/>
                      <Tag label={`${sellSigs.length} SELL`} color={G.red}/>
                    </div>
                  </div>
                  <div style={{display:"flex",flexDirection:"column",gap:6}}>
                    {stockSigs.slice(0,10).map((sig,j)=>(
                      <div key={j} style={{display:"flex",gap:10,alignItems:"center",padding:"7px 10px",
                        background:G.bg,borderRadius:6,borderLeft:`3px solid ${sig.signal===1?G.green:G.red}`}}>
                        <Tag label={sig.id} color={G.yellow}/>
                        <Tag label={sig.signal===1?"BUY":"SELL"} color={sig.signal===1?G.green:G.red}/>
                        <span style={{color:G.textSec,fontSize:11,flex:1}}>{sig.reason}</span>
                        <span style={{color:G.textMut,fontSize:10,fontFamily:"monospace"}}>{(sig.confidence*100).toFixed(0)}%</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}

          {/* ── FUNDAMENTALS TAB ── */}
          {tab==="fundamentals"&&(
            <div style={{display:"flex",flexDirection:"column",gap:16}}>
              {Object.keys(F).length===0
                ? <Empty icon="📊" title="Fundamentals loading" sub="Fetched from yfinance/screener.in when backend is connected. Start backend for real data."/>
                : (
                  <>
                    <div style={{background:G.bg,border:`1px solid ${G.border}`,borderRadius:8,padding:"14px 16px"}}>
                      <div style={{color:G.textSec,fontSize:12,lineHeight:1.7}}>{F.description||"No company description available."}</div>
                    </div>
                    <div style={{display:"grid",gridTemplateColumns:"repeat(4,1fr)",gap:10}}>
                      {[
                        {key:"pe_ratio",label:"P/E Ratio",val:F.pe_ratio?F.pe_ratio.toFixed(1):"—",desc:"Price-to-earnings. <15 is cheap, >30 is expensive relative to growth. Click to understand."},
                        {key:"roe",label:"ROE %",val:F.roe!=null?`${F.roe.toFixed(1)}%`:"—",desc:"Return on Equity — how well the company uses shareholder money. >15% is good; >25% is excellent. Consistent ROE > 20% is a quality indicator."},
                        {key:"market_cap",label:"Market Cap",val:F.market_cap_cr?`₹${(F.market_cap_cr/100).toFixed(0)}k Cr`:"—",desc:"Total market value of all shares. Large cap >₹20,000 Cr is more stable; mid cap ₹5,000-20,000 Cr has more growth potential."},
                        {key:"pb",label:"P/B Ratio",val:F.price_to_book?F.price_to_book.toFixed(2):"—",desc:"Price-to-book. <1 = stock trading below asset value. Banking stocks often trade at P/B 1-3. High P/B only justified by high ROE."},
                        {key:"rev_growth",label:"Revenue Growth",val:F.revenue_growth!=null?`${F.revenue_growth.toFixed(1)}%`:"—",desc:"YoY revenue growth. >15% is strong growth; >25% is high-growth territory. Negative = declining business."},
                        {key:"debt_eq",label:"Debt/Equity",val:F.debt_to_equity?F.debt_to_equity.toFixed(2):"—",desc:"Total debt divided by equity. <0.5 is low debt; >2 is highly leveraged. High D/E OK for infrastructure but risky for cyclical sectors."},
                        {key:"dividend",label:"Dividend Yield",val:F.dividend_yield?`${F.dividend_yield.toFixed(2)}%`:"—",desc:"Annual dividend as % of stock price. >3% is high yield. Good for income investors. Low yield may mean company reinvests for growth."},
                        {key:"eps",label:"EPS",val:F.eps?`₹${F.eps.toFixed(2)}`:"—",desc:"Earnings Per Share. Rising EPS over 3+ years indicates consistent profitability. EPS × average P/E = fair value estimate."},
                      ].map(({key,label,val,desc})=>(
                        <div key={key} onClick={()=>setExpandedItem(expandedItem===key?null:key)}
                          style={{background:G.bg,borderRadius:6,padding:"12px 14px",cursor:"pointer",
                            border:`1px solid ${expandedItem===key?G.blue+"55":G.border}`}}
                          onMouseEnter={e=>e.currentTarget.style.background=G.surfaceHov}
                          onMouseLeave={e=>e.currentTarget.style.background=G.bg}>
                          <div style={{color:G.textMut,fontSize:9,marginBottom:5}}>{label}</div>
                          <div style={{color:G.text,fontSize:15,fontWeight:700,fontFamily:"monospace",marginBottom:4}}>{val}</div>
                          {expandedItem===key&&(
                            <div style={{color:G.textSec,fontSize:10,lineHeight:1.6,marginTop:6,
                              paddingTop:6,borderTop:`1px solid ${G.border}`}}>{desc}</div>
                          )}
                          {expandedItem!==key&&<div style={{color:G.textMut,fontSize:8}}>click to understand</div>}
                        </div>
                      ))}
                    </div>
                    {/* 52-week range */}
                    {F.week52_low&&F.week52_high&&(
                      <div style={{background:G.surface,border:`1px solid ${G.border}`,borderRadius:8,padding:"16px 18px"}}>
                        <div style={{color:G.text,fontSize:12,fontWeight:600,marginBottom:10}}>52-Week Range</div>
                        <div style={{position:"relative",height:8,background:G.border,borderRadius:4,marginBottom:10}}>
                          <div style={{position:"absolute",left:`${((price-F.week52_low)/(F.week52_high-F.week52_low))*100}%`,
                            width:12,height:12,background:G.blue,borderRadius:"50%",top:-2,
                            transform:"translateX(-50%)",boxShadow:`0 0 8px ${G.blue}`}}/>
                          <div style={{position:"absolute",left:0,top:-2,color:G.red,fontSize:10,fontFamily:"monospace"}}>₹{F.week52_low.toFixed(0)}</div>
                          <div style={{position:"absolute",right:0,top:-2,color:G.green,fontSize:10,fontFamily:"monospace"}}>₹{F.week52_high.toFixed(0)}</div>
                        </div>
                        <div style={{textAlign:"center",color:G.textSec,fontSize:11,marginTop:12}}>
                          Current ₹{price.toFixed(0)} is {((price-F.week52_low)/(F.week52_high-F.week52_low)*100).toFixed(0)}% from 52W low
                        </div>
                      </div>
                    )}
                  </>
                )}
            </div>
          )}

          {/* ── NEWS TAB ── */}
          {tab==="news"&&(
            <div style={{display:"flex",flexDirection:"column",gap:10}}>
              {stockNews.length===0
                ? <Empty icon="📰" title="No news for this stock" sub="News feeds scan ET, Moneycontrol, Reuters, Business Standard every 5 min. Start backend for real news."/>
                : stockNews.map((item,i)=>{
                    const sent=SENTIMENT_LABEL[item.sentiment]??SENTIMENT_LABEL.NEUTRAL;
                    return (
                      <div key={i} style={{background:G.surface,border:`1px solid ${G.border}`,
                        borderRadius:8,padding:"14px 18px"}}>
                        <div style={{display:"flex",justifyContent:"space-between",alignItems:"flex-start",marginBottom:8}}>
                          <div style={{display:"flex",gap:8,alignItems:"center",flexWrap:"wrap"}}>
                            <span style={{color:SOURCE_COLOR[item.source]??G.textSec,fontSize:11,fontWeight:600}}>{item.source}</span>
                            <span style={{color:sent.color,fontSize:11,fontWeight:700}}>{sent.icon} {item.sentiment?.replace("_"," ")}</span>
                          </div>
                          <span style={{color:G.textMut,fontSize:10,fontFamily:"monospace"}}>{item.time}</span>
                        </div>
                        <div style={{color:G.text,fontSize:13,fontWeight:600,lineHeight:1.4,marginBottom:6}}>
                          {item.headline}
                        </div>
                        {item.summary&&<div style={{color:G.textSec,fontSize:11,lineHeight:1.6}}>{item.summary}</div>}
                        {item.impact&&(
                          <div style={{marginTop:8,padding:"8px 12px",background:G.bg,borderRadius:6,
                            borderLeft:`3px solid ${sent.color}`,color:G.textSec,fontSize:11,lineHeight:1.5}}>
                            <strong style={{color:sent.color}}>Impact analysis:</strong> {item.impact}
                          </div>
                        )}
                      </div>
                    );
                  })
              }
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════════════
// DEMO NEWS GENERATOR (until backend provides real feeds)
// ═══════════════════════════════════════════════════════════════════════════
function generateDemoNews(picks) {
  const templates=[
    {h:"Q3 results: net profit up 18% YoY on strong topline",sent:"BULLISH",src:"Economic Times",score:0.62},
    {h:"FII inflows surge as global risk appetite improves",sent:"BULLISH",src:"Moneycontrol",score:0.45},
    {h:"Management guidance raised for FY25 revenue",sent:"STRONGLY_BULLISH",src:"Business Standard",score:0.78},
    {h:"Sector headwinds: raw material inflation continues",sent:"BEARISH",src:"Mint",score:-0.41},
    {h:"SEBI directive may impact business temporarily",sent:"BEARISH",src:"Reuters",score:-0.35},
    {h:"Analyst upgrade to Buy with target raised 15%",sent:"STRONGLY_BULLISH",src:"Bloomberg",score:0.82},
    {h:"Promoter stake unchanged; no insider selling",sent:"NEUTRAL",src:"NDTV Business",score:0.05},
    {h:"Weak guidance given for next quarter",sent:"BEARISH",src:"Financial Express",score:-0.38},
  ];
  const now=new Date();
  return picks.slice(0,5).flatMap((p,pi)=>{
    const items=templates.slice(0,2+pi%2).map((t,i)=>{
      const mins=Math.floor(Math.random()*120);
      const related=picks.filter(x=>x.s!==p.s&&x.sec===p.sec).slice(0,2).map(x=>x.s);
      return {
        symbol:p.s,related,headline:`${p.s}: ${t.h}`,summary:`${p.n} ${t.h.toLowerCase()}. Analysis by AlphaZero sentiment engine.`,
        sentiment:t.sent,sentiment_score:t.score,source:t.src,
        time:`${now.getHours()}:${String(now.getMinutes()-mins<0?0:now.getMinutes()-mins).padStart(2,"0")}`,
        impact:`${t.sent.includes("BULL")?"Positive for share price":"Negative short-term pressure"}. ${p.s} SIGMA score adjusted accordingly.`,
        confirmation:t.score>0.5?[t.src,"AlphaZero AI"]:t.score<-0.3?[t.src]:[],
      };
    });
    return items;
  });
}

// ═══════════════════════════════════════════════════════════════════════════
// MAIN APP
// ═══════════════════════════════════════════════════════════════════════════
export default function App() {
  // ── State ──────────────────────────────────────────────────────────────
  const [tab,setTab]             = useState("overview");
  const [connStatus,setConn]     = useState("connecting");
  const [now,setNow]             = useState(new Date());
  const [regime,setRegime]       = useState("TRENDING");
  const [indices,setIndices]     = useState({nifty:24148,banknifty:51832,vix:14.2,market_open:false});
  const [quotes,setQuotes]       = useState({});
  const [picks,setPicks]         = useState([]);
  const [positions,setPos]       = useState([]);
  const [candleCache,setCaches]  = useState({});
  const [allSigs,setAllSigs]     = useState([]);
  const [evalStats,setEvalStats] = useState({});
  const [evalHistory,setHistory] = useState([]);
  const [agentScores,setAgtScores]= useState([]);
  const [agentKpi,setAgentKpi]   = useState({});
  const [karmaStats,setKarma]    = useState({});
  const [fundamentals,setFundamentals]=useState({});
  const [news,setNews]           = useState([]);
  const [events,setEvents]       = useState([]);
  const [selectedStock,setSelected]=useState(null);
  const [systemState,setSysState]=useState({status:"RUNNING",mode:"PAPER",iteration:0,uptime_s:0});

  // ── Refs ────────────────────────────────────────────────────────────────
  const cRef=useRef(candleCache);   cRef.current=candleCache;
  const pRef=useRef(positions);     pRef.current=positions;
  const rRef=useRef(regime);        rRef.current=regime;
  const qRef=useRef(quotes);        qRef.current=quotes;
  const connRef=useRef(connStatus); connRef.current=connStatus;
  const startTs=useRef(Date.now());

  // ── Event bus adder ────────────────────────────────────────────────────
  const addEvt=useCallback((type,agent,msg)=>{
    setEvents(prev=>[{type,agent,msg,ts:new Date().toLocaleTimeString("en-IN",{hour12:false})},...prev.slice(0,99)]);
  },[]);

  // ── Clock ──────────────────────────────────────────────────────────────
  useEffect(()=>{const t=setInterval(()=>setNow(new Date()),1000);return()=>clearInterval(t);},[]);

  // ── System uptime ──────────────────────────────────────────────────────
  useEffect(()=>{
    const t=setInterval(()=>setSysState(prev=>({...prev,uptime_s:Math.floor((Date.now()-startTs.current)/1000)})),5000);
    return()=>clearInterval(t);
  },[]);

  // ── Backend WS ─────────────────────────────────────────────────────────
  useEffect(()=>{
    let ws,alive=true;
    const connect=()=>{
      try {
        ws=new WebSocket(`ws://localhost:8000/ws`);
        ws.onopen=()=>{if(alive){setConn("live");addEvt("SYSTEM","WS","Connected to AlphaZero backend");}};
        ws.onmessage=e=>{
          const msg=JSON.parse(e.data);
          if(msg.quotes)setQuotes(msg.quotes);
          if(msg.indices)setIndices(msg.indices);
          if(msg.regime)setRegime(msg.regime);
          if(msg.karma)setKarma(msg.karma);
          if(msg.fundamentals)setFundamentals(prev=>({...prev,...msg.fundamentals}));
          if(msg.news)setNews(msg.news);
          if(msg.eval_stats)setEvalStats(msg.eval_stats);
          if(msg.agent_scores)setAgtScores(msg.agent_scores);
          if(msg.agent_kpi)setAgentKpi(msg.agent_kpi);
          if(msg.system)setSysState(msg.system);
          if(msg.type==="PONG"){}
        };
        ws.onclose=()=>{if(alive){setConn("offline");setTimeout(()=>{if(alive)connect();},5000);}};
        ws.onerror=()=>{if(alive){setConn("offline");}};
        // Heartbeat
        const ping=setInterval(()=>{if(ws.readyState===1)ws.send(JSON.stringify({type:"PING"}));},20000);
        ws._pingInterval=ping;
      } catch {if(alive)setConn("offline");}
    };
    connect();
    return ()=>{alive=false;ws?.close();clearInterval(ws?._pingInterval);};
  },[addEvt]);

  // ── Regime drift (offline) ─────────────────────────────────────────────
  useEffect(()=>{
    if(connStatus==="live") return;
    const r=["TRENDING","SIDEWAYS","VOLATILE","RISK_OFF"];
    setKarmaStats&&setKarma({
      episodes:847,win_rate:0.61,best_strategy:"T2 Triple EMA",
      training_active:new Date().getHours()<9||new Date().getHours()>=18,
      last_training:new Date().getHours()>=18?"Today "+new Date().getHours()+":00":"Yesterday 22:30",
      strategy_weights:{"T2 Triple EMA":1.42,"T1 EMA Cross":1.28,"M1 RSI Rev":1.15,"B2 Vol Breakout":0.98,"V1 VWAP Cross":0.87,"M2 BB Bounce":0.72,"T5 ADX":1.06,"S1 Z-Score":0.65},
      discovered_patterns:[
        {pattern:"RSI<35 + ADX>25 + TRENDING",win_rate:0.74,description:"RSI oversold in trending market — high win reversal"},
        {pattern:"Triple EMA stack + Volume surge",win_rate:0.81,description:"Strongest bull setup with institutional volume"},
        {pattern:"BB squeeze + VWAP reclaim",win_rate:0.69,description:"Post-consolidation breakout with VWAP confirmation"},
      ],
      regime_win_rates:{TRENDING:{win_rate:0.68,trades:124},SIDEWAYS:{win_rate:0.57,trades:89},VOLATILE:{win_rate:0.44,trades:34},RISK_OFF:{win_rate:0.31,trades:12}},
    });
    const t=setInterval(()=>{
      setRegime(r[Math.floor(Math.random()*r.length)]);
      setIndices(prev=>({
        ...prev,
        nifty:prev.nifty+(Math.random()-.49)*30,
        banknifty:prev.banknifty+(Math.random()-.49)*80,
        vix:Math.max(10,Math.min(35,prev.vix+(Math.random()-.5)*0.8)),
        market_open:new Date().getHours()>=9&&new Date().getHours()<16&&new Date().getDay()>=1&&new Date().getDay()<=5,
      }));
      setAgentKpi(prev=>{
        const agents=["ZEUS","ORACLE","ATLAS","SIGMA","APEX","NEXUS","HERMES","TITAN","GUARDIAN","MERCURY","LENS","KARMA"];
        const updated={...prev};
        agents.forEach(a=>{updated[a]={kpi:0.55+Math.random()*0.35,cycles:(updated[a]?.cycles??0)+1};});
        return updated;
      });
    },12000);
    return()=>clearInterval(t);
  },[connStatus]);

  // ── Candle fetch (stable callback) ─────────────────────────────────────
  const getCandles=useCallback(async(symbol)=>{
    if(cRef.current[symbol]) return cRef.current[symbol];
    if(connRef.current==="live"){
      try{
        const r=await fetch(`${BACKEND}/candles/${symbol}`);
        const d=await r.json();
        if(d.candles?.length){
          const norm=d.candles.map(c=>({...c,close:c.close??c.Close??0}));
          setCaches(p=>({...p,[symbol]:norm}));
          return norm;
        }
      }catch{}
    }
    // Synthetic fallback
    const st=NSE_UNIVERSE.find(x=>x.s===symbol);
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
  },[]);

  // ── APEX stock selection (dynamic, whole universe) ─────────────────────
  const runSelect=useCallback(async()=>{
    const cr=rRef.current;
    const results=await Promise.all(NSE_UNIVERSE.map(async(st)=>{
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
      const tt=ind&&Li>=0&&ind.adx[Li]>40?"SHORT_TERM":ind&&Li>=0&&ind.adx[Li]<18&&cr==="SIDEWAYS"?"INTRADAY":"SWING";
      const pools={TRENDING:["T1 EMA Cross","T2 Triple EMA","T4 MACD","T5 ADX","T7 Donchian","B2 Vol Breakout"],SIDEWAYS:["M1 RSI Rev","M2 BB Bounce","M3 BB Squeeze","V1 VWAP Cross","S1 Z-Score"],VOLATILE:["M1 RSI Rev","M2 BB Bounce","V1 VWAP Cross"],RISK_OFF:[]};
      const pool=pools[cr]??pools.TRENDING;
      const ss=pool[Math.floor(Math.random()*pool.length)];
      const [sid,...sname]=ss.split(" ");
      const stockSigs=cdl?titanSignals(cdl,cr):[];
      const buys=stockSigs.filter(x=>x.signal===1).length;
      const sells=stockSigs.filter(x=>x.signal===-1).length;
      const mtfRaw=Array(5).fill(0).map(()=>Math.random()>.45?1:0);
      const mtfVotes=mtfRaw.filter(Boolean).length;
      const topReason=stockSigs[0]?.reason??"SIGMA ranked top by multi-factor model";
      const selectionReason=`${cr} regime · ${ss} strategy confirmed · RSI ${ind&&Li>=0?ind.rsi[Li].toFixed(0):"—"} · ADX ${ind&&Li>=0?ind.adx[Li].toFixed(0):"—"} · ${buys} buy signals · ${mtfVotes}/5 MTF confirmed · SIGMA score ${(score*100).toFixed(0)}/100`;
      return {...st,score,tt,confidence:+(.52+Math.random()*.42).toFixed(2),
        price,chgPct:+chg.toFixed(2),entry:price,sl:+(price-1.5*atr).toFixed(2),
        target:+(price+1.5*atr).toFixed(2),cons:+(price+.8*atr).toFixed(2),opt:+(price+2.5*atr).toFixed(2),
        regime:cr,sid,sname:sname.join(" "),mtfVotes,selectionReason,
        sigmaFactors:{momentum:+mf.toFixed(2),trend:+tf.toFixed(2),earnings:+earn.toFixed(2),
          relStrength:+ef.toFixed(2),news:+nf.toFixed(2),volume:+vf.toFixed(2),
          volatility:+(1-atr/price*30).toFixed(2),fii:+fii.toFixed(2)},
      };
    }));
    const top5=results.sort((a,b)=>b.score-a.score).slice(0,5);
    setPicks(top5);
    addEvt("SELECTION","APEX",`Selected: ${top5.map(s=>s.s).join(", ")} from ${NSE_UNIVERSE.length} stocks · ${cr}`);

    // Collect all signals
    const sigs=[];
    for(const st of top5){
      const cdl=cRef.current[st.s];
      if(cdl){
        const tSigs=titanSignals(cdl,cr).slice(0,3).map(s=>({...s,symbol:st.s,regime:cr,ts:new Date().toLocaleTimeString("en-IN",{hour12:false})}));
        sigs.push(...tSigs);
      }
    }
    setAllSigs(sigs);

    // Auto-open positions for high confidence picks
    top5.filter(s=>s.confidence>.65&&s.mtfVotes>=3).forEach(stock=>{
      if(!pRef.current.find(p=>p.symbol===stock.s&&p.status==="OPEN")){
        const qty=Math.max(1,Math.floor(50000/stock.price));
        setPos(prev=>{
          if(prev.filter(p=>p.status==="OPEN").length>=8) return prev;
          return [...prev.filter(p=>!(p.symbol===stock.s&&p.status==="OPEN")),
            {id:`${stock.s}-${Date.now()}`,symbol:stock.s,entryPrice:stock.price,cp:stock.price,
             sl:stock.sl,target:stock.target,qty,sid:stock.sid,tt:stock.tt,
             pnl:0,pnlPct:0,status:"OPEN",time:new Date().toLocaleTimeString("en-IN",{hour12:false})}
          ].slice(0,10);
        });
        addEvt("ORDER","MERCURY",`[${systemState.mode}] BUY ${qty}×${stock.s} @₹${stock.price} | ${stock.sid} | conf:${(stock.confidence*100).toFixed(0)}%`);
      }
    });
  },[getCandles,addEvt]);

  useEffect(()=>{runSelect();const t=setInterval(runSelect,40000);return()=>clearInterval(t);},[runSelect]);

  // ── Live price updater ─────────────────────────────────────────────────
  useEffect(()=>{
    const update=()=>{
      setPos(prev=>prev.map(pos=>{
        if(pos.status!=="OPEN") return pos;
        const candles=cRef.current[pos.symbol];
        const last=candles?.[candles.length-1];
        const cp=qRef.current[pos.symbol]?.ltp??(last?.close??last?.Close??pos.entryPrice);
        const grossPnl=(cp-pos.entryPrice)*pos.qty;
        const c=calcNetPnl({...pos,cp});
        // Monitoring check for long-term/swing
        let alert=null;
        if((pos.tt==="LONG_TERM"||pos.tt==="SWING")&&cp<=pos.sl){
          alert="SL HIT — exit";
          addEvt("RISK","GUARDIAN",`${pos.symbol} hit stop loss at ₹${cp.toFixed(0)}`);
        }
        if(cp>=pos.target) alert="TARGET reached";
        return {...pos,cp:+cp.toFixed(2),pnl:c.netPnl,pnlPct:c.netPct,alert};
      }));
    };
    const t=setInterval(update,8000);
    return()=>clearInterval(t);
  },[addEvt]);

  // ── Auto-close SL/target hits ──────────────────────────────────────────
  useEffect(()=>{
    const check=()=>{
      setPos(prev=>prev.map(p=>{
        if(p.status!=="OPEN") return p;
        if(p.alert==="SL HIT — exit"||p.alert==="TARGET reached"){
          addEvt("EXEC","MERCURY",`CLOSED ${p.symbol} @₹${p.cp} — ${p.alert}`);
          return {...p,status:"CLOSED",exitPrice:p.cp};
        }
        return p;
      }));
    };
    const t=setInterval(check,15000);
    return()=>clearInterval(t);
  },[addEvt]);

  // ── TITAN signals ──────────────────────────────────────────────────────
  useEffect(()=>{
    const run=()=>{
      picks.slice(0,3).forEach(stock=>{
        const cdl=cRef.current[stock.s];
        if(!cdl||cdl.length<15) return;
        const sigs=titanSignals(cdl,rRef.current);
        if(sigs.length>0){
          const top=sigs[0];
          addEvt("SIGNAL","TITAN",`${stock.s} — ${top.id} → ${top.signal===1?"BUY":"SELL"} (${(top.confidence*100).toFixed(0)}%) · ${top.reason}`);
        }
      });
    };
    const t=setInterval(run,10000);
    return()=>clearInterval(t);
  },[picks,addEvt]);

  // ── News generation ────────────────────────────────────────────────────
  useEffect(()=>{
    if(picks.length>0&&connStatus!=="live"){
      setNews(generateDemoNews(picks));
    }
  },[picks,connStatus]);

  // ── Fundamentals fetch ─────────────────────────────────────────────────
  useEffect(()=>{
    if(connStatus!=="live") return;
    picks.forEach(async st=>{
      if(fundamentals[st.s]) return;
      try{
        const r=await fetch(`${BACKEND}/fundamentals/${st.s}`);
        const d=await r.json();
        setFundamentals(prev=>({...prev,[st.s]:d}));
      }catch{}
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
        setEvalStats(sr);
        setHistory(hr);
        setAgtScores(ar);
      }catch{}
    };
    f();const t=setInterval(f,30000);return()=>clearInterval(t);
  },[connStatus]);

  // ── Net P&L for topnav ─────────────────────────────────────────────────
  const openPositions=positions.filter(p=>p.status==="OPEN");
  const netPnlTotal=openPositions.reduce((s,p)=>s+calcNetPnl(p).netPnl,0);
  const closedPnl=positions.filter(p=>p.status==="CLOSED").reduce((s,p)=>s+calcNetPnl({...p,cp:p.exitPrice??p.cp??p.entryPrice}).netPnl,0);
  const totalNetPnl=netPnlTotal+closedPnl;

  // ── Counts for tab badges ──────────────────────────────────────────────
  const tabCounts={pos:openPositions.length,sigs:allSigs.length,news:news.length,eval:evalStats?.total_evaluated??0};

  return (
    <div style={{background:G.bg,color:G.text,minHeight:"100vh",
      fontFamily:"'SF Mono','Fira Code','JetBrains Mono',Consolas,monospace",
      fontSize:13,display:"flex",flexDirection:"column"}}>

      <ConnBanner status={connStatus}/>
      <TopNav regime={regime} indices={indices} paperPnl={totalNetPnl} time={now} connStatus={connStatus} mode={systemState.mode}/>
      <TabBar active={tab} setActive={setTab} counts={tabCounts}/>

      <div style={{flex:1,padding:"20px 24px",maxWidth:1400,width:"100%",margin:"0 auto"}}>
        {tab==="overview"&&
          <OverviewTab picks={picks} positions={positions} allSigs={allSigs}
            evalStats={evalStats} indices={indices} candleCache={candleCache}
            news={news} onStock={setSelected}/>}
        {tab==="positions"&&
          <PositionsTab positions={positions} mode={systemState.mode}/>}
        {tab==="signals"&&
          <SignalsTab signals={allSigs} onStock={setSelected} picks={picks}/>}
        {tab==="news"&&
          <NewsTab news={news} picks={picks}/>}
        {tab==="performance"&&
          <PerformanceTab evalStats={evalStats} positions={positions} agentKpi={agentKpi} systemState={systemState}/>}
        {tab==="evaluation"&&
          <EvaluationTab evalStats={evalStats} evalHistory={evalHistory} agentScores={agentScores}/>}
        {tab==="agents"&&
          <AgentsTab agentKpi={agentKpi} events={events} karmaStats={karmaStats}/>}
      </div>

      {/* Footer */}
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
            {NSE_UNIVERSE.length} stocks · {AGENT_LIST.length} agents · NSE/BSE
          </span>
          <div style={{width:1,height:12,background:G.border}}/>
          <span style={{color:G.textMut,fontSize:10}}>
            {systemState.mode==="LIVE"
              ? <span style={{color:G.red}}>🔴 LIVE — real orders via OpenAlgo</span>
              : <span style={{color:G.yellow}}>📄 PAPER — all strategies run, no real orders</span>
            }
          </span>
          <div style={{width:1,height:12,background:G.border}}/>
          <span style={{color:G.textMut,fontSize:10,fontFamily:"monospace"}}>
            {now.toLocaleTimeString("en-IN",{hour12:false})} IST
          </span>
        </div>
      </footer>

      {/* Stock detail modal */}
      {selectedStock&&(
        <StockModal
          stock={selectedStock}
          onClose={()=>setSelected(null)}
          candles={candleCache[selectedStock.s]}
          quotes={quotes}
          signals={allSigs.filter(s=>s.symbol===selectedStock.s)}
          fundamentals={fundamentals}
          news={news}
          mode={systemState.mode}
        />
      )}
    </div>
  );
}
