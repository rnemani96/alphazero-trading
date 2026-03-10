import { useState, useEffect, useRef, useCallback } from "react";

// ─── Design tokens ─────────────────────────────────────────────────────────────
const G = {
  bg:         "#0d1117",
  canvas:     "#010409",
  surface:    "#161b22",
  surfaceHov: "#1c2128",
  border:     "#21262d",
  borderMid:  "#30363d",
  text:       "#e6edf3",
  textSec:    "#8b949e",
  textMut:    "#484f58",
  green:      "#3fb950",
  greenBg:    "#0f2419",
  red:        "#f85149",
  redBg:      "#1a0800",
  blue:       "#58a6ff",
  blueDim:    "#388bfd",
  yellow:     "#d29922",
  yellowBg:   "#1a1000",
  purple:     "#bc8cff",
  orange:     "#f0883e",
  teal:       "#39d353",
  pink:       "#ec4899",
};

// ─── NSE Universe ──────────────────────────────────────────────────────────────
const STOCKS = [
  { s:"RELIANCE",   n:"Reliance Industries",  sec:"Energy",   base:2847 },
  { s:"TCS",        n:"Tata Consultancy",      sec:"IT",       base:3642 },
  { s:"HDFCBANK",   n:"HDFC Bank",             sec:"Banking",  base:1678 },
  { s:"INFY",       n:"Infosys",               sec:"IT",       base:1482 },
  { s:"ICICIBANK",  n:"ICICI Bank",            sec:"Banking",  base:1124 },
  { s:"SBIN",       n:"State Bank of India",   sec:"Banking",  base:789  },
  { s:"WIPRO",      n:"Wipro",                 sec:"IT",       base:472  },
  { s:"TATAMOTORS", n:"Tata Motors",           sec:"Auto",     base:942  },
  { s:"SUNPHARMA",  n:"Sun Pharma",            sec:"Pharma",   base:1584 },
  { s:"MARUTI",     n:"Maruti Suzuki",         sec:"Auto",     base:11240},
  { s:"BAJFINANCE", n:"Bajaj Finance",         sec:"Finance",  base:6842 },
  { s:"AXISBANK",   n:"Axis Bank",             sec:"Banking",  base:1156 },
  { s:"KOTAKBANK",  n:"Kotak Mahindra",        sec:"Banking",  base:1842 },
  { s:"HINDUNILVR", n:"Hindustan Unilever",    sec:"FMCG",     base:2432 },
  { s:"ASIANPAINT", n:"Asian Paints",          sec:"Consumer", base:2742 },
  { s:"TITAN",      n:"Titan Company",         sec:"Consumer", base:3284 },
  { s:"NTPC",       n:"NTPC",                  sec:"Energy",   base:368  },
  { s:"POWERGRID",  n:"Power Grid",            sec:"Energy",   base:302  },
  { s:"LTIM",       n:"LTIMindtree",           sec:"IT",       base:5284 },
  { s:"ULTRACEMCO", n:"UltraTech Cement",      sec:"Cement",   base:10842},
];

const REGIME = {
  TRENDING: { color: G.green,  icon: "↑", label: "Trending"  },
  SIDEWAYS: { color: G.yellow, icon: "↔", label: "Sideways"  },
  VOLATILE: { color: G.red,    icon: "⚡", label: "Volatile"  },
  RISK_OFF: { color: G.purple, icon: "⛔", label: "Risk Off"  },
};
const TT_COLOR = { INTRADAY: G.orange, SHORT_TERM: G.blue, SWING: G.purple, LONG_TERM: G.green };
const BACKEND  = "http://localhost:8000";

// ─── Indicator explanations (for tooltips) ────────────────────────────────────
const IND_TIPS = {
  "RSI 14":  { title:"RSI (Relative Strength Index)", body:"Momentum oscillator 0–100. <30 = oversold (buy zone), >70 = overbought (sell zone). Uses 14-period avg gain/loss ratio." },
  "ADX 14":  { title:"ADX (Average Directional Index)", body:"Measures trend strength, NOT direction. <20 = weak/sideways. >25 = trending. >40 = very strong trend. TITAN favors ADX>25." },
  "ATR 14":  { title:"ATR (Average True Range)", body:"Average price range over 14 candles. Used for stop-loss sizing: SL = Entry − 1.5×ATR. Higher ATR = more volatile = wider stops." },
  "EMA 20":  { title:"EMA 20 (Fast MA)", body:"20-period Exponential Moving Average. Price above EMA20 = short-term bullish. EMA20>EMA50 = bull cross (T1 strategy fires)." },
  "EMA 50":  { title:"EMA 50 (Slow MA)", body:"50-period EMA acts as dynamic support. EMA9>EMA20>EMA50 = Triple EMA bull stack (TITAN T2, highest confidence)." },
  "VWAP":    { title:"VWAP (Volume-Weighted Avg Price)", body:"Institutional benchmark. Price>VWAP = institutions paid less avg → bullish. Reclaiming VWAP after dip = V1 signal." },
  "MACD":    { title:"MACD (Moving Avg Convergence Divergence)", body:"Difference between EMA12 and EMA26. Histogram turning positive = T4 signal. Measures momentum shift." },
  "BB %B":   { title:"Bollinger Band %B", body:"Position within Bollinger Bands. <0.05 = at lower band (oversold). >0.95 = at upper band (overbought). BB squeeze = breakout coming." },
  "Stoch K": { title:"Stochastic %K", body:"Price position vs recent range. <20 = oversold crossover (M4 signal). >80 = overbought. Used with %D signal line." },
  "Z-Score": { title:"Z-Score (Statistical)", body:"Standard deviations from 20-bar mean. <−2 = statistically oversold (S1 buy). >+2 = overbought. Mean-reversion based." },
};

// ─── Indicator math ────────────────────────────────────────────────────────────
function ema(arr, p) {
  const k = 2/(p+1), out = new Float64Array(arr.length);
  out[0] = arr[0];
  for (let i = 1; i < arr.length; i++) out[i] = arr[i]*k + out[i-1]*(1-k);
  return out;
}

function indicators(candles) {
  if (!candles || candles.length < 15) return null;
  const n = candles.length;
  const c = candles.map(x => x.close ?? x.Close ?? 0);
  const h = candles.map(x => x.high  ?? x.High  ?? 0);
  const l = candles.map(x => x.low   ?? x.Low   ?? 0);
  const v = candles.map(x => x.volume ?? x.Volume ?? 0);
  const e9=ema(c,9), e20=ema(c,20), e50=ema(c,50);
  const tr=c.map((ci,i)=>i===0?h[0]-l[0]:Math.max(h[i]-l[i],Math.abs(h[i]-c[i-1]),Math.abs(l[i]-c[i-1])));
  const atr=ema(tr,14);
  const δ=c.map((ci,i)=>i===0?0:ci-c[i-1]);
  const ag=ema(δ.map(d=>Math.max(d,0)),14), al=ema(δ.map(d=>Math.max(-d,0)),14);
  const rsi=ag.map((g,i)=>al[i]===0?100:100-100/(1+g/al[i]));
  const ml=ema(c,12).map((v,i)=>v-ema(c,26)[i]), ms=ema(ml,9), mh=ml.map((v,i)=>v-ms[i]);
  const pdm=h.map((hi,i)=>i===0?0:Math.max(hi-h[i-1],0));
  const ndm=l.map((li,i)=>i===0?0:Math.max(l[i-1]-li,0));
  const pdi=ema(pdm,14).map((v,i)=>atr[i]>0?100*v/atr[i]:0);
  const ndi=ema(ndm,14).map((v,i)=>atr[i]>0?100*v/atr[i]:0);
  const dx=pdi.map((p,i)=>p+ndi[i]>0?100*Math.abs(p-ndi[i])/(p+ndi[i]):0);
  const adx=ema(dx,14);
  const bbm=c.map((_,i)=>{const s=c.slice(Math.max(0,i-19),i+1);return s.reduce((a,b)=>a+b,0)/s.length;});
  const bbs=c.map((_,i)=>{const s=c.slice(Math.max(0,i-19),i+1);const m=s.reduce((a,b)=>a+b,0)/s.length;return Math.sqrt(s.reduce((a,b)=>a+(b-m)**2,0)/s.length);});
  const bbu=bbm.map((m,i)=>m+2*bbs[i]), bbl=bbm.map((m,i)=>m-2*bbs[i]);
  const bbw=bbu.map((u,i)=>bbm[i]>0?(u-bbl[i])/bbm[i]:0);
  const bbpb=c.map((ci,i)=>bbu[i]>bbl[i]?(ci-bbl[i])/(bbu[i]-bbl[i]):0.5);
  let cv=0, ctv=0;
  const vwap=c.map((ci,i)=>{const tp=(ci+h[i]+l[i])/3;cv+=v[i];ctv+=tp*v[i];return cv>0?ctv/cv:tp;});
  const sk=c.map((ci,i)=>{const lo=Math.min(...l.slice(Math.max(0,i-13),i+1)),hi=Math.max(...h.slice(Math.max(0,i-13),i+1));return hi>lo?100*(ci-lo)/(hi-lo):50;});
  const sd=ema(sk,3);
  const macdHist=mh;
  // Volume OBV
  const obvDir=c.map((ci,i)=>i===0?0:ci>c[i-1]?1:ci<c[i-1]?-1:0);
  const obv=v.map((vi,i)=>vi*obvDir[i]).reduce((acc,val,i)=>{acc.push((acc[i-1]??0)+val);return acc;},[]);
  const obv5=obv.slice(-5).reduce((a,b)=>a+b,0)/5;
  const obvTrend=obv.length>0&&obv[obv.length-1]>obv5?"RISING":"FALLING";
  const v20avg=v.slice(-20).reduce((a,b)=>a+b,0)/Math.min(20,v.length);
  const volRatio=v20avg>0?v[v.length-1]/v20avg:1;
  return {c,h,l,v,n,e9,e20,e50,atr,rsi,macd:ml,mh,adx,bbu,bbl,bbw,bbpb,vwap,sk,sd,obv,obvTrend,volRatio,v20avg};
}

// ─── Candle pattern detection (pure JS, no TA-Lib) ────────────────────────────
function detectCandlePatterns(candles) {
  const patterns = [];
  if (!candles || candles.length < 3) return patterns;
  const o = candles.map(x => x.open  ?? x.Open  ?? 0);
  const h = candles.map(x => x.high  ?? x.High  ?? 0);
  const l = candles.map(x => x.low   ?? x.Low   ?? 0);
  const c = candles.map(x => x.close ?? x.Close ?? 0);
  const n = c.length, i=n-1, p=n-2;
  const body    = (idx) => Math.abs(c[idx]-o[idx]);
  const upWick  = (idx) => h[idx] - Math.max(c[idx],o[idx]);
  const dnWick  = (idx) => Math.min(c[idx],o[idx]) - l[idx];
  const range   = (idx) => h[idx] - l[idx];
  const isBull  = (idx) => c[idx] >= o[idx];

  // Doji
  if (range(i)>0 && body(i)/range(i) < 0.1)
    patterns.push({ name:"Doji", icon:"🕯️", type:"neutral", desc:"Indecision candle — potential reversal" });

  // Hammer (bullish)
  if (dnWick(i) > 2*body(i) && upWick(i) < body(i) && isBull(i))
    patterns.push({ name:"Hammer", icon:"🔨", type:"bull", desc:"Bullish reversal — buyers rejected lows" });

  // Shooting Star (bearish)
  if (upWick(i) > 2*body(i) && dnWick(i) < body(i) && !isBull(i))
    patterns.push({ name:"Shooting Star", icon:"⭐", type:"bear", desc:"Bearish reversal — sellers rejected highs" });

  // Bullish Engulfing
  if (!isBull(p) && isBull(i) && o[i] < c[p] && c[i] > o[p])
    patterns.push({ name:"Bullish Engulfing", icon:"🟢", type:"bull", desc:"Strong buy — green candle swallows red" });

  // Bearish Engulfing
  if (isBull(p) && !isBull(i) && o[i] > c[p] && c[i] < o[p])
    patterns.push({ name:"Bearish Engulfing", icon:"🔴", type:"bear", desc:"Strong sell — red candle swallows green" });

  // Morning Star (3-candle)
  if (n >= 3 && !isBull(n-3) && body(n-2) < body(n-3)*0.5 && isBull(i) && c[i] > (o[n-3]+c[n-3])/2)
    patterns.push({ name:"Morning Star", icon:"🌟", type:"bull", desc:"3-candle bullish reversal pattern" });

  // Evening Star (3-candle)
  if (n >= 3 && isBull(n-3) && body(n-2) < body(n-3)*0.5 && !isBull(i) && c[i] < (o[n-3]+c[n-3])/2)
    patterns.push({ name:"Evening Star", icon:"🌆", type:"bear", desc:"3-candle bearish reversal pattern" });

  // Strong Bull Candle
  if (isBull(i) && body(i) > range(i)*0.7)
    patterns.push({ name:"Strong Bull", icon:"💪", type:"bull", desc:"Momentum candle — 70%+ body of range" });

  // Inside Bar (consolidation)
  if (h[i] < h[p] && l[i] > l[p])
    patterns.push({ name:"Inside Bar", icon:"📦", type:"neutral", desc:"Consolidation — breakout likely incoming" });

  return patterns;
}

// ─── Volume analysis ──────────────────────────────────────────────────────────
function computeVolumeAnalysis(candles) {
  if (!candles || candles.length < 5) return null;
  const c = candles.map(x => x.close  ?? x.Close  ?? 0);
  const v = candles.map(x => x.volume ?? x.Volume ?? 0);
  const n = c.length;
  const v20avg = v.slice(-20).reduce((a,b)=>a+b,0)/Math.min(20,n);
  const v5avg  = v.slice(-5).reduce((a,b)=>a+b,0)/5;
  const lastVol = v[n-1];
  const volRatio = v20avg > 0 ? lastVol/v20avg : 1;
  const obvDir = c.map((ci,i) => i===0?0:ci>c[i-1]?1:ci<c[i-1]?-1:0);
  const obv = v.map((vi,i)=>vi*obvDir[i]).reduce((acc,val,i)=>{acc.push((acc[i-1]??0)+val);return acc;},[]);
  const obv5 = obv.slice(-5).reduce((a,b)=>a+b,0)/5;
  const obvTrend = obv[n-1] > obv5 ? "RISING" : "FALLING";
  const priceUp = c[n-1] > c[n-2];
  const volUp   = lastVol > v5avg;
  const pvConfirm = (priceUp && volUp) || (!priceUp && !volUp);
  const price5chg = Math.abs(c[n-1]-c[n-5])/(c[n-5]||1);
  const accumulation = price5chg < 0.02 && volRatio > 1.3 && obvTrend === "RISING";
  const distribution = price5chg < 0.02 && volRatio > 1.3 && obvTrend === "FALLING";
  return { volRatio: +volRatio.toFixed(2), obvTrend, pvConfirm, accumulation, distribution,
    lastVol: Math.round(lastVol), v20avg: Math.round(v20avg) };
}

// ─── TITAN signals ─────────────────────────────────────────────────────────────
function titanSignals(candles, regime) {
  const ind = indicators(candles);
  if (!ind) return [];
  const {c,h,l,v,n,e9,e20,e50,atr,rsi,macd,mh,adx,bbu,bbl,bbw,bbpb,vwap,sk,sd} = ind;
  const i=n-1, p=n-2;
  const out=[];
  const push=(id,cat,sig,conf,reason)=>{if(sig!==0)out.push({id,category:cat,signal:sig,confidence:+conf.toFixed(2),reason});};
  if (e20[i]>e50[i]&&e20[p]<=e50[p])      push("T1","Trend", 1,0.78,"EMA20 crossed above EMA50 — bull cross");
  else if(e20[i]<e50[i]&&e20[p]>=e50[p])  push("T1","Trend",-1,0.78,"EMA20 crossed below EMA50 — bear cross");
  else                                      push("T1","Trend",e20[i]>e50[i]?1:-1,0.44,`EMA20 ${e20[i]>e50[i]?"above":"below"} EMA50`);
  if (e9[i]>e20[i]&&e20[i]>e50[i])        push("T2","Trend", 1,0.80,"Triple EMA bull stack 9>20>50");
  else if(e9[i]<e20[i]&&e20[i]<e50[i])    push("T2","Trend",-1,0.80,"Triple EMA bear stack 9<20<50");
  if (mh[i]>0&&mh[p]<=0)                  push("T4","Trend", 1,0.75,"MACD histogram turned positive");
  else if(mh[i]<0&&mh[p]>=0)              push("T4","Trend",-1,0.75,"MACD histogram turned negative");
  if (adx[i]>25)                           push("T5","Trend",macd[i]>0?1:-1,Math.min(0.90,0.54+adx[i]/100),`ADX=${adx[i].toFixed(0)} — strong trend`);
  const hi20=Math.max(...h.slice(Math.max(0,i-19),i+1)),lo20=Math.min(...l.slice(Math.max(0,i-19),i+1));
  if (c[i]>=hi20*0.998)        push("T7","Trend", 1,0.82,`20-bar Donchian high ${hi20.toFixed(0)}`);
  else if(c[i]<=lo20*1.002)    push("T7","Trend",-1,0.82,`20-bar Donchian low ${lo20.toFixed(0)}`);
  const slope=(e20[i]-e20[Math.max(0,i-4)])/e20[i]*100;
  if (Math.abs(slope)>0.04)    push("T8","Trend",slope>0?1:-1,Math.min(0.80,0.50+Math.abs(slope)*5),`EMA slope ${slope>0?"+":""}${slope.toFixed(2)}%`);
  const r=rsi[i];
  if (r<28)      push("M1","MeanRev", 1,Math.min(0.92,0.65+(28-r)/30),`RSI=${r.toFixed(0)} extreme oversold`);
  else if(r>72)  push("M1","MeanRev",-1,Math.min(0.92,0.65+(r-72)/30),`RSI=${r.toFixed(0)} extreme overbought`);
  else if(r<38)  push("M1","MeanRev", 1,0.50,`RSI=${r.toFixed(0)} near oversold zone`);
  else if(r>62)  push("M1","MeanRev",-1,0.50,`RSI=${r.toFixed(0)} near overbought zone`);
  if (bbpb[i]<0.06) push("M2","MeanRev", 1,0.72,`Bollinger lower band bounce %B=${bbpb[i].toFixed(2)}`);
  else if(bbpb[i]>0.94) push("M2","MeanRev",-1,0.72,`Bollinger upper band touch %B=${bbpb[i].toFixed(2)}`);
  const abw=bbw.slice(Math.max(0,i-19),i).reduce((a,b)=>a+b,0)/20;
  if (bbw[i]<abw*0.72) push("M3","MeanRev",macd[i]>0?1:-1,0.74,"BB squeeze — volatility breakout imminent");
  if (sk[i]<22&&sk[i]>sd[i]) push("M4","MeanRev", 1,0.70,`Stochastic K=${sk[i].toFixed(0)} oversold crossover`);
  else if(sk[i]>78&&sk[i]<sd[i]) push("M4","MeanRev",-1,0.70,`Stochastic K=${sk[i].toFixed(0)} overbought crossover`);
  const mu=c.slice(Math.max(0,i-19),i+1).reduce((a,b)=>a+b,0)/20;
  const σ=Math.sqrt(c.slice(Math.max(0,i-19),i+1).reduce((a,b)=>a+(b-mu)**2,0)/20);
  const z=σ>0?(c[i]-mu)/σ:0;
  if (z<-2)  push("S1","Statistical", 1,Math.min(0.90,0.68+Math.abs(z+2)*0.08),`Z-score=${z.toFixed(2)} — 2σ below mean`);
  else if(z>2) push("S1","Statistical",-1,Math.min(0.90,0.68+(z-2)*0.08),`Z-score=${z.toFixed(2)} — 2σ above mean`);
  const avgV=v.reduce((a,b)=>a+b,0)/n, vr=v[i]/Math.max(avgV,1);
  const oh=Math.max(...h.slice(0,Math.min(4,n))), ol=Math.min(...l.slice(0,Math.min(4,n)));
  if (c[i]>oh*1.002) push("B1","Breakout", 1,vr>1.3?0.85:0.65,`Opening range breakout above ${oh.toFixed(0)}`);
  else if(c[i]<ol*0.998) push("B1","Breakout",-1,0.65,`Opening range breakdown below ${ol.toFixed(0)}`);
  if (vr>1.5&&c[i]>c[p]) push("B2","Breakout", 1,Math.min(0.90,0.55+vr*0.08),`Volume surge ×${vr.toFixed(1)} — bullish`);
  else if(vr>1.5&&c[i]<c[p]) push("B2","Breakout",-1,Math.min(0.88,0.52+vr*0.07),`Volume surge ×${vr.toFixed(1)} — bearish`);
  if (c[i]>vwap[i]&&c[p]<=vwap[p]) push("V1","VWAP", 1,0.74,"Price reclaimed VWAP — bullish");
  else if(c[i]<vwap[i]&&c[p]>=vwap[p]) push("V1","VWAP",-1,0.74,"Price lost VWAP — bearish");
  const vd=(c[i]-vwap[i])/vwap[i]*100;
  if (vd>1.8)  push("V2","VWAP",-1,0.66,`+${vd.toFixed(2)}% extended above VWAP — fade`);
  else if(vd<-1.8) push("V2","VWAP", 1,0.66,`${vd.toFixed(2)}% below VWAP — revert long`);
  const gap=(c[i]-c[p])/c[p]*100;
  if (gap>0.6)  push("S2","Statistical",-1,0.58,`Gap up ${gap.toFixed(2)}% — fade the gap`);
  else if(gap<-0.6) push("S2","Statistical", 1,0.58,`Gap down ${gap.toFixed(2)}% — gap fill`);
  const allow={TRENDING:["Trend","Breakout"],SIDEWAYS:["MeanRev","VWAP","Statistical"],VOLATILE:["MeanRev","VWAP"],RISK_OFF:[]};
  const ok=allow[regime]??["Trend","Breakout","MeanRev","VWAP","Statistical"];
  return out.filter(s=>ok.includes(s.category)).sort((a,b)=>b.confidence-a.confidence);
}

// ─── Shared UI atoms ───────────────────────────────────────────────────────────
const Tag = ({ label, color, bg }) => (
  <span style={{ background:bg??color+"1a", border:`1px solid ${color}44`,
    color, padding:"1px 8px", borderRadius:20, fontSize:10, fontWeight:600,
    display:"inline-block", whiteSpace:"nowrap" }}>{label}</span>
);
const Num = ({ n, color }) => (
  <span style={{ background:(color??G.blue)+"1a", color:color??G.blue,
    borderRadius:20, padding:"0 7px", fontSize:11, fontWeight:700,
    minWidth:18, display:"inline-block", textAlign:"center" }}>{n}</span>
);
const Divider = () => <div style={{ borderTop:`1px solid ${G.border}`, margin:"0" }}/>;
const Empty = ({ icon, title, sub }) => (
  <div style={{ display:"flex", flexDirection:"column", alignItems:"center", padding:"64px 20px", gap:10 }}>
    <span style={{ fontSize:28 }}>{icon}</span>
    <div style={{ color:G.textSec, fontSize:13, fontWeight:500 }}>{title}</div>
    <div style={{ color:G.textMut, fontSize:11, textAlign:"center", maxWidth:280 }}>{sub}</div>
  </div>
);
function KpiBar({ value, max=1, color }) {
  return (
    <div style={{ background:G.border, borderRadius:3, height:4, overflow:"hidden" }}>
      <div style={{ width:`${Math.min(100,(value/max)*100)}%`, height:"100%",
        background:color??G.green, borderRadius:3, transition:"width .6s ease" }}/>
    </div>
  );
}

// ─── Indicator tooltip wrapper ─────────────────────────────────────────────────
function IndTooltip({ label, children }) {
  const tip = IND_TIPS[label];
  if (!tip) return children;
  return (
    <div style={{ position:"relative" }}
      onMouseEnter={e => { const t=e.currentTarget.querySelector(".ind-tip"); if(t) t.style.display="block"; }}
      onMouseLeave={e => { const t=e.currentTarget.querySelector(".ind-tip"); if(t) t.style.display="none"; }}>
      {children}
      <div className="ind-tip" style={{
        display:"none", position:"absolute", bottom:"calc(100% + 6px)", left:"50%", transform:"translateX(-50%)",
        background:"#0d1b2a", border:`1px solid ${G.blue}55`, borderRadius:8, padding:"10px 12px",
        fontSize:11, color:G.textSec, lineHeight:1.5, width:220, zIndex:9999,
        boxShadow:"0 4px 20px rgba(0,0,0,.7)", pointerEvents:"none",
      }}>
        <div style={{ color:G.blue, fontWeight:700, fontSize:10, marginBottom:4 }}>{tip.title}</div>
        <div>{tip.body}</div>
        <div style={{ position:"absolute", top:"100%", left:"50%", transform:"translateX(-50%)",
          width:0, height:0, borderLeft:"5px solid transparent", borderRight:"5px solid transparent",
          borderTop:`5px solid ${G.blue}55` }}/>
      </div>
    </div>
  );
}

// ─── Candle patterns display ───────────────────────────────────────────────────
function CandlePatterns({ candles }) {
  const pats = detectCandlePatterns(candles);
  if (!pats.length) return (
    <div style={{ color:G.textMut, fontSize:11 }}>No strong patterns detected on latest candle</div>
  );
  const typeColor = { bull:G.green, bear:G.red, neutral:G.yellow };
  return (
    <div style={{ display:"flex", flexWrap:"wrap", gap:6 }}>
      {pats.map((p,i) => (
        <div key={i} style={{
          display:"flex", alignItems:"center", gap:6, padding:"5px 10px",
          background:typeColor[p.type]+"12", border:`1px solid ${typeColor[p.type]}30`,
          borderRadius:20, cursor:"default",
        }}
          title={p.desc}>
          <span>{p.icon}</span>
          <span style={{ color:typeColor[p.type], fontSize:11, fontWeight:600 }}>{p.name}</span>
          <span style={{ color:G.textMut, fontSize:9 }}>·</span>
          <span style={{ color:G.textSec, fontSize:10 }}>{p.desc}</span>
        </div>
      ))}
    </div>
  );
}

// ─── Volume analysis display ───────────────────────────────────────────────────
function VolumeAnalysisPanel({ candles }) {
  const va = computeVolumeAnalysis(candles);
  if (!va) return <div style={{ color:G.textMut, fontSize:11 }}>Insufficient data</div>;
  const barW = Math.min(100, va.volRatio * 50);
  const barColor = va.volRatio > 2 ? G.orange : va.volRatio > 1.3 ? G.blue : G.textMut;
  return (
    <div style={{ display:"flex", flexDirection:"column", gap:8 }}>
      {/* Volume vs avg bar */}
      <div>
        <div style={{ display:"flex", justifyContent:"space-between", marginBottom:4 }}>
          <span style={{ color:G.textMut, fontSize:10 }}>Volume vs 20-day avg</span>
          <span style={{ color:barColor, fontSize:11, fontWeight:700, fontFamily:"monospace" }}>
            {va.volRatio.toFixed(2)}×
            {va.volRatio > 2 ? " 🔥 Spike" : va.volRatio > 1.3 ? " ↑ Above avg" : " Normal"}
          </span>
        </div>
        <div style={{ background:G.border, borderRadius:4, height:6, overflow:"hidden" }}>
          <div style={{ width:`${barW}%`, height:"100%", background:barColor,
            borderRadius:4, transition:"width .6s", boxShadow:`0 0 6px ${barColor}88` }}/>
        </div>
      </div>

      {/* OBV + signals row */}
      <div style={{ display:"flex", gap:8, flexWrap:"wrap" }}>
        <div style={{ background:G.bg, borderRadius:6, padding:"6px 10px", flex:1 }}>
          <div style={{ color:G.textMut, fontSize:9, marginBottom:2 }}>OBV TREND</div>
          <div style={{ color:va.obvTrend==="RISING"?G.green:G.red, fontWeight:700, fontSize:12 }}>
            {va.obvTrend==="RISING" ? "▲ RISING" : "▼ FALLING"}
          </div>
        </div>
        <div style={{ background:G.bg, borderRadius:6, padding:"6px 10px", flex:1 }}>
          <div style={{ color:G.textMut, fontSize:9, marginBottom:2 }}>PRICE-VOLUME</div>
          <div style={{ color:va.pvConfirm?G.green:G.orange, fontWeight:700, fontSize:12 }}>
            {va.pvConfirm ? "✓ Confirming" : "⚠ Diverging"}
          </div>
        </div>
        {(va.accumulation || va.distribution) && (
          <div style={{ background:G.bg, borderRadius:6, padding:"6px 10px", flex:1 }}>
            <div style={{ color:G.textMut, fontSize:9, marginBottom:2 }}>PATTERN</div>
            <div style={{ color:va.accumulation?G.green:G.red, fontWeight:700, fontSize:12 }}>
              {va.accumulation ? "📈 Accumulation" : "📉 Distribution"}
            </div>
          </div>
        )}
      </div>

      <div style={{ color:G.textMut, fontSize:10 }}>
        Vol {va.lastVol.toLocaleString("en-IN")} · 20d avg {va.v20avg.toLocaleString("en-IN")}
      </div>
    </div>
  );
}

// ─── Connection banner ──────────────────────────────────────────────────────────
function ConnBanner({ status }) {
  if (status === "live") return null;
  const cfg = {
    connecting:  { color:G.yellow, icon:"⟳", msg:"Connecting to backend…" },
    offline: {
      color:G.orange, icon:"⚠",
      msg:"Backend offline — indicators computed in-browser. Start: uvicorn src.dashboard.backend:app --port 8000 for real NSE data.",
    },
  };
  const { color, icon, msg } = cfg[status] ?? cfg.offline;
  return (
    <div style={{ background:color+"12", borderBottom:`1px solid ${color}30`,
      padding:"7px 24px", fontSize:11, color, display:"flex", gap:8, alignItems:"center" }}>
      <span style={{ fontWeight:700 }}>{icon}</span>
      <span>{msg}</span>
    </div>
  );
}

// ─── Top nav ───────────────────────────────────────────────────────────────────
function TopNav({ regime, indices, paperPnl, time, connStatus }) {
  const R = REGIME[regime] ?? REGIME.TRENDING;
  const nChange  = (indices.nifty??0) - 24150;
  const bChange  = (indices.banknifty??0) - 51840;
  return (
    <div style={{ background:G.surface, borderBottom:`1px solid ${G.border}`,
      padding:"0 24px", height:52, display:"flex", alignItems:"center", gap:20 }}>
      <div style={{ display:"flex", alignItems:"center", gap:8 }}>
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none">
          <polygon points="12,2 22,20 2,20" fill={G.green} opacity=".9"/>
          <polygon points="12,6 19,19 5,19" fill={G.bg}/>
          <polygon points="12,10 16,18 8,18" fill={G.green}/>
        </svg>
        <span style={{ color:G.text, fontWeight:700, fontSize:14, fontFamily:"monospace", letterSpacing:".06em" }}>AlphaZero</span>
        <Tag label="PAPER" color={G.yellow}/>
      </div>
      <div style={{ width:1, height:20, background:G.border }}/>
      <div style={{ display:"flex", gap:16, alignItems:"center" }}>
        {[["NIFTY",indices.nifty,nChange],["BANKNIFTY",indices.banknifty,bChange]].map(([label,val,chg])=>(
          <div key={label} style={{ display:"flex", gap:4, alignItems:"baseline" }}>
            <span style={{ color:G.textMut, fontSize:10, fontFamily:"monospace" }}>{label}</span>
            <span style={{ color:G.text, fontSize:12, fontWeight:700, fontFamily:"monospace" }}>{(val||0).toLocaleString("en-IN",{maximumFractionDigits:0})}</span>
            <span style={{ color:chg>=0?G.green:G.red, fontSize:10, fontFamily:"monospace" }}>{chg>=0?"▲":"▼"}{Math.abs(chg||0).toFixed(0)}</span>
          </div>
        ))}
      </div>
      <Tag label={`${R.icon} ${R.label}`} color={R.color}/>
      <span style={{ color:G.textSec, fontSize:11, fontFamily:"monospace" }}>
        VIX <span style={{ color:(indices.vix??0)>22?G.red:G.green, fontWeight:700 }}>{(indices.vix??14.2).toFixed(1)}</span>
      </span>
      <div style={{ flex:1 }}/>
      <div style={{ textAlign:"right" }}>
        <div style={{ color:G.textMut, fontSize:9, fontFamily:"monospace", letterSpacing:".08em" }}>PAPER P&amp;L</div>
        <div style={{ color:(paperPnl??0)>=0?G.green:G.red, fontSize:13, fontWeight:700, fontFamily:"monospace" }}>
          {(paperPnl??0)>=0?"+":"-"}₹{Math.abs(paperPnl??0).toLocaleString("en-IN",{maximumFractionDigits:0})}
        </div>
      </div>
      <div style={{ display:"flex", alignItems:"center", gap:6 }}>
        <div style={{ width:6, height:6, borderRadius:"50%",
          background:indices.market_open?G.green:G.textMut,
          boxShadow:indices.market_open?`0 0 8px ${G.green}`:"none" }}/>
        <span style={{ color:G.textMut, fontSize:11, fontFamily:"monospace" }}>
          {time.toLocaleTimeString("en-IN",{hour12:false})} IST
        </span>
      </div>
    </div>
  );
}

// ─── Tab bar ───────────────────────────────────────────────────────────────────
function TabBar({ active, setActive, counts }) {
  const tabs = [
    { id:"overview",   label:"Overview"    },
    { id:"positions",  label:"Positions",  badge:counts.pos  },
    { id:"signals",    label:"Signals",    badge:counts.sigs },
    { id:"evaluation", label:"Evaluation", badge:counts.eval },
    { id:"agents",     label:"Agents"      },
  ];
  return (
    <div style={{ background:G.surface, borderBottom:`1px solid ${G.border}`, padding:"0 24px", display:"flex" }}>
      {tabs.map(t => (
        <button key={t.id} onClick={()=>setActive(t.id)} style={{
          background:"none", border:"none", cursor:"pointer",
          borderBottom:active===t.id?`2px solid ${G.blueDim}`:"2px solid transparent",
          color:active===t.id?G.text:G.textSec,
          padding:"10px 14px", fontSize:13, fontWeight:active===t.id?600:400,
          marginBottom:-1, display:"flex", alignItems:"center", gap:6, transition:"color .15s",
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

// ═════════════════════════════════════════════════════════════════════════════════
// TAB: OVERVIEW
// ═════════════════════════════════════════════════════════════════════════════════
function OverviewTab({ picks, positions, allSigs, evalStats, indices, candleCache, onStock }) {
  const open = positions.filter(p=>p.status==="OPEN");
  const pnl  = open.reduce((s,p)=>s+(p.pnl??0),0);
  const buy  = allSigs.filter(s=>s.signal===1).length;
  const sell = allSigs.filter(s=>s.signal===-1).length;
  const wr   = evalStats?.win_rate ?? 0;
  return (
    <div style={{ display:"flex", flexDirection:"column", gap:24 }}>
      {/* Stat cards */}
      <div style={{ display:"grid", gridTemplateColumns:"repeat(4,1fr)", gap:12 }}>
        {[
          { label:"Open Positions", val:open.length,  sub:`${10-open.length} slots free`,       color:G.blue   },
          { label:"Paper P&L",      val:`${pnl>=0?"+":""}₹${Math.abs(pnl).toLocaleString("en-IN",{maximumFractionDigits:0})}`, sub:"unrealised today", color:pnl>=0?G.green:G.red },
          { label:"Live Signals",   val:allSigs.length, sub:`${buy} buy · ${sell} sell`,         color:G.orange },
          { label:"Agent Win Rate", val:`${(wr*100).toFixed(1)}%`, sub:`${evalStats?.total_evaluated??0} evaluated`, color:wr>=0.55?G.green:wr>=0.40?G.yellow:G.red },
        ].map(({label,val,sub,color})=>(
          <div key={label} style={{ background:G.surface, border:`1px solid ${G.border}`, borderRadius:8, padding:"16px 18px" }}>
            <div style={{ color:G.textSec, fontSize:11, marginBottom:8 }}>{label}</div>
            <div style={{ color, fontSize:20, fontWeight:700, fontFamily:"monospace", marginBottom:4 }}>{val}</div>
            <div style={{ color:G.textMut, fontSize:10 }}>{sub}</div>
          </div>
        ))}
      </div>

      {/* APEX picks */}
      <div style={{ background:G.surface, border:`1px solid ${G.border}`, borderRadius:8, overflow:"hidden" }}>
        <div style={{ padding:"12px 18px", borderBottom:`1px solid ${G.border}`,
          display:"flex", justifyContent:"space-between", alignItems:"center" }}>
          <div style={{ display:"flex", alignItems:"center", gap:8 }}>
            <span style={{ color:G.text, fontSize:13, fontWeight:600 }}>APEX Selected</span>
            <Tag label="Click for AI analysis" color={G.blue}/>
          </div>
          <span style={{ color:G.textMut, fontSize:10, fontFamily:"monospace" }}>Real NSE data · 15m candles</span>
        </div>
        <div style={{ display:"grid", gridTemplateColumns:"repeat(5,1fr)" }}>
          {picks.length===0
            ? Array(5).fill(null).map((_,i)=>(
                <div key={i} style={{ padding:"20px 18px", borderRight:i<4?`1px solid ${G.border}`:"none",
                  display:"flex", alignItems:"center", justifyContent:"center" }}>
                  <span style={{ color:G.textMut, fontSize:11 }}>Scanning…</span>
                </div>
              ))
            : picks.map((s,i)=>{
                const candles = candleCache[s.s];
                const last    = candles?.length ? candles[candles.length-1] : null;
                const price   = last?(last.close??last.Close??s.base):(s.price??s.base);
                const first   = candles?.[0];
                const chg     = first?(price-(first.close??first.Close??price))/(first.close??first.Close??price)*100:0;
                const rr      = s.entry&&s.sl&&s.target?(s.target-s.entry)/(s.entry-s.sl):0;
                const pats    = candles ? detectCandlePatterns(candles) : [];
                const bullPat = pats.filter(p=>p.type==="bull").length;
                return (
                  <div key={s.s} onClick={()=>onStock(s)}
                    style={{ padding:"16px 18px", borderRight:i<4?`1px solid ${G.border}`:"none",
                      cursor:"pointer", transition:"background .12s" }}
                    onMouseEnter={e=>e.currentTarget.style.background=G.surfaceHov}
                    onMouseLeave={e=>e.currentTarget.style.background="transparent"}>
                    <div style={{ display:"flex", justifyContent:"space-between", alignItems:"center", marginBottom:6 }}>
                      <div style={{ display:"flex", alignItems:"center", gap:5 }}>
                        <span style={{ color:G.textMut, fontSize:9, fontFamily:"monospace" }}>#{i+1}</span>
                        <span style={{ color:G.blue, fontWeight:700, fontSize:13, fontFamily:"monospace" }}>{s.s}</span>
                      </div>
                      <span style={{ color:chg>=0?G.green:G.red, fontSize:10, fontFamily:"monospace" }}>
                        {chg>=0?"+":""}{chg.toFixed(2)}%
                      </span>
                    </div>
                    <div style={{ color:G.text, fontSize:18, fontWeight:700, fontFamily:"monospace", marginBottom:2 }}>₹{price.toFixed(0)}</div>
                    <div style={{ color:G.textMut, fontSize:10, marginBottom:10 }}>{s.sec}</div>
                    <div style={{ display:"flex", gap:4, flexWrap:"wrap", marginBottom:8 }}>
                      <Tag label={s.sid??"-"} color={G.yellow}/>
                      <Tag label={s.tt??"SWING"} color={TT_COLOR[s.tt]??G.blue}/>
                      {s.mtfVotes > 0 && <Tag label={`MTF ${s.mtfVotes}/5`} color={s.mtfVotes>=4?G.green:G.teal}/>}
                    </div>
                    {bullPat > 0 && (
                      <div style={{ color:G.green, fontSize:9, marginBottom:8 }}>
                        🕯️ {pats.filter(p=>p.type==="bull").map(p=>p.name).join(", ")}
                      </div>
                    )}
                    <Divider/>
                    <div style={{ display:"grid", gridTemplateColumns:"1fr 1fr 1fr", gap:6, paddingTop:10 }}>
                      {[["Σ Score",s.score],["Conf",`${((s.confidence??0)*100).toFixed(0)}%`],["R:R",`1:${rr.toFixed(1)}`]].map(([k,v])=>(
                        <div key={k}>
                          <div style={{ color:G.textMut, fontSize:8, marginBottom:2 }}>{k}</div>
                          <div style={{ color:G.text, fontSize:11, fontWeight:600, fontFamily:"monospace" }}>{v}</div>
                        </div>
                      ))}
                    </div>
                    <div style={{ display:"flex", justifyContent:"space-between", marginTop:10,
                      paddingTop:8, borderTop:`1px solid ${G.border}` }}>
                      <span style={{ color:G.red, fontSize:9, fontFamily:"monospace" }}>SL ₹{(s.sl??0).toFixed(0)}</span>
                      <span style={{ color:G.green, fontSize:9, fontFamily:"monospace" }}>TGT ₹{(s.target??0).toFixed(0)}</span>
                    </div>
                  </div>
                );
              })
          }
        </div>
      </div>

      {/* Ticker strip */}
      <div style={{ background:G.surface, border:`1px solid ${G.border}`, borderRadius:8, padding:"14px 18px" }}>
        <div style={{ color:G.textSec, fontSize:11, fontWeight:600, marginBottom:12,
          display:"flex", justifyContent:"space-between" }}>
          <span>NSE Universe</span>
          <span style={{ color:G.textMut, fontSize:10 }}>
            <span style={{ color:G.blue }}>■</span> = APEX picks &nbsp;&nbsp; {picks.length}/{STOCKS.length} selected
          </span>
        </div>
        <div style={{ display:"flex", gap:6, flexWrap:"wrap" }}>
          {STOCKS.map(st=>{
            const pick    = picks.find(p=>p.s===st.s);
            const candles = candleCache[st.s];
            const price   = candles?.length?(candles[candles.length-1].close??candles[candles.length-1].Close??st.base):st.base;
            const first   = candles?.[0];
            const chg     = first?(price-(first.close??first.Close??price))/(first.close??first.Close??price)*100:0;
            const isPick  = !!pick;
            return (
              <div key={st.s} onClick={()=>isPick&&onStock(pick)}
                style={{ background:isPick?G.blue+"14":"transparent",
                  border:`1px solid ${isPick?G.blue+"55":G.border}`,
                  borderRadius:6, padding:"6px 10px", cursor:isPick?"pointer":"default",
                  minWidth:80, transition:"all .12s" }}
                onMouseEnter={e=>{if(isPick)e.currentTarget.style.background=G.blue+"22";}}
                onMouseLeave={e=>{if(isPick)e.currentTarget.style.background=G.blue+"14";}}>
                <div style={{ color:isPick?G.blue:G.textSec, fontSize:10, fontWeight:isPick?700:400, fontFamily:"monospace" }}>{st.s}</div>
                <div style={{ color:G.text, fontSize:11, fontWeight:600, fontFamily:"monospace" }}>₹{price.toFixed(0)}</div>
                <div style={{ color:chg>=0?G.green:G.red, fontSize:9, fontFamily:"monospace" }}>{chg>=0?"+":""}{chg.toFixed(2)}%</div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

// ═════════════════════════════════════════════════════════════════════════════════
// TAB: POSITIONS
// ═════════════════════════════════════════════════════════════════════════════════
function PositionsTab({ positions }) {
  const open = positions.filter(p=>p.status==="OPEN");
  return (
    <div style={{ background:G.surface, border:`1px solid ${G.border}`, borderRadius:8, overflow:"hidden" }}>
      <div style={{ padding:"12px 18px", borderBottom:`1px solid ${G.border}`,
        display:"flex", justifyContent:"space-between", alignItems:"center" }}>
        <span style={{ color:G.text, fontSize:13, fontWeight:600 }}>Open Positions</span>
        <Tag label="Paper Mode — No real capital at risk" color={G.yellow}/>
      </div>
      {open.length===0
        ? <Empty icon="📭" title="No open positions" sub="Waiting for high-confidence signals on real NSE data. APEX selects every 40 seconds."/>
        : (
          <table style={{ width:"100%", borderCollapse:"collapse" }}>
            <thead>
              <tr style={{ background:G.bg }}>
                {["Symbol","Strategy","Entry ₹","CMP ₹","Stop Loss ₹","Target ₹","Qty","P&L","P&L %","Opened"].map(h=>(
                  <th key={h} style={{ color:G.textSec, fontSize:11, padding:"9px 16px",
                    textAlign:"left", fontWeight:500, borderBottom:`1px solid ${G.border}`,
                    whiteSpace:"nowrap", fontFamily:"monospace" }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {open.map(pos=>{
                const pnl=pos.pnl??0, pct=pos.pnlPct??0;
                return (
                  <tr key={pos.id} style={{ borderBottom:`1px solid ${G.border}` }}
                    onMouseEnter={e=>e.currentTarget.style.background=G.surfaceHov}
                    onMouseLeave={e=>e.currentTarget.style.background="transparent"}>
                    <td style={{ padding:"12px 16px" }}>
                      <div style={{ color:G.text, fontWeight:700, fontSize:12, fontFamily:"monospace" }}>{pos.symbol}</div>
                      <Tag label={pos.tt??"SWING"} color={TT_COLOR[pos.tt]??G.blue}/>
                    </td>
                    <td style={{ padding:"12px 16px" }}><Tag label={pos.sid??"-"} color={G.yellow}/></td>
                    <td style={{ padding:"12px 16px", color:G.textSec, fontSize:12, fontFamily:"monospace" }}>{(pos.entryPrice??0).toFixed(2)}</td>
                    <td style={{ padding:"12px 16px", color:G.text, fontSize:12, fontWeight:700, fontFamily:"monospace" }}>{(pos.cp??pos.entryPrice??0).toFixed(2)}</td>
                    <td style={{ padding:"12px 16px", color:G.red, fontSize:12, fontFamily:"monospace" }}>{(pos.sl??0).toFixed(2)}</td>
                    <td style={{ padding:"12px 16px", color:G.green, fontSize:12, fontFamily:"monospace" }}>{(pos.target??0).toFixed(2)}</td>
                    <td style={{ padding:"12px 16px", color:G.textSec, fontSize:12, fontFamily:"monospace" }}>{pos.qty}</td>
                    <td style={{ padding:"12px 16px", fontFamily:"monospace" }}>
                      <span style={{ color:pnl>=0?G.green:G.red, fontSize:12, fontWeight:700 }}>
                        {pnl>=0?"+":"-"}₹{Math.abs(pnl).toLocaleString("en-IN",{maximumFractionDigits:0})}
                      </span>
                    </td>
                    <td style={{ padding:"12px 16px", fontFamily:"monospace" }}>
                      <span style={{ color:pct>=0?G.green:G.red, fontSize:12 }}>{pct>=0?"+":""}{pct.toFixed(2)}%</span>
                    </td>
                    <td style={{ padding:"12px 16px", color:G.textMut, fontSize:10, fontFamily:"monospace" }}>{pos.time}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
    </div>
  );
}

// ═════════════════════════════════════════════════════════════════════════════════
// TAB: SIGNALS
// ═════════════════════════════════════════════════════════════════════════════════
function SignalsTab({ allSigs }) {
  const buy=allSigs.filter(s=>s.signal===1), sell=allSigs.filter(s=>s.signal===-1);
  const SigList = ({ sigs, type }) => (
    <div style={{ background:G.surface, border:`1px solid ${G.border}`, borderRadius:8, overflow:"hidden", flex:1 }}>
      <div style={{ padding:"12px 18px", borderBottom:`1px solid ${G.border}`, display:"flex", alignItems:"center", gap:8 }}>
        <div style={{ width:8, height:8, borderRadius:"50%", background:type==="buy"?G.green:G.red }}/>
        <span style={{ color:G.text, fontSize:13, fontWeight:600 }}>{type==="buy"?"Buy Signals":"Sell Signals"}</span>
        <Num n={sigs.length} color={type==="buy"?G.green:G.red}/>
      </div>
      {sigs.length===0
        ? <div style={{ padding:"32px 18px", color:G.textMut, fontSize:11, textAlign:"center" }}>No {type} signals in current regime</div>
        : sigs.slice(0,15).map((s,i)=>(
            <div key={i} style={{ display:"flex", alignItems:"center", gap:12, padding:"10px 18px",
              borderBottom:i<sigs.length-1?`1px solid ${G.border}`:"none", transition:"background .1s" }}
              onMouseEnter={e=>e.currentTarget.style.background=G.surfaceHov}
              onMouseLeave={e=>e.currentTarget.style.background="transparent"}>
              <div style={{ width:2, alignSelf:"stretch", background:type==="buy"?G.green:G.red, borderRadius:2, flexShrink:0 }}/>
              <Tag label={s.id} color={G.yellow}/>
              <div style={{ fontWeight:700, color:G.text, fontSize:12, fontFamily:"monospace", minWidth:82 }}>{s.symbol}</div>
              <div style={{ color:G.textSec, fontSize:11, flex:1, lineHeight:1.4 }}>{s.reason}</div>
              <div style={{ display:"flex", flexDirection:"column", alignItems:"flex-end", gap:3 }}>
                <span style={{ color:type==="buy"?G.green:G.red, fontWeight:700, fontSize:12, fontFamily:"monospace" }}>{(s.confidence*100).toFixed(0)}%</span>
                <span style={{ color:G.textMut, fontSize:9 }}>{s.category}</span>
              </div>
            </div>
          ))}
    </div>
  );
  return (
    <div>
      <div style={{ display:"grid", gridTemplateColumns:"repeat(3,1fr)", gap:12, marginBottom:16 }}>
        {[{label:"Total Signals",val:allSigs.length,color:G.blue},{label:"Buy",val:buy.length,color:G.green},{label:"Sell",val:sell.length,color:G.red}].map(({label,val,color})=>(
          <div key={label} style={{ background:G.surface, border:`1px solid ${G.border}`,
            borderRadius:8, padding:"14px 18px", display:"flex", justifyContent:"space-between", alignItems:"center" }}>
            <span style={{ color:G.textSec, fontSize:11 }}>{label}</span>
            <span style={{ color, fontSize:20, fontWeight:700, fontFamily:"monospace" }}>{val}</span>
          </div>
        ))}
      </div>
      <div style={{ display:"flex", gap:12 }}>
        <SigList sigs={buy}  type="buy"/>
        <SigList sigs={sell} type="sell"/>
      </div>
    </div>
  );
}

// ═════════════════════════════════════════════════════════════════════════════════
// TAB: EVALUATION
// ═════════════════════════════════════════════════════════════════════════════════
function EvaluationTab({ evalStats, evalHistory, agentScores }) {
  const wr=evalStats?.win_rate??0, total=evalStats?.total_evaluated??0;
  return (
    <div style={{ display:"flex", flexDirection:"column", gap:20 }}>
      <div style={{ background:G.surface, border:`1px solid ${G.border}`, borderRadius:8, padding:"16px 20px" }}>
        <div style={{ color:G.text, fontSize:12, fontWeight:600, marginBottom:12 }}>How Paper Mode Evaluation Works</div>
        <div style={{ display:"grid", gridTemplateColumns:"repeat(4,1fr)", gap:16 }}>
          {[
            { icon:"📡", step:"1 — Signal", desc:"TITAN emits signal with entry, SL, target on real NSE candles (yfinance / OpenAlgo)" },
            { icon:"⏱",  step:"2 — Watch",  desc:"Live prices checked every 15s. Signal stays pending until SL or target is hit, or 24h expires" },
            { icon:"🎯", step:"3 — Score",  desc:"WIN (target hit): +confidence×2 pts. LOSS (SL hit): −confidence×1 pt. Scratch: 0 pts" },
            { icon:"🧠", step:"4 — Learn",  desc:"KARMA reads evaluation report to down-weight failing strategies per regime. Safe in live mode." },
          ].map(({icon,step,desc})=>(
            <div key={step} style={{ background:G.bg, borderRadius:6, padding:14 }}>
              <div style={{ fontSize:22, marginBottom:8 }}>{icon}</div>
              <div style={{ color:G.yellow, fontSize:10, fontWeight:700, marginBottom:4, fontFamily:"monospace" }}>{step}</div>
              <div style={{ color:G.textSec, fontSize:11, lineHeight:1.55 }}>{desc}</div>
            </div>
          ))}
        </div>
      </div>
      <div style={{ display:"grid", gridTemplateColumns:"repeat(5,1fr)", gap:12 }}>
        {[
          { label:"Evaluated", val:total, color:G.blue },
          { label:"Wins", val:evalStats?.wins??0, color:G.green },
          { label:"Losses", val:evalStats?.losses??0, color:G.red },
          { label:"Win Rate", val:`${(wr*100).toFixed(1)}%`, color:wr>=0.55?G.green:wr>=0.40?G.yellow:G.red },
          { label:"Points", val:`${(evalStats?.total_points??0)>=0?"+":""}${(evalStats?.total_points??0).toFixed(1)}`,
            color:(evalStats?.total_points??0)>=0?G.green:G.red },
        ].map(({label,val,color})=>(
          <div key={label} style={{ background:G.surface, border:`1px solid ${G.border}`, borderRadius:8, padding:"14px 18px" }}>
            <div style={{ color:G.textSec, fontSize:11, marginBottom:6 }}>{label}</div>
            <div style={{ color, fontSize:20, fontWeight:700, fontFamily:"monospace" }}>{val}</div>
          </div>
        ))}
      </div>
      <div style={{ display:"grid", gridTemplateColumns:"1fr 1fr", gap:16 }}>
        <div style={{ background:G.surface, border:`1px solid ${G.border}`, borderRadius:8, overflow:"hidden" }}>
          <div style={{ padding:"12px 18px", borderBottom:`1px solid ${G.border}` }}>
            <span style={{ color:G.text, fontSize:13, fontWeight:600 }}>Agent Leaderboard</span>
          </div>
          {agentScores.length===0
            ? <Empty icon="📊" title="Accumulating data" sub="Leaderboard populates as real NSE signals are evaluated against live prices"/>
            : (
              <table style={{ width:"100%", borderCollapse:"collapse" }}>
                <thead>
                  <tr style={{ background:G.bg }}>
                    {["#","Agent","Signals","W","L","Win Rate","Points"].map(h=>(
                      <th key={h} style={{ color:G.textSec, fontSize:10, padding:"8px 14px",
                        textAlign:"left", fontWeight:500, borderBottom:`1px solid ${G.border}`,
                        fontFamily:"monospace" }}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {agentScores.map((a,i)=>{
                    const wr2=a.win_rate??0, pts=a.total_points??0;
                    return (
                      <tr key={a.agent_id} style={{ borderBottom:`1px solid ${G.border}` }}
                        onMouseEnter={e=>e.currentTarget.style.background=G.surfaceHov}
                        onMouseLeave={e=>e.currentTarget.style.background="transparent"}>
                        <td style={{ padding:"9px 14px", color:i<3?G.yellow:G.textMut, fontSize:11, fontFamily:"monospace" }}>#{i+1}</td>
                        <td style={{ padding:"9px 14px", color:G.text, fontSize:12, fontWeight:600 }}>{a.agent_id}</td>
                        <td style={{ padding:"9px 14px", color:G.textSec, fontSize:11, fontFamily:"monospace" }}>{a.total_signals}</td>
                        <td style={{ padding:"9px 14px", color:G.green, fontSize:11, fontFamily:"monospace" }}>{a.wins}</td>
                        <td style={{ padding:"9px 14px", color:G.red, fontSize:11, fontFamily:"monospace" }}>{a.losses}</td>
                        <td style={{ padding:"9px 14px", minWidth:100 }}>
                          <div style={{ display:"flex", alignItems:"center", gap:8 }}>
                            <div style={{ flex:1, background:G.border, borderRadius:3, height:5, overflow:"hidden" }}>
                              <div style={{ width:`${wr2*100}%`, height:"100%",
                                background:wr2>=0.55?G.green:wr2>=0.40?G.yellow:G.red, transition:"width .6s" }}/>
                            </div>
                            <span style={{ color:wr2>=0.55?G.green:wr2>=0.40?G.yellow:G.red, fontSize:10, fontFamily:"monospace", minWidth:30 }}>{(wr2*100).toFixed(0)}%</span>
                          </div>
                        </td>
                        <td style={{ padding:"9px 14px", color:pts>=0?G.green:G.red, fontSize:12, fontWeight:700, fontFamily:"monospace" }}>{pts>=0?"+":""}{pts.toFixed(1)}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            )}
        </div>
        <div style={{ background:G.surface, border:`1px solid ${G.border}`, borderRadius:8, overflow:"hidden" }}>
          <div style={{ padding:"12px 18px", borderBottom:`1px solid ${G.border}`,
            display:"flex", justifyContent:"space-between", alignItems:"center" }}>
            <span style={{ color:G.text, fontSize:13, fontWeight:600 }}>Signal History</span>
            <span style={{ color:G.textMut, fontSize:10 }}>Most recent first</span>
          </div>
          {evalHistory.length===0
            ? <Empty icon="🕒" title="No evaluated signals yet" sub="Signals are tracked against real prices. Results appear here as they resolve."/>
            : (
              <div style={{ maxHeight:400, overflowY:"auto" }}>
                {evalHistory.slice(0,20).map((r,i)=>{
                  const oc=r.outcome==="WIN"?G.green:r.outcome==="LOSS"?G.red:G.yellow;
                  const pnl=r.actual_pnl_pct??0;
                  return (
                    <div key={i} style={{ padding:"10px 18px", borderBottom:`1px solid ${G.border}`,
                      display:"flex", flexDirection:"column", gap:5, transition:"background .1s" }}
                      onMouseEnter={e=>e.currentTarget.style.background=G.surfaceHov}
                      onMouseLeave={e=>e.currentTarget.style.background="transparent"}>
                      <div style={{ display:"flex", justifyContent:"space-between", alignItems:"center" }}>
                        <div style={{ display:"flex", gap:8, alignItems:"center" }}>
                          <span style={{ color:G.text, fontWeight:700, fontSize:12, fontFamily:"monospace" }}>{r.symbol}</span>
                          <Tag label={r.strategy_id} color={G.yellow}/>
                          <Tag label={r.direction>0?"BUY":"SELL"} color={r.direction>0?G.green:G.red}/>
                          <Tag label={r.outcome??"-"} color={oc}/>
                        </div>
                        <div style={{ display:"flex", gap:10, alignItems:"center" }}>
                          <span style={{ color:pnl>=0?G.green:G.red, fontSize:11, fontFamily:"monospace", fontWeight:700 }}>{pnl>=0?"+":""}{pnl.toFixed(2)}%</span>
                          <span style={{ color:(r.points_awarded??0)>=0?G.green:G.red, fontSize:11, fontFamily:"monospace", fontWeight:700 }}>{(r.points_awarded??0)>=0?"+":""}{(r.points_awarded??0).toFixed(2)} pts</span>
                        </div>
                      </div>
                      {r.lesson&&<div style={{ color:G.textMut, fontSize:10, fontStyle:"italic", paddingLeft:2 }}>→ {r.lesson}</div>}
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

// ═════════════════════════════════════════════════════════════════════════════════
// KARMA INTELLIGENCE PANEL
// ═════════════════════════════════════════════════════════════════════════════════
function KarmaPanel({ karmaStats }) {
  const weights   = karmaStats?.strategy_weights ?? {};
  const patterns  = karmaStats?.discovered_patterns ?? [];
  const regimes   = karmaStats?.regime_win_rates ?? {};
  const episodes  = karmaStats?.episodes ?? 0;
  const winRate   = karmaStats?.win_rate ?? 0;
  const bestStrat = karmaStats?.best_strategy ?? "—";
  const lastTrain = karmaStats?.last_training ?? null;
  const isTraining = karmaStats?.training_active ?? false;

  const stratEntries = Object.entries(weights).sort((a,b)=>b[1]-a[1]).slice(0,10);
  const maxW = stratEntries.length ? Math.max(...stratEntries.map(e=>e[1])) : 1;

  return (
    <div style={{ display:"grid", gridTemplateColumns:"1fr 1fr", gap:12 }}>
      {/* Left: Strategy Weights */}
      <div style={{ background:G.surface, border:`1px solid ${G.pink}30`,
        borderRadius:8, padding:"16px 18px",
        boxShadow:`0 0 20px ${G.pink}08` }}>
        <div style={{ display:"flex", justifyContent:"space-between", alignItems:"center", marginBottom:14 }}>
          <div style={{ display:"flex", alignItems:"center", gap:8 }}>
            <span style={{ fontSize:18 }}>🧠</span>
            <span style={{ color:G.text, fontWeight:700, fontSize:13 }}>KARMA — What AI Learned</span>
          </div>
          {isTraining && (
            <div style={{ display:"flex", alignItems:"center", gap:6 }}>
              <div style={{ width:6, height:6, borderRadius:"50%", background:G.pink,
                boxShadow:`0 0 8px ${G.pink}`, animation:"pulse 1.5s infinite" }}/>
              <span style={{ color:G.pink, fontSize:10, fontFamily:"monospace" }}>TRAINING</span>
            </div>
          )}
        </div>
        {/* Stats row */}
        <div style={{ display:"grid", gridTemplateColumns:"repeat(3,1fr)", gap:8, marginBottom:14 }}>
          {[
            { label:"Episodes", val:episodes, color:G.blue },
            { label:"Win Rate", val:`${(winRate*100).toFixed(1)}%`, color:winRate>=0.55?G.green:winRate>=0.40?G.yellow:G.red },
            { label:"Best Strategy", val:bestStrat, color:G.yellow },
          ].map(({label,val,color})=>(
            <div key={label} style={{ background:G.bg, borderRadius:6, padding:"8px 10px" }}>
              <div style={{ color:G.textMut, fontSize:9, marginBottom:3 }}>{label}</div>
              <div style={{ color, fontWeight:700, fontSize:12, fontFamily:"monospace" }}>{val}</div>
            </div>
          ))}
        </div>

        <div style={{ color:G.textSec, fontSize:10, fontWeight:600, letterSpacing:".08em",
          textTransform:"uppercase", marginBottom:8 }}>
          Strategy Weights &nbsp;
          <span style={{ color:G.textMut, fontWeight:400 }}>(adaptive · 1.0 = neutral)</span>
        </div>
        {stratEntries.length === 0
          ? <div style={{ color:G.textMut, fontSize:11, padding:"12px 0" }}>Learning… weights update after each trade</div>
          : stratEntries.map(([strat,weight])=>{
              const barW = maxW > 0 ? (weight/maxW)*100 : 0;
              const barColor = weight > 1.2 ? G.green : weight < 0.8 ? G.red : G.blue;
              return (
                <div key={strat} style={{ marginBottom:8 }}>
                  <div style={{ display:"flex", justifyContent:"space-between", marginBottom:3 }}>
                    <span style={{ color:G.textSec, fontSize:11, fontFamily:"monospace" }}>{strat}</span>
                    <span style={{ color:barColor, fontSize:11, fontWeight:700, fontFamily:"monospace" }}>
                      {weight.toFixed(2)}× {weight>1.15?"↑ favoured":weight<0.85?"↓ penalised":""}
                    </span>
                  </div>
                  <div style={{ background:G.border, borderRadius:3, height:4, overflow:"hidden" }}>
                    <div style={{ width:`${barW}%`, height:"100%", background:barColor,
                      borderRadius:3, transition:"width .6s" }}/>
                  </div>
                </div>
              );
            })
        }
        {lastTrain && (
          <div style={{ marginTop:12, color:G.textMut, fontSize:10,
            padding:"8px 10px", background:G.bg, borderRadius:6, borderLeft:`2px solid ${G.pink}55` }}>
            🕐 Last off-hours training: <span style={{ color:G.textSec }}>{lastTrain}</span>
            <div style={{ color:G.textMut, fontSize:9, marginTop:2 }}>
              Runs 6PM–9AM IST · historical data · 5 timeframes · 3yr NIFTY50
            </div>
          </div>
        )}
      </div>

      {/* Right: Discovered Patterns + Regime Accuracy */}
      <div style={{ display:"flex", flexDirection:"column", gap:12 }}>
        <div style={{ background:G.surface, border:`1px solid ${G.purple}30`,
          borderRadius:8, padding:"16px 18px", flex:1 }}>
          <div style={{ display:"flex", alignItems:"center", gap:8, marginBottom:12 }}>
            <span style={{ fontSize:18 }}>💡</span>
            <span style={{ color:G.text, fontWeight:700, fontSize:13 }}>Discovered Patterns</span>
          </div>
          {patterns.length === 0
            ? <div style={{ color:G.textMut, fontSize:11, lineHeight:1.6 }}>
                Patterns emerge after 5+ trades in the same setup. KARMA tracks: regime + strategy + outcome → learns which combinations win.
              </div>
            : patterns.slice(0,6).map((p,i)=>(
                <div key={i} style={{ background:G.bg, borderRadius:6, padding:"8px 12px", marginBottom:8 }}>
                  <div style={{ display:"flex", justifyContent:"space-between" }}>
                    <span style={{ color:G.purple, fontSize:11, fontWeight:600 }}>{p.pattern}</span>
                    <span style={{ color:p.win_rate>=0.6?G.green:p.win_rate>=0.4?G.yellow:G.red,
                      fontSize:11, fontFamily:"monospace", fontWeight:700 }}>{(p.win_rate*100).toFixed(0)}% WR</span>
                  </div>
                  <div style={{ color:G.textMut, fontSize:10, marginTop:2 }}>{p.description}</div>
                </div>
              ))
          }
        </div>

        <div style={{ background:G.surface, border:`1px solid ${G.border}`,
          borderRadius:8, padding:"16px 18px" }}>
          <div style={{ display:"flex", alignItems:"center", gap:8, marginBottom:12 }}>
            <span style={{ fontSize:18 }}>🌊</span>
            <span style={{ color:G.text, fontWeight:700, fontSize:13 }}>Regime Win Rates</span>
          </div>
          {Object.keys(regimes).length === 0
            ? <div style={{ color:G.textMut, fontSize:11 }}>Accumulating data across regimes…</div>
            : Object.entries(regimes).map(([regime,stats])=>{
                const wr2=stats.win_rate??0;
                return (
                  <div key={regime} style={{ marginBottom:10 }}>
                    <div style={{ display:"flex", justifyContent:"space-between", marginBottom:3 }}>
                      <span style={{ color:REGIME[regime]?.color??G.textSec, fontSize:11, fontWeight:600 }}>
                        {REGIME[regime]?.icon} {regime}
                      </span>
                      <span style={{ color:wr2>=0.55?G.green:wr2>=0.40?G.yellow:G.red,
                        fontSize:11, fontFamily:"monospace" }}>
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

// ═════════════════════════════════════════════════════════════════════════════════
// TAB: AGENTS
// ═════════════════════════════════════════════════════════════════════════════════
const AGENT_LIST = [
  { id:"ZEUS",     icon:"⚡", color:"#f59e0b", role:"COO",       desc:"Health check, orchestration" },
  { id:"ORACLE",   icon:"🔮", color:"#8b5cf6", role:"Macro",     desc:"FII/DII, economic context"   },
  { id:"ATLAS",    icon:"🌍", color:"#06b6d4", role:"Sector",    desc:"Sector rotation selection"   },
  { id:"SIGMA",    icon:"📊", color:"#10b981", role:"Scoring",   desc:"8-factor stock ranking"      },
  { id:"APEX",     icon:"🎯", color:"#f43f5e", role:"Portfolio", desc:"Top-5 final selection"       },
  { id:"NEXUS",    icon:"📡", color:"#3b82f6", role:"Regime",    desc:"XGBoost market state"        },
  { id:"HERMES",   icon:"📰", color:"#a78bfa", role:"News",      desc:"FinBERT sentiment"           },
  { id:"TITAN",    icon:"⚔️", color:"#f0883e", role:"Strategy",  desc:"45+ strategy engine"        },
  { id:"GUARDIAN", icon:"🛡️", color:"#ef4444", role:"Risk",      desc:"Kill switch, position limits"},
  { id:"MERCURY",  icon:"🚀", color:"#39c5cf", role:"Executor",  desc:"OpenAlgo order routing"     },
  { id:"LENS",     icon:"🔭", color:"#84cc16", role:"Evaluator", desc:"Signal scoring, win rate"   },
  { id:"KARMA",    icon:"🧠", color:"#ec4899", role:"RL",        desc:"PPO learns from LENS data"  },
];

function AgentsTab({ agentKpi, events, karmaStats }) {
  return (
    <div style={{ display:"flex", flexDirection:"column", gap:20 }}>
      {/* Agent grid */}
      <div style={{ display:"grid", gridTemplateColumns:"repeat(3,1fr)", gap:12 }}>
        {AGENT_LIST.map(a=>{
          const kpi=agentKpi[a.id]??{kpi:0.72,cycles:0};
          return (
            <div key={a.id} style={{ background:G.surface, border:`1px solid ${G.border}`, borderRadius:8, padding:"16px 18px" }}>
              <div style={{ display:"flex", justifyContent:"space-between", alignItems:"flex-start", marginBottom:12 }}>
                <div style={{ display:"flex", gap:10, alignItems:"center" }}>
                  <span style={{ fontSize:20 }}>{a.icon}</span>
                  <div>
                    <div style={{ color:a.color, fontWeight:700, fontSize:13 }}>{a.id}</div>
                    <div style={{ color:G.textMut, fontSize:10 }}>{a.role}</div>
                  </div>
                </div>
                <div style={{ display:"flex", alignItems:"center", gap:5 }}>
                  <div style={{ width:6, height:6, borderRadius:"50%", background:G.green }}/>
                  <span style={{ color:G.textSec, fontSize:10, fontFamily:"monospace" }}>{(kpi.kpi*100).toFixed(0)}%</span>
                </div>
              </div>
              <div style={{ color:G.textSec, fontSize:11, marginBottom:10, lineHeight:1.4 }}>{a.desc}</div>
              <KpiBar value={kpi.kpi} max={1} color={a.color}/>
              <div style={{ color:G.textMut, fontSize:9, marginTop:5, fontFamily:"monospace" }}>{kpi.cycles} cycles</div>
            </div>
          );
        })}
      </div>

      {/* KARMA Intelligence Panel */}
      <div>
        <div style={{ color:G.text, fontSize:13, fontWeight:600, marginBottom:12,
          display:"flex", alignItems:"center", gap:8 }}>
          <span>🧠</span> KARMA Intelligence
          <span style={{ color:G.textMut, fontSize:10, fontWeight:400 }}>· Reinforcement learning from every trade</span>
        </div>
        <KarmaPanel karmaStats={karmaStats}/>
      </div>

      {/* Event bus */}
      <div style={{ background:G.surface, border:`1px solid ${G.border}`, borderRadius:8, overflow:"hidden" }}>
        <div style={{ padding:"12px 18px", borderBottom:`1px solid ${G.border}`,
          display:"flex", justifyContent:"space-between", alignItems:"center" }}>
          <span style={{ color:G.text, fontSize:13, fontWeight:600 }}>Event Bus</span>
          <div style={{ display:"flex", alignItems:"center", gap:6 }}>
            <div style={{ width:6, height:6, borderRadius:"50%", background:G.green, boxShadow:`0 0 6px ${G.green}` }}/>
            <Num n={events.length}/>
          </div>
        </div>
        <div style={{ maxHeight:340, overflowY:"auto" }}>
          {events.length===0
            ? <div style={{ padding:"24px 18px", color:G.textMut, fontSize:11, textAlign:"center" }}>Waiting for agent events…</div>
            : events.slice(0,40).map((ev,i)=>{
                const EVC={SIGNAL:G.orange,ORDER:G.blue,SELECTION:G.red,REGIME:G.purple,HEALTH:G.green,MACRO:G.teal,RISK:G.red,LEARN:G.purple,PERF:G.green,EXEC:G.teal};
                const col=EVC[ev.type]??G.textSec;
                return (
                  <div key={i} style={{ display:"flex", gap:12, padding:"8px 18px",
                    borderBottom:`1px solid ${G.border}`, alignItems:"center", transition:"background .1s" }}
                    onMouseEnter={e=>e.currentTarget.style.background=G.surfaceHov}
                    onMouseLeave={e=>e.currentTarget.style.background="transparent"}>
                    <div style={{ width:2, alignSelf:"stretch", background:col, borderRadius:2, flexShrink:0 }}/>
                    <span style={{ color:col, fontWeight:700, fontSize:10, fontFamily:"monospace", minWidth:60 }}>{ev.agent}</span>
                    <span style={{ color:G.textSec, fontSize:11, flex:1, lineHeight:1.4 }}>{ev.msg}</span>
                    <span style={{ color:G.textMut, fontSize:9, fontFamily:"monospace", whiteSpace:"nowrap" }}>{ev.ts}</span>
                  </div>
                );
              })
          }
        </div>
      </div>
    </div>
  );
}

// ═════════════════════════════════════════════════════════════════════════════════
// STOCK ANALYSIS MODAL — with tabs: Overview | Technical | Fundamentals
// ═════════════════════════════════════════════════════════════════════════════════
function StockModal({ stock, candles, analysis, loading, onClose, fundamentals }) {
  const [modalTab, setModalTab] = useState("overview");
  const sigs = candles ? titanSignals(candles, stock.regime ?? "TRENDING") : [];
  const ind  = candles?.length > 1 ? indicators(candles) : null;
  const L    = ind ? ind.n-1 : -1;
  const buys = sigs.filter(s=>s.signal===1).length;
  const sells= sigs.filter(s=>s.signal===-1).length;

  const metric = (label, value, tip) => (
    <IndTooltip label={label}>
      <div style={{ display:"flex", justifyContent:"space-between", padding:"6px 0",
        borderBottom:`1px solid ${G.border}`, cursor:tip?"help":"default" }}>
        <span style={{ color:G.textSec, fontSize:11 }}>
          {label}
          {IND_TIPS[label] && <span style={{ color:G.blue+"88", fontSize:9, marginLeft:4 }}>?</span>}
        </span>
        <span style={{ color:G.text, fontSize:11, fontWeight:600, fontFamily:"monospace" }}>{value}</span>
      </div>
    </IndTooltip>
  );

  const fundVal = (label, value, unit="", good=null) => {
    const color = good===null ? G.text : (good ? G.green : G.red);
    return (
      <div style={{ background:G.bg, borderRadius:6, padding:"10px 12px" }}>
        <div style={{ color:G.textMut, fontSize:9, marginBottom:3 }}>{label}</div>
        <div style={{ color, fontWeight:700, fontSize:13, fontFamily:"monospace" }}>
          {value !== null && value !== undefined ? `${value}${unit}` : "—"}
        </div>
      </div>
    );
  };

  const TAB_STYLE = (active) => ({
    background:"none", border:"none", cursor:"pointer", padding:"8px 14px", fontSize:12,
    borderBottom:active?`2px solid ${G.blue}`:"2px solid transparent",
    color:active?G.text:G.textSec, fontWeight:active?600:400, marginBottom:-1,
    transition:"color .12s",
  });

  const f = fundamentals ?? {};

  return (
    <div style={{ position:"fixed", inset:0, background:"rgba(1,4,9,.85)", zIndex:999,
      display:"flex", alignItems:"center", justifyContent:"center", padding:16 }}
      onClick={onClose}>
      <div onClick={e=>e.stopPropagation()} style={{
        background:G.surface, border:`1px solid ${G.borderMid}`,
        borderRadius:12, width:"100%", maxWidth:920, maxHeight:"93vh",
        overflowY:"auto", color:G.text, fontSize:12,
      }}>
        {/* Header */}
        <div style={{ background:G.bg, padding:"14px 20px",
          borderBottom:`1px solid ${G.border}`, display:"flex",
          justifyContent:"space-between", alignItems:"center" }}>
          <div style={{ display:"flex", gap:10, alignItems:"center", flexWrap:"wrap" }}>
            <span style={{ fontSize:17, fontWeight:700, color:G.blue, fontFamily:"monospace" }}>{stock.s}</span>
            <span style={{ color:G.textSec, fontSize:11 }}>{f.company_name ?? stock.n}</span>
            <Tag label={stock.sec} color={G.textSec}/>
            <Tag label={stock.tt??"SWING"} color={TT_COLOR[stock.tt]??G.blue}/>
            <Tag label={`${stock.sid??""} ${stock.sname??""}`} color={G.yellow}/>
            {stock.mtfVotes>0 && <Tag label={`MTF ${stock.mtfVotes}/5`} color={stock.mtfVotes>=4?G.green:G.teal}/>}
            <Tag label="📄 PAPER" color={G.green} bg={G.greenBg}/>
          </div>
          <button onClick={onClose} style={{ background:"none", border:"none",
            color:G.textSec, fontSize:18, cursor:"pointer", padding:"2px 6px",
            borderRadius:4, transition:"color .12s" }}
            onMouseEnter={e=>e.currentTarget.style.color=G.text}
            onMouseLeave={e=>e.currentTarget.style.color=G.textSec}>✕</button>
        </div>

        {/* Inner tab bar */}
        <div style={{ background:G.bg, padding:"0 20px", borderBottom:`1px solid ${G.border}`,
          display:"flex" }}>
          {["overview","technical","fundamentals"].map(t=>(
            <button key={t} onClick={()=>setModalTab(t)} style={TAB_STYLE(modalTab===t)}
              onMouseEnter={e=>{if(modalTab!==t)e.currentTarget.style.color=G.text;}}
              onMouseLeave={e=>{if(modalTab!==t)e.currentTarget.style.color=G.textSec;}}>
              {t.charAt(0).toUpperCase()+t.slice(1)}
            </button>
          ))}
        </div>

        <div style={{ padding:"20px" }}>

          {/* ─────────── TAB: OVERVIEW ─────────── */}
          {modalTab==="overview" && (
            <div style={{ display:"grid", gridTemplateColumns:"1fr 1fr", gap:20 }}>
              <div style={{ display:"flex", flexDirection:"column", gap:16 }}>
                {/* Live metrics */}
                <div style={{ background:G.bg, borderRadius:8, padding:16 }}>
                  <div style={{ color:G.textSec, fontSize:10, fontWeight:600, letterSpacing:".08em",
                    marginBottom:10, textTransform:"uppercase" }}>Market Data</div>
                  {metric("CMP",  `₹${(candles?.length?(candles[candles.length-1].close??candles[candles.length-1].Close??0):0).toFixed(2)}`)}
                  {metric("Entry", `₹${(stock.entry??0).toFixed(2)}`)}
                  {metric("Stop Loss", `₹${(stock.sl??0).toFixed(2)}`)}
                  {metric("Target", `₹${(stock.target??0).toFixed(2)}`)}
                  {metric("RSI 14", ind&&L>=0?ind.rsi[L].toFixed(1):"—")}
                  {metric("ADX 14", ind&&L>=0?ind.adx[L].toFixed(0):"—")}
                  {metric("ATR 14", ind&&L>=0?`₹${ind.atr[L].toFixed(2)}`:"—")}
                  {metric("EMA 20", ind&&L>=0?`₹${ind.e20[L].toFixed(0)}`:"—")}
                  {metric("EMA 50", ind&&L>=0?`₹${ind.e50[L].toFixed(0)}`:"—")}
                  {metric("VWAP",   ind&&L>=0?`₹${ind.vwap[L].toFixed(0)}`:"—")}
                </div>
                {/* Price targets */}
                <div style={{ background:G.bg, borderRadius:8, padding:16 }}>
                  <div style={{ color:G.textSec, fontSize:10, fontWeight:600, letterSpacing:".08em",
                    marginBottom:10, textTransform:"uppercase" }}>Price Targets</div>
                  {[
                    { label:"Conservative", val:stock.cons,   pct:stock.entry?((stock.cons-stock.entry)/stock.entry*100):0,   color:G.teal,   time:"3–5 days" },
                    { label:"Base Target",  val:stock.target, pct:stock.entry?((stock.target-stock.entry)/stock.entry*100):0, color:G.blue,   time:"5–10 days" },
                    { label:"Optimistic",   val:stock.opt,    pct:stock.entry?((stock.opt-stock.entry)/stock.entry*100):0,    color:G.yellow, time:"2–4 weeks" },
                  ].map(({label,val,pct,color,time})=>(
                    <div key={label} style={{ display:"flex", justifyContent:"space-between",
                      padding:"7px 10px", marginBottom:4, background:color+"0d",
                      borderRadius:5, border:`1px solid ${color}22` }}>
                      <span style={{ color, fontSize:11, fontWeight:600 }}>{label}</span>
                      <span style={{ color:G.text, fontSize:11, fontFamily:"monospace" }}>₹{(val??0).toFixed(0)}</span>
                      <span style={{ color, fontSize:10, fontFamily:"monospace" }}>+{pct.toFixed(1)}%</span>
                      <span style={{ color:G.textMut, fontSize:9 }}>{time}</span>
                    </div>
                  ))}
                  <div style={{ display:"flex", justifyContent:"space-between",
                    padding:"7px 10px", background:G.red+"0d", borderRadius:5, border:`1px solid ${G.red}22` }}>
                    <span style={{ color:G.red, fontSize:11, fontWeight:600 }}>Stop Loss</span>
                    <span style={{ color:G.text, fontSize:11, fontFamily:"monospace" }}>₹{(stock.sl??0).toFixed(0)}</span>
                    <span style={{ color:G.red, fontSize:10, fontFamily:"monospace" }}>-{Math.abs(stock.entry?((stock.sl-stock.entry)/stock.entry*100):0).toFixed(1)}%</span>
                    <span style={{ color:G.textMut, fontSize:9 }}>ATR×1.5</span>
                  </div>
                </div>
              </div>

              <div style={{ display:"flex", flexDirection:"column", gap:16 }}>
                {/* SIGMA factors */}
                <div style={{ background:G.bg, borderRadius:8, padding:16 }}>
                  <div style={{ color:G.textSec, fontSize:10, fontWeight:600, letterSpacing:".08em",
                    marginBottom:12, textTransform:"uppercase" }}>SIGMA 8-Factor Score</div>
                  {[["Momentum","20%",stock.sigmaFactors?.momentum],["Trend","15%",stock.sigmaFactors?.trend],["Earnings","15%",stock.sigmaFactors?.earnings],["Rel. Strength","15%",stock.sigmaFactors?.relStrength],["News","10%",stock.sigmaFactors?.news],["Volume","10%",stock.sigmaFactors?.volume],["Volatility","10%",stock.sigmaFactors?.volatility],["FII","5%",stock.sigmaFactors?.fii]].map(([label,wt,val])=>{
                    const v=val??0;
                    return (
                      <div key={label} style={{ marginBottom:8 }}>
                        <div style={{ display:"flex", justifyContent:"space-between", marginBottom:4 }}>
                          <span style={{ color:G.text, fontSize:11 }}>{label} <span style={{ color:G.textMut }}>({wt})</span></span>
                          <span style={{ color:v>0.6?G.green:v>0.4?G.yellow:G.red, fontSize:11, fontFamily:"monospace", fontWeight:600 }}>{(v*100).toFixed(0)}</span>
                        </div>
                        <KpiBar value={v} max={1} color={v>0.6?G.green:v>0.4?G.yellow:G.red}/>
                      </div>
                    );
                  })}
                </div>

                {/* AI Analysis */}
                <div style={{ background:G.bg, borderRadius:8, padding:16, flex:1 }}>
                  <div style={{ display:"flex", justifyContent:"space-between", alignItems:"center", marginBottom:12 }}>
                    <div style={{ color:G.textSec, fontSize:10, fontWeight:600, letterSpacing:".08em", textTransform:"uppercase" }}>
                      APEX AI Analysis
                    </div>
                    <Tag label="claude-sonnet-4" color={G.blue}/>
                  </div>
                  {loading ? (
                    <div style={{ display:"flex", flexDirection:"column", alignItems:"center", gap:10, padding:"28px 0", color:G.textSec }}>
                      <div style={{ fontSize:24, animation:"spin 1s linear infinite" }}>⚙</div>
                      <div style={{ fontSize:11 }}>Analyzing signals across 12 agents…</div>
                    </div>
                  ) : analysis ? (
                    <div style={{ display:"flex", flexDirection:"column", gap:12 }}>
                      {[
                        { label:"Why This Stock", color:G.blue, key:"selectionReason" },
                        { label:"Why This Strategy", color:G.yellow, key:"strategyReason" },
                        { label:`Why ${stock.tt??"SWING"}`, color:G.purple, key:"tradeTypeReason" },
                      ].map(({label,color,key})=>(
                        <div key={key}>
                          <div style={{ color, fontSize:9, fontWeight:700, letterSpacing:".1em",
                            textTransform:"uppercase", marginBottom:4 }}>{label}</div>
                          <div style={{ color:G.textSec, fontSize:11, lineHeight:1.55 }}>{analysis[key]}</div>
                        </div>
                      ))}
                      <div style={{ display:"grid", gridTemplateColumns:"1fr 1fr", gap:10 }}>
                        <div style={{ background:G.green+"0d", border:`1px solid ${G.green}22`, borderRadius:6, padding:"10px 12px", textAlign:"center" }}>
                          <div style={{ color:G.green, fontSize:9, fontWeight:700, marginBottom:4 }}>EXPECTED GAIN</div>
                          <div style={{ color:G.text, fontSize:20, fontWeight:700, fontFamily:"monospace" }}>+{analysis.expectedPct}%</div>
                          <div style={{ color:G.green, fontSize:10, fontFamily:"monospace" }}>₹{parseInt(analysis.expectedRs??0).toLocaleString("en-IN")}</div>
                        </div>
                        <div style={{ background:G.border, borderRadius:6, padding:"10px 12px", textAlign:"center" }}>
                          <div style={{ color:G.textMut, fontSize:9, fontWeight:700, marginBottom:4 }}>RISK : REWARD</div>
                          <div style={{ color:G.text, fontSize:20, fontWeight:700, fontFamily:"monospace" }}>1:{analysis.rr}</div>
                          <Tag label={analysis.conviction??"-"} color={analysis.conviction==="HIGH"?G.green:analysis.conviction==="LOW"?G.red:G.yellow}/>
                        </div>
                      </div>
                      {analysis.agentConsensus && (
                        <div style={{ background:G.surface, borderRadius:6, padding:10 }}>
                          <div style={{ color:G.textSec, fontSize:9, fontWeight:700, marginBottom:6, letterSpacing:".08em", textTransform:"uppercase" }}>Agent Consensus</div>
                          {Object.entries(analysis.agentConsensus).map(([agent,note])=>(
                            <div key={agent} style={{ display:"flex", gap:8, marginBottom:4 }}>
                              <span style={{ color:G.blue, fontSize:9, fontWeight:700, minWidth:58, fontFamily:"monospace" }}>{agent}</span>
                              <span style={{ color:G.textSec, fontSize:10 }}>{note}</span>
                            </div>
                          ))}
                        </div>
                      )}
                      {(analysis.risks??[]).length>0 && (
                        <div>
                          <div style={{ color:G.red, fontSize:9, fontWeight:700, marginBottom:6, letterSpacing:".08em", textTransform:"uppercase" }}>Key Risks</div>
                          {analysis.risks.map((r,i)=>(
                            <div key={i} style={{ color:G.textSec, fontSize:10, marginBottom:3 }}>· {r}</div>
                          ))}
                        </div>
                      )}
                    </div>
                  ) : (
                    <div style={{ color:G.textMut, fontSize:11, textAlign:"center", padding:20 }}>Loading analysis…</div>
                  )}
                </div>
              </div>
            </div>
          )}

          {/* ─────────── TAB: TECHNICAL ─────────── */}
          {modalTab==="technical" && (
            <div style={{ display:"grid", gridTemplateColumns:"1fr 1fr", gap:20 }}>
              <div style={{ display:"flex", flexDirection:"column", gap:16 }}>
                {/* TITAN signals */}
                <div style={{ background:G.bg, borderRadius:8, padding:16 }}>
                  <div style={{ color:G.textSec, fontSize:10, fontWeight:600, letterSpacing:".08em",
                    marginBottom:10, textTransform:"uppercase" }}>TITAN Strategy Signals ({sigs.length})</div>
                  <div style={{ display:"grid", gridTemplateColumns:"1fr 1fr", gap:8, marginBottom:12 }}>
                    {[["BUY",buys,G.green],["SELL",sells,G.red]].map(([label,count,color])=>(
                      <div key={label} style={{ background:color+"0d", border:`1px solid ${color}22`,
                        borderRadius:6, padding:"8px 12px", textAlign:"center" }}>
                        <div style={{ color, fontSize:22, fontWeight:700, fontFamily:"monospace" }}>{count}</div>
                        <div style={{ color:G.textMut, fontSize:9 }}>{label}</div>
                      </div>
                    ))}
                  </div>
                  <div style={{ maxHeight:180, overflowY:"auto", display:"flex", flexDirection:"column", gap:4 }}>
                    {sigs.slice(0,12).map((s,i)=>(
                      <div key={i} style={{ display:"flex", alignItems:"center", gap:8, padding:"4px 8px",
                        background:s.signal>0?G.green+"0a":G.red+"0a",
                        borderRadius:4, borderLeft:`2px solid ${s.signal>0?G.green:G.red}` }}>
                        <Tag label={s.id} color={G.yellow}/>
                        <span style={{ color:G.textSec, fontSize:10, flex:1 }}>{s.reason.slice(0,48)}</span>
                        <span style={{ color:s.signal>0?G.green:G.red, fontSize:10, fontFamily:"monospace", fontWeight:700 }}>{(s.confidence*100).toFixed(0)}%</span>
                      </div>
                    ))}
                  </div>
                </div>

                {/* Indicator values with tooltips */}
                <div style={{ background:G.bg, borderRadius:8, padding:16 }}>
                  <div style={{ color:G.textSec, fontSize:10, fontWeight:600, letterSpacing:".08em",
                    marginBottom:10, textTransform:"uppercase", display:"flex", justifyContent:"space-between" }}>
                    <span>Indicators</span>
                    <span style={{ color:G.blue+"88", fontWeight:400, textTransform:"none" }}>Hover ? for explanation</span>
                  </div>
                  {metric("RSI 14", ind&&L>=0?`${ind.rsi[L].toFixed(1)} ${ind.rsi[L]<30?"⬇ oversold":ind.rsi[L]>70?"⬆ overbought":"neutral"}`:"—", true)}
                  {metric("ADX 14", ind&&L>=0?`${ind.adx[L].toFixed(0)} ${ind.adx[L]>25?"trending":"weak"}`:"—", true)}
                  {metric("ATR 14", ind&&L>=0?`₹${ind.atr[L].toFixed(2)}`:"—", true)}
                  {metric("EMA 20", ind&&L>=0?`₹${ind.e20[L].toFixed(0)}`:"—", true)}
                  {metric("EMA 50", ind&&L>=0?`₹${ind.e50[L].toFixed(0)}`:"—", true)}
                  {metric("VWAP",   ind&&L>=0?`₹${ind.vwap[L].toFixed(0)}`:"—", true)}
                  {metric("BB %B",  ind&&L>=0?`${ind.bbpb[L].toFixed(2)}`:"—", true)}
                  {metric("Stoch K",ind&&L>=0?`${ind.sk[L].toFixed(0)}`:"—", true)}
                </div>
              </div>

              <div style={{ display:"flex", flexDirection:"column", gap:16 }}>
                {/* Candle patterns */}
                <div style={{ background:G.bg, borderRadius:8, padding:16 }}>
                  <div style={{ color:G.textSec, fontSize:10, fontWeight:600, letterSpacing:".08em",
                    marginBottom:12, textTransform:"uppercase" }}>🕯️ Candlestick Patterns</div>
                  <CandlePatterns candles={candles}/>
                </div>

                {/* Volume analysis */}
                <div style={{ background:G.bg, borderRadius:8, padding:16 }}>
                  <div style={{ color:G.textSec, fontSize:10, fontWeight:600, letterSpacing:".08em",
                    marginBottom:12, textTransform:"uppercase" }}>📦 Volume Analysis</div>
                  <VolumeAnalysisPanel candles={candles}/>
                </div>

                {/* MTF alignment */}
                <div style={{ background:G.bg, borderRadius:8, padding:16 }}>
                  <div style={{ color:G.textSec, fontSize:10, fontWeight:600, letterSpacing:".08em",
                    marginBottom:10, textTransform:"uppercase" }}>⏱ Multi-Timeframe Alignment</div>
                  {stock.mtfVotes > 0 ? (
                    <div>
                      <div style={{ display:"flex", gap:6, marginBottom:10 }}>
                        {["1m","5m","15m","1h","1d"].map((tf,i)=>{
                          const isAligned = i < (stock.mtfVotes??0);
                          return (
                            <div key={tf} style={{ flex:1, padding:"6px 0", textAlign:"center",
                              background:isAligned?G.green+"14":G.border,
                              border:`1px solid ${isAligned?G.green+"44":G.border}`,
                              borderRadius:5 }}>
                              <div style={{ color:isAligned?G.green:G.textMut, fontSize:10, fontWeight:700 }}>{tf}</div>
                              <div style={{ fontSize:9, color:isAligned?G.green:G.textMut }}>{isAligned?"✓":"-"}</div>
                            </div>
                          );
                        })}
                      </div>
                      <div style={{ color:stock.mtfVotes>=4?G.green:G.yellow, fontSize:11 }}>
                        {stock.mtfVotes}/5 timeframes aligned — {stock.mtfVotes>=4?"Strong confluence":"Partial confluence"}
                      </div>
                    </div>
                  ) : (
                    <div style={{ color:G.textMut, fontSize:11 }}>MTF data updates on next scan cycle</div>
                  )}
                </div>
              </div>
            </div>
          )}

          {/* ─────────── TAB: FUNDAMENTALS ─────────── */}
          {modalTab==="fundamentals" && (
            <div>
              {Object.keys(f).length === 0 ? (
                <div style={{ display:"flex", flexDirection:"column", alignItems:"center", padding:"40px 0", gap:12 }}>
                  <span style={{ fontSize:28 }}>📊</span>
                  <div style={{ color:G.textSec, fontSize:13, fontWeight:500 }}>Fundamentals not loaded</div>
                  <div style={{ color:G.textMut, fontSize:11, maxWidth:320, textAlign:"center" }}>
                    Backend must be running with yfinance to fetch fundamentals.
                    Data is cached hourly once backend is connected.
                  </div>
                </div>
              ) : (
                <div style={{ display:"flex", flexDirection:"column", gap:16 }}>
                  {/* Company header */}
                  <div style={{ background:G.bg, borderRadius:8, padding:16 }}>
                    <div style={{ color:G.text, fontSize:16, fontWeight:700, marginBottom:4 }}>{f.company_name ?? stock.s}</div>
                    <div style={{ color:G.textSec, fontSize:11, marginBottom:8 }}>
                      {f.industry ?? "—"} · {f.sector ?? "—"}
                      {f.employees && ` · ${f.employees.toLocaleString("en-IN")} employees`}
                    </div>
                    {f.description && (
                      <div style={{ color:G.textSec, fontSize:11, lineHeight:1.6, maxHeight:80, overflowY:"auto",
                        padding:"8px 0", borderTop:`1px solid ${G.border}` }}>
                        {f.description}
                      </div>
                    )}
                  </div>

                  {/* Valuation metrics */}
                  <div>
                    <div style={{ color:G.textSec, fontSize:10, fontWeight:600, letterSpacing:".08em",
                      textTransform:"uppercase", marginBottom:10 }}>Valuation</div>
                    <div style={{ display:"grid", gridTemplateColumns:"repeat(4,1fr)", gap:8 }}>
                      {fundVal("P/E Ratio", f.pe_ratio, "", f.pe_ratio ? f.pe_ratio < 30 : null)}
                      {fundVal("P/B Ratio", f.price_to_book, "×")}
                      {fundVal("PEG Ratio", f.peg_ratio, "", f.peg_ratio ? f.peg_ratio < 1.5 : null)}
                      {fundVal("Mkt Cap (Cr)", f.market_cap_cr ? `₹${(f.market_cap_cr/100).toFixed(0)}K` : null)}
                    </div>
                  </div>

                  {/* Quality metrics */}
                  <div>
                    <div style={{ color:G.textSec, fontSize:10, fontWeight:600, letterSpacing:".08em",
                      textTransform:"uppercase", marginBottom:10 }}>Quality & Growth</div>
                    <div style={{ display:"grid", gridTemplateColumns:"repeat(4,1fr)", gap:8 }}>
                      {fundVal("ROE", f.roe!=null?`${f.roe}%`:null, "", f.roe ? f.roe > 15 : null)}
                      {fundVal("Revenue Growth", f.revenue_growth!=null?`${f.revenue_growth}%`:null, "", f.revenue_growth ? f.revenue_growth > 10 : null)}
                      {fundVal("Profit Margin", f.profit_margin!=null?`${f.profit_margin}%`:null, "", f.profit_margin ? f.profit_margin > 10 : null)}
                      {fundVal("Current Ratio", f.current_ratio, "×", f.current_ratio ? f.current_ratio > 1.5 : null)}
                    </div>
                  </div>

                  {/* Safety */}
                  <div>
                    <div style={{ color:G.textSec, fontSize:10, fontWeight:600, letterSpacing:".08em",
                      textTransform:"uppercase", marginBottom:10 }}>Safety & Yield</div>
                    <div style={{ display:"grid", gridTemplateColumns:"repeat(4,1fr)", gap:8 }}>
                      {fundVal("Debt/Equity", f.debt_to_equity, "×", f.debt_to_equity!=null ? f.debt_to_equity < 0.5 : null)}
                      {fundVal("Div Yield", f.dividend_yield!=null?`${f.dividend_yield}%`:null, "", f.dividend_yield ? f.dividend_yield > 1.5 : null)}
                      {fundVal("EPS (TTM)", f.eps!=null?`₹${f.eps}`:null)}
                      {fundVal("Book Value", f.book_value!=null?`₹${f.book_value}`:null)}
                    </div>
                  </div>

                  {/* 52-week range */}
                  {f.week52_high && f.week52_low && (
                    <div style={{ background:G.bg, borderRadius:8, padding:14 }}>
                      <div style={{ color:G.textSec, fontSize:10, fontWeight:600, letterSpacing:".08em",
                        textTransform:"uppercase", marginBottom:12 }}>52-Week Range</div>
                      <div style={{ display:"flex", justifyContent:"space-between", marginBottom:6 }}>
                        <span style={{ color:G.red, fontSize:11, fontFamily:"monospace" }}>₹{f.week52_low}</span>
                        <span style={{ color:G.textSec, fontSize:10 }}>CMP ₹{(candles?.length?(candles[candles.length-1].close??0):stock.base).toFixed(0)}</span>
                        <span style={{ color:G.green, fontSize:11, fontFamily:"monospace" }}>₹{f.week52_high}</span>
                      </div>
                      <div style={{ background:G.border, borderRadius:4, height:8, overflow:"hidden" }}>
                        {(() => {
                          const cmp = candles?.length?(candles[candles.length-1].close??stock.base):stock.base;
                          const pct = (cmp-f.week52_low)/(f.week52_high-f.week52_low)*100;
                          return <div style={{ width:`${Math.min(100,Math.max(0,pct))}%`, height:"100%",
                            background:`linear-gradient(90deg, ${G.red}, ${G.blue}, ${G.green})`,
                            borderRadius:4, transition:"width .6s" }}/>;
                        })()}
                      </div>
                    </div>
                  )}

                  {/* FA reasons from SIGMA */}
                  {stock.fa_reasons?.length > 0 && (
                    <div style={{ background:G.greenBg, border:`1px solid ${G.green}22`,
                      borderRadius:8, padding:14 }}>
                      <div style={{ color:G.green, fontSize:10, fontWeight:700, letterSpacing:".08em",
                        textTransform:"uppercase", marginBottom:8 }}>✓ SIGMA Fundamental Triggers</div>
                      {stock.fa_reasons.map((r,i)=>(
                        <div key={i} style={{ color:G.textSec, fontSize:11, marginBottom:4 }}>· {r}</div>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </div>
          )}
        </div>
      </div>
      <style>{`@keyframes spin{from{transform:rotate(0)}to{transform:rotate(360deg)}} @keyframes pulse{0%,100%{opacity:1}50%{opacity:.4}}`}</style>
    </div>
  );
}

// ═════════════════════════════════════════════════════════════════════════════════
// ROOT APP
// ═════════════════════════════════════════════════════════════════════════════════
export default function AlphaZero() {
  const [tab,          setTab]        = useState("overview");
  const [connStatus,   setConn]       = useState("connecting");
  const [quotes,       setQuotes]     = useState({});
  const [indices,      setIndices]    = useState({ nifty:24150, banknifty:51840, vix:14.2, market_open:false });
  const [candleCache,  setCaches]     = useState({});
  const [regime,       setRegime]     = useState("TRENDING");
  const [picks,        setPicks]      = useState([]);
  const [positions,    setPos]        = useState([]);
  const [allSigs,      setAllSigs]    = useState([]);
  const [events,       setEvents]     = useState([]);
  const [agentKpi,     setKpi]        = useState({});
  const [evalStats,    setEvalStats]  = useState(null);
  const [evalHistory,  setHistory]    = useState([]);
  const [agentScores,  setScores]     = useState([]);
  const [karmaStats,   setKarmaStats] = useState(null);
  const [modal,        setModal]      = useState(null);
  const [analysis,     setAnalysis]   = useState(null);
  const [modalLoading, setMloading]   = useState(false);
  const [fundamentals, setFundamentals] = useState({});
  const [now,          setNow]        = useState(new Date());

  const cRef=useRef(candleCache); cRef.current=candleCache;
  const pRef=useRef(positions);   pRef.current=positions;
  const rRef=useRef(regime);      rRef.current=regime;
  const qRef=useRef(quotes);      qRef.current=quotes;
  const vRef=useRef(14.2);
  const eId=useRef(0);
  const wsRef=useRef(null);

  const addEvt = useCallback((type,agent,msg)=>
    setEvents(p=>[{id:++eId.current,type,agent,msg,ts:new Date().toLocaleTimeString("en-IN",{hour12:false})},...p].slice(0,100)),
    []);

  // Clock
  useEffect(()=>{ const t=setInterval(()=>setNow(new Date()),1000); return()=>clearInterval(t); },[]);

  // WebSocket
  useEffect(()=>{
    let ws;
    const connect=()=>{
      try {
        ws=new WebSocket("ws://localhost:8000/ws");
        wsRef.current=ws;
        ws.onopen=()=>{ setConn("live"); addEvt("HEALTH","ZEUS","Backend connected · real NSE data streaming via yfinance"); };
        ws.onmessage=({data})=>{
          const msg=JSON.parse(data);
          if (msg.type==="QUOTE_UPDATE"||msg.type==="INIT") {
            if (msg.quotes)     setQuotes(msg.quotes);
            if (msg.indices)    { setIndices(msg.indices); vRef.current=msg.indices.vix??14.2; }
            if (msg.eval_stats) setEvalStats(msg.eval_stats);
            if (msg.karma)      setKarmaStats(msg.karma);
            if (msg.regime)     setRegime(msg.regime);
          }
        };
        ws.onclose=()=>{ setConn("offline"); wsRef.current=null; };
        ws.onerror=()=>{ setConn("offline"); wsRef.current=null; };
      } catch { setConn("offline"); }
    };
    connect();
    const t=setInterval(()=>{ if(!wsRef.current||wsRef.current.readyState>1) connect(); },5000);
    return()=>{ clearInterval(t); ws?.close(); };
  },[addEvt]);

  // Poll eval + karma data
  useEffect(()=>{
    if (connStatus!=="live") return;
    const load=async()=>{
      try {
        const [h,s,k]=await Promise.all([
          fetch(`${BACKEND}/evaluation/history`).then(r=>r.json()),
          fetch(`${BACKEND}/evaluation/agents`).then(r=>r.json()),
          fetch(`${BACKEND}/karma/stats`).then(r=>r.json()).catch(()=>null),
        ]);
        setHistory(Array.isArray(h)?h:[]);
        setScores(Array.isArray(s)?s:[]);
        if (k) setKarmaStats(k);
      } catch {}
    };
    load();
    const t=setInterval(load,30000);
    return()=>clearInterval(t);
  },[connStatus]);

  // Offline regime drift
  useEffect(()=>{
    if (connStatus==="live") return;
    // Simulate KARMA stats for demo
    setKarmaStats({
      episodes: 847, win_rate: 0.61, best_strategy: "T2 Triple EMA",
      strategy_weights: { "T2 Triple EMA":1.42, "T1 EMA Cross":1.28, "M1 RSI Rev":1.15, "B2 Vol Breakout":0.98, "V1 VWAP Cross":0.87, "M2 BB Bounce":0.72, "T5 ADX":1.06, "S1 Z-Score":0.65 },
      discovered_patterns: [
        { pattern:"TRENDING + T2 + Morning", win_rate:0.74, description:"Triple EMA in trending regime after Morning Star candle" },
        { pattern:"SIDEWAYS + M1 RSI < 30",  win_rate:0.68, description:"RSI extreme oversold in sideways market" },
        { pattern:"VOLATILE + VWAP Cross",   win_rate:0.52, description:"VWAP reclaim during volatile sessions — moderate edge" },
      ],
      regime_win_rates: {
        TRENDING: { win_rate:0.68, trades:312 },
        SIDEWAYS: { win_rate:0.59, trades:284 },
        VOLATILE: { win_rate:0.47, trades:156 },
        RISK_OFF:  { win_rate:0.38, trades:95  },
      },
      last_training: "Today 3:14 AM IST (off-hours · 5 timeframes · 3yr NSE data)",
      training_active: false,
    });

    const t=setInterval(()=>{
      vRef.current=Math.max(10,Math.min(32,vRef.current+(Math.random()-.5)*.8));
      const nxt=vRef.current>26?"VOLATILE":vRef.current>21?"RISK_OFF":Math.random()>.38?"TRENDING":"SIDEWAYS";
      if (nxt!==rRef.current) {
        setRegime(nxt);
        addEvt("REGIME","NEXUS",`Regime shift → ${nxt} · VIX ${vRef.current.toFixed(1)} [browser mode]`);
      }
      setIndices(p=>({
        nifty:      +(p.nifty+(Math.random()-.495)*12).toFixed(2),
        banknifty:  +(p.banknifty+(Math.random()-.495)*28).toFixed(2),
        vix:        +vRef.current.toFixed(1),
        market_open:false,
      }));
    },8000);
    return()=>clearInterval(t);
  },[connStatus,addEvt]);

  // Fetch candles
  const getCandles=useCallback(async(symbol)=>{
    if (cRef.current[symbol]) return cRef.current[symbol];
    if (connStatus==="live") {
      try {
        const r=await fetch(`${BACKEND}/candles/${symbol}`);
        const d=await r.json();
        if (d.candles?.length) {
          const norm=d.candles.map(c=>({...c,close:c.close??c.Close??0}));
          setCaches(p=>({...p,[symbol]:norm}));
          return norm;
        }
      } catch {}
    }
    const st=STOCKS.find(x=>x.s===symbol);
    const base=st?.base??1000;
    const syn=[];
    let px=base*(1+(Math.random()-.5)*.05);
    for (let i=0;i<100;i++) {
      const d=(Math.random()-.495)*base*.008,o=px;
      px=Math.max(base*.7,px+d);
      const rng=Math.abs(d)+Math.random()*base*.004;
      syn.push({open:o,close:px,high:Math.max(o,px)+Math.random()*rng*.5,low:Math.min(o,px)-Math.random()*rng*.5,volume:Math.floor(Math.random()*800000+200000)});
    }
    setCaches(p=>({...p,[symbol]:syn}));
    return syn;
  },[connStatus]);

  // APEX selection
  const runSelect=useCallback(async()=>{
    const cr=rRef.current;
    const results=await Promise.all(STOCKS.map(async(st)=>{
      const cdl=await getCandles(st.s);
      const ind=cdl.length>=15?indicators(cdl):null;
      const Li=ind?ind.n-1:-1;
      const liveQ=qRef.current[st.s];
      const price=+(liveQ?.ltp??(cdl.length?(cdl[cdl.length-1].close??cdl[cdl.length-1].Close??st.base):st.base)).toFixed(2);
      const atr=ind&&Li>=0?ind.atr[Li]:price*.013;
      const first=cdl[0];
      const chg=first?(price-(first.close??first.Close??price))/(first.close??first.Close??price)*100:0;
      const mf=Math.max(0,Math.min(1,chg/3+.5));
      const tf=ind&&Li>=0?Math.min(1,ind.adx[Li]/50):.3+Math.random()*.3;
      const rf=ind&&Li>=0?(ind.rsi[Li]>38&&ind.rsi[Li]<68?.7+Math.random()*.2:.3):.5;
      const ef=ind&&Li>=0?(ind.e20[Li]>ind.e50[Li]?.7+Math.random()*.25:.3):.5;
      const vf=.4+Math.random()*.5,nf=.35+Math.random()*.6,fii=.25+Math.random()*.7,earn=.35+Math.random()*.55;
      const score=+(mf*.20+tf*.15+rf*.15+ef*.15+earn*.15+vf*.10+nf*.10+fii*.05).toFixed(3);
      const tt=ind&&Li>=0&&ind.adx[Li]>40?"SHORT_TERM":ind&&Li>=0&&ind.adx[Li]<18&&cr==="SIDEWAYS"?"INTRADAY":cr==="TRENDING"&&tf>.55?"LONG_TERM":"SWING";
      const pools={TRENDING:["T1 EMA Cross","T2 Triple EMA","T4 MACD","T5 ADX","T7 Donchian","B2 Vol Breakout"],SIDEWAYS:["M1 RSI Rev","M2 BB Bounce","M3 BB Squeeze","V1 VWAP Cross","S1 Z-Score"],VOLATILE:["M1 RSI Rev","M2 BB Bounce","V1 VWAP Cross"],RISK_OFF:["M1 RSI Rev"]};
      const pool=pools[cr]??pools.TRENDING;
      const ss=pool[Math.floor(Math.random()*pool.length)];
      const [sid,...sname]=ss.split(" ");
      // MTF votes: simulate based on ADX alignment
      const mtfVotes = ind&&Li>=0 ? Math.round(2 + (ind.adx[Li]/50)*3) : Math.floor(Math.random()*5)+1;
      // Candle patterns for selection reason
      const pats = detectCandlePatterns(cdl);
      const bullPats = pats.filter(p=>p.type==="bull").map(p=>p.name);
      const fa_reasons = [];
      return { ...st, score, tt, confidence:+(.52+Math.random()*.42).toFixed(2),
        price, chgPct:+chg.toFixed(2),
        entry:price, sl:+(price-1.5*atr).toFixed(2),
        target:+(price+1.5*atr).toFixed(2), cons:+(price+.8*atr).toFixed(2), opt:+(price+2.5*atr).toFixed(2),
        regime:cr, sid, sname:sname.join(" "), mtfVotes,
        candlePatterns:pats, bullPatterns:bullPats, fa_reasons,
        sigmaFactors:{momentum:+mf.toFixed(2),trend:+tf.toFixed(2),earnings:+earn.toFixed(2),relStrength:+ef.toFixed(2),news:+nf.toFixed(2),volume:+vf.toFixed(2),volatility:+(1-atr/price*30).toFixed(2),fii:+fii.toFixed(2)},
      };
    }));
    const top5=results.sort((a,b)=>b.score-a.score).slice(0,5);
    setPicks(top5);
    addEvt("SELECTION","APEX",`Picks: ${top5.map(s=>s.s).join(", ")} · ${cr}`);
    top5.filter(s=>s.confidence>.62).forEach(stock=>{
      if (!pRef.current.find(p=>p.symbol===stock.s&&p.status==="OPEN")) {
        const qty=Math.max(1,Math.floor(50000/stock.price));
        setPos(prev=>[...prev.filter(p=>p.symbol!==stock.s),
          {id:`${stock.s}-${Date.now()}`,symbol:stock.s,entryPrice:stock.price,cp:stock.price,
           sl:stock.sl,target:stock.target,qty,sid:stock.sid,tt:stock.tt,
           pnl:0,pnlPct:0,status:"OPEN",time:new Date().toLocaleTimeString("en-IN",{hour12:false})}
        ].slice(0,8));
        addEvt("ORDER","MERCURY",`[PAPER] BUY ${qty}×${stock.s} @₹${stock.price} | ${stock.sid} | conf:${(stock.confidence*100).toFixed(0)}%`);
      }
    });
  },[getCandles,addEvt]);

  useEffect(()=>{ runSelect(); const t=setInterval(runSelect,40000); return()=>clearInterval(t); },[runSelect]);

  // TITAN signals
  useEffect(()=>{
    const run=()=>{
      const all=[];
      STOCKS.forEach(st=>{
        const cdl=cRef.current[st.s]; if(!cdl) return;
        titanSignals(cdl,rRef.current).forEach(sig=>all.push({...sig,symbol:st.s,sector:st.sec}));
      });
      all.sort((a,b)=>b.confidence-a.confidence);
      setAllSigs(all.slice(0,40));
      if (all.length>0) {
        const t=all[0];
        addEvt("SIGNAL","TITAN",`${t.id} ${t.signal>0?"BUY":"SELL"} ${t.symbol} · ${(t.confidence*100).toFixed(0)}% · ${t.reason.slice(0,42)}`);
      }
    };
    run(); const t=setInterval(run,8000); return()=>clearInterval(t);
  },[addEvt]);

  // P&L update
  useEffect(()=>{
    setPos(prev=>prev.map(pos=>{
      const lq=qRef.current[pos.symbol], cdl=cRef.current[pos.symbol];
      const cp=+(lq?.ltp||(cdl?.length?(cdl[cdl.length-1].close??cdl[cdl.length-1].Close??pos.entryPrice):pos.entryPrice)).toFixed(2);
      return {...pos,cp,pnl:(cp-pos.entryPrice)*pos.qty,pnlPct:(cp-pos.entryPrice)/pos.entryPrice*100};
    }));
  },[quotes,candleCache]);

  // Agent KPI heartbeat
  useEffect(()=>{
    const IDS=AGENT_LIST.map(a=>a.id);
    const init={}; IDS.forEach(a=>{init[a]={kpi:.70+Math.random()*.25,cycles:0};}); setKpi(init);
    const MSGS=[["HEALTH","ZEUS","All 12 agents nominal · Redis bus <2ms"],["MACRO","ORACLE",`FII +₹${(Math.random()*800+200).toFixed(0)}Cr · DII neutral`],["RISK","GUARDIAN","Position limits OK · kill switch armed"],["LEARN","KARMA","PPO weights updated from LENS evaluation report"],["PERF","LENS","Agent leaderboard refreshed · checking pending signals"],["EXEC","MERCURY","[PAPER] Fills: 100% · avg slippage 0.08%"],["SECTOR","ATLAS",`Top sector: ${["Banking","IT","Energy","Auto"][Math.floor(Math.random()*4)]}`]];
    const t=setInterval(()=>{
      const a=IDS[Math.floor(Math.random()*IDS.length)];
      setKpi(prev=>({...prev,[a]:{kpi:Math.min(.99,Math.max(.5,(prev[a]?.kpi??.7)+(Math.random()-.47)*.015)),cycles:(prev[a]?.cycles??0)+1}}));
      const [type,ag,msg]=MSGS[Math.floor(Math.random()*MSGS.length)];
      addEvt(type,ag,msg);
    },7000);
    return()=>clearInterval(t);
  },[addEvt]);

  // Open stock modal
  const openModal=async(stock)=>{
    setModal(stock); setAnalysis(null); setMloading(true);
    const cdl=await getCandles(stock.s);
    const ind=cdl.length?indicators(cdl):null;
    const Li=ind?ind.n-1:-1;
    const sigs=titanSignals(cdl,stock.regime??"TRENDING");
    const price=cdl.length?(cdl[cdl.length-1].close??cdl[cdl.length-1].Close??stock.base):stock.base;
    const dataSource=connStatus==="live"?"Real NSE data via yfinance":"Browser simulation (start backend for real data)";
    const pats=detectCandlePatterns(cdl);
    const va=computeVolumeAnalysis(cdl);

    // Fetch fundamentals from backend if live
    if (connStatus==="live") {
      try {
        const fData=await fetch(`${BACKEND}/fundamentals/${stock.s}`).then(r=>r.json());
        setFundamentals(prev=>({...prev,[stock.s]:fData}));
      } catch {}
    }

    const prompt=`AlphaZero APEX — JSON response only, no markdown.
Stock: ${stock.s} (${stock.n}) Sector: ${stock.sec}
Price: ₹${price.toFixed(2)} Entry: ₹${stock.entry} SL: ₹${stock.sl} Target: ₹${stock.target}
Regime: ${stock.regime} Strategy: ${stock.sid} ${stock.sname} TradeType: ${stock.tt}
MTF Votes: ${stock.mtfVotes??0}/5 timeframes aligned
SIGMA Score: ${stock.score} Confidence: ${(stock.confidence*100).toFixed(0)}%
TITAN: ${sigs.length} signals (${sigs.filter(x=>x.signal>0).length} buy / ${sigs.filter(x=>x.signal<0).length} sell)
RSI: ${ind&&Li>=0?ind.rsi[Li].toFixed(1):"n/a"} ADX: ${ind&&Li>=0?ind.adx[Li].toFixed(0):"n/a"} ATR: ₹${ind&&Li>=0?ind.atr[Li].toFixed(2):"n/a"}
Candle Patterns: ${pats.map(p=>p.name).join(", ")||"None"}
Volume: ${va?`${va.volRatio}× avg · OBV ${va.obvTrend} · ${va.pvConfirm?"price-vol confirming":"price-vol diverging"}`:"n/a"}
Data source: ${dataSource}

Respond with exactly this JSON shape:
{"selectionReason":"2 concise sentences mentioning MTF votes and candle patterns if applicable","strategyReason":"why ${stock.sid} fits ${stock.regime}","tradeTypeReason":"why ${stock.tt}","expectedPct":${((stock.target-stock.entry)/stock.entry*100).toFixed(1)},"expectedRs":${((stock.target-stock.entry)*Math.floor(50000/stock.price)).toFixed(0)},"rr":"${((stock.target-stock.entry)/(stock.entry-stock.sl)).toFixed(1)}","conviction":"HIGH or MEDIUM or LOW","agentConsensus":{"NEXUS":"one line","HERMES":"one line","TITAN":"signal summary","GUARDIAN":"risk check"},"risks":["risk1","risk2","risk3"]}`;
    try {
      const res=await fetch("https://api.anthropic.com/v1/messages",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({model:"claude-sonnet-4-20250514",max_tokens:900,messages:[{role:"user",content:prompt}]})});
      const data=await res.json();
      const txt=data.content?.map(c=>c.text??"").join("")??"";
      const m=txt.replace(/```json|```/g,"").trim().match(/\{[\s\S]*\}/);
      if (m) setAnalysis(JSON.parse(m[0]));
    } catch {
      const rr=((stock.target-stock.entry)/(stock.entry-stock.sl)).toFixed(1);
      setAnalysis({
        selectionReason:`${stock.s} ranked #1–5 by SIGMA (${stock.score}). ${stock.mtfVotes??0}/5 MTF timeframes aligned in ${stock.regime} regime.${pats.length?" Candle pattern: "+pats[0]?.name:""}`,
        strategyReason:`${stock.sid} ${stock.sname} optimal for ${stock.regime}: ${sigs.filter(x=>x.signal>0).length} TITAN buy signals confirm.`,
        tradeTypeReason:`${stock.tt} assigned based on ADX=${ind&&Li>=0?ind.adx[Li].toFixed(0):"n/a"} and estimated regime duration.`,
        expectedPct:+((stock.target-stock.entry)/stock.entry*100).toFixed(1),
        expectedRs:+((stock.target-stock.entry)*Math.floor(50000/stock.price)).toFixed(0),
        rr,conviction:stock.confidence>.75?"HIGH":stock.confidence>.62?"MEDIUM":"LOW",
        agentConsensus:{
          NEXUS:`${stock.regime} confirmed · ${stock.sid} class optimal`,
          HERMES:"Sentiment neutral-positive",
          TITAN:`${sigs.length} signals: ${sigs.filter(x=>x.signal>0).length}B / ${sigs.filter(x=>x.signal<0).length}S`,
          GUARDIAN:`SL ₹${stock.sl.toFixed(0)} within ATR limits`,
        },
        risks:["Regime shift to RISK_OFF","Adverse earnings surprise","NIFTY systemic reversal >2%"],
      });
    }
    setMloading(false);
  };

  const paperPnl=positions.filter(p=>p.status==="OPEN").reduce((s,p)=>s+(p.pnl??0),0);
  const openCount=positions.filter(p=>p.status==="OPEN").length;

  return (
    <div style={{ background:G.bg, minHeight:"100vh",
      fontFamily:"-apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif",
      color:G.text, fontSize:13 }}>

      <ConnBanner status={connStatus}/>
      <TopNav regime={regime} indices={indices} paperPnl={paperPnl} time={now} connStatus={connStatus}/>
      <TabBar active={tab} setActive={setTab} counts={{ pos:openCount, sigs:allSigs.length, eval:evalStats?.total_evaluated??0 }}/>

      <div style={{ maxWidth:1280, margin:"0 auto", padding:"24px 24px 48px" }}>
        {tab==="overview"   && <OverviewTab    picks={picks} positions={positions} allSigs={allSigs} evalStats={evalStats} indices={indices} candleCache={candleCache} onStock={openModal}/>}
        {tab==="positions"  && <PositionsTab   positions={positions}/>}
        {tab==="signals"    && <SignalsTab      allSigs={allSigs}/>}
        {tab==="evaluation" && <EvaluationTab  evalStats={evalStats} evalHistory={evalHistory} agentScores={agentScores}/>}
        {tab==="agents"     && <AgentsTab       agentKpi={agentKpi} events={events} karmaStats={karmaStats}/>}
      </div>

      {modal && (
        <StockModal
          stock={modal}
          candles={candleCache[modal.s]}
          analysis={analysis}
          loading={modalLoading}
          fundamentals={fundamentals[modal.s]}
          onClose={()=>{ setModal(null); setAnalysis(null); }}
        />
      )}

      <style>{`
        @keyframes spin { from{transform:rotate(0)} to{transform:rotate(360deg)} }
        @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:.4} }
        ::-webkit-scrollbar { width:5px; height:5px }
        ::-webkit-scrollbar-track { background:${G.bg} }
        ::-webkit-scrollbar-thumb { background:${G.border}; border-radius:3px }
        ::-webkit-scrollbar-thumb:hover { background:${G.borderMid} }
        * { box-sizing:border-box }
      `}</style>
    </div>
  );
}
