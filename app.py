# -*- coding: utf-8 -*-
"""ai2-breakout — 돌파 포착 대시보드"""
import os
import json
import glob
import datetime

import numpy as np
import pandas as pd
import streamlit as st

from fetch_prices import fetch_one

st.set_page_config(page_title="돌파 포착기", page_icon="🚀", layout="wide")

HERE = os.path.dirname(os.path.abspath(__file__))
SIG_DIR = os.path.join(HERE, 'signals')

STAGE_META = {
    2: ('🚀 돌파 (D+0~3)', '#34D399', '방금 터진 종목 — 매수 검토 구간'),
    1: ('🔵 돌파 임박 (스퀴즈)', '#60A5FA', '변동성 수축 중 — 미리 담아둘 후보'),
    3: ('📈 진행 중 (D+4~20)', '#FBBF24', '이미 상승 중 — 추격 주의'),
    4: ('🔥 과열', '#F87171', '단기 급등/RSI 과열 — 관망'),
}

st.markdown("""
<style>
.bk-card{background:#1E293B;border:1px solid #334155;border-left:4px solid var(--c,#34D399);
         border-radius:10px;padding:12px 16px;margin-bottom:10px;}
.bk-name{font-size:1.1rem;font-weight:800;color:#F1F5F9;}
.bk-code{font-family:monospace;color:#94A3B8;font-size:.82rem;margin-left:6px;}
.bk-chip{display:inline-block;background:rgba(52,211,153,.10);border:1px solid rgba(52,211,153,.3);
         border-radius:6px;color:#CBD5E1;font-size:.74rem;padding:2px 8px;margin:3px 4px 0 0;}
.bk-num{font-family:'JetBrains Mono',monospace;font-weight:800;}
</style>""", unsafe_allow_html=True)


@st.cache_data(ttl=600)
def load_all_signals():
    out = {}
    for p in sorted(glob.glob(os.path.join(SIG_DIR, '*.json'))):
        d = os.path.basename(p)[:-5]
        try:
            out[d] = json.load(open(p, encoding='utf-8'))
        except Exception:
            pass
    return out


@st.cache_data(ttl=1800, show_spinner=False)
def price_series(code: str, pages: int = 8):
    df = fetch_one(code, pages=pages)
    return df if len(df) else None


def spark(code):
    df = price_series(code)
    if df is None or len(df) < 20:
        return
    d = df.tail(60).copy()
    d['date'] = pd.to_datetime(d['date'])
    st.line_chart(d.set_index('date')['close'], height=140)


def render_card(s, rank=None):
    c = STAGE_META[s['stage']][1]
    chips = ''.join(f'<span class="bk-chip">{r}</span>' for r in s.get('reasons', []))
    rev = f" · 컨센 {s['rev_score']:+.1f}%" if s.get('rev_score') is not None else ''
    st.markdown(
        f'<div class="bk-card" style="--c:{c};">'
        f'<span class="bk-name">{"#"+str(rank)+" " if rank else ""}{s["name"]}</span>'
        f'<span class="bk-code">{s["code"]} · {s.get("market","")} · {s.get("sector","")}</span>'
        f'<div style="margin-top:4px;color:#CBD5E1;" class="bk-num">'
        f'{s["close"]:,.0f}원 '
        f'<span style="color:{"#34D399" if s["ret1"]>=0 else "#F87171"}">{s["ret1"]:+.1f}%</span>'
        f' · 거래량 {s["vol_ratio"]:.1f}x · 5일 {s["ret5"]:+.1f}%'
        f' · <span style="color:#62EFFF;">점수 {s["score"]}</span>{rev}</div>'
        f'<div style="margin-top:6px;">{chips}</div></div>', unsafe_allow_html=True)


sig_all = load_all_signals()
st.title("🚀 돌파 포착기")
st.caption("ai2 실적 데이터 + 일봉 기술적 신호로 **막 돌파를 시작한 종목**을 매일 자동 탐지합니다.")

if not sig_all:
    st.info("아직 신호 기록이 없습니다. `python run_daily.py` 를 실행하거나 자동 워크플로를 기다려주세요.")
    st.stop()

dates = sorted(sig_all.keys(), reverse=True)
latest = dates[0]
data = sig_all[latest]
df = pd.DataFrame(data['signals'])

c1, c2, c3, c4 = st.columns(4)
c1.metric("기준일", latest)
c2.metric("유니버스", f"{data.get('universe', 0):,}종목")
c3.metric("🚀 돌파", f"{int((df['stage']==2).sum())}종목")
c4.metric("🔵 임박", f"{int((df['stage']==1).sum())}종목")

t1, t2, t3, t4 = st.tabs(["🚀 오늘의 돌파", "🔵 돌파 임박", "📜 신호 이력", "📊 성과 검증"])

with t1:
    d2 = df[df['stage'] == 2].sort_values('score', ascending=False)
    st.markdown(f"**{STAGE_META[2][2]}** — {len(d2)}종목")
    if d2.empty:
        st.info("오늘은 돌파 신호가 없습니다. (조용한 장세이거나 조건 미달)")
    else:
        show_chart = st.checkbox("미니 차트 표시 (느려질 수 있음)", value=False)
        for i, (_, s) in enumerate(d2.head(20).iterrows(), 1):
            render_card(s, i)
            if show_chart:
                spark(s['code'])
    with st.expander(f"📈 진행 중 {int((df['stage']==3).sum())}종목 · 🔥 과열 {int((df['stage']==4).sum())}종목"):
        for stg in (3, 4):
            sub = df[df['stage'] == stg].sort_values('score', ascending=False).head(10)
            if not sub.empty:
                st.markdown(f"**{STAGE_META[stg][0]}** — {STAGE_META[stg][2]}")
                st.dataframe(sub[['name', 'code', 'close', 'ret1', 'ret5', 'ret20',
                                  'vol_ratio', 'rsi', 'score']],
                             hide_index=True, use_container_width=True)

with t2:
    d1 = df[df['stage'] == 1].sort_values('score', ascending=False)
    st.markdown(f"**{STAGE_META[1][2]}** — {len(d1)}종목")
    st.caption("변동성이 크게 수축한 상태. 아직 안 터졌으므로 관심종목에 넣고 돌파를 기다리는 용도.")
    if d1.empty:
        st.info("스퀴즈 조건을 만족하는 종목이 없습니다.")
    else:
        st.dataframe(
            d1[['name', 'code', 'market', 'sector', 'close', 'ret20',
                'squeeze_pctile', 'rsi', 'rev_score', 'score']].head(50),
            hide_index=True, use_container_width=True, height=520,
            column_config={
                'squeeze_pctile': st.column_config.NumberColumn('수축도', format='%.0f',
                                                                help='낮을수록 강하게 수축'),
                'rev_score': st.column_config.NumberColumn('컨센%', format='%+.1f'),
                'score': st.column_config.NumberColumn('점수', format='%.1f'),
            })

with t3:
    st.markdown("**과거 돌파 신호 이력** — 날짜별 Stage2 종목")
    rows = []
    for d in dates:
        for s in sig_all[d]['signals']:
            if s['stage'] == 2:
                rows.append({'신호일': d, '종목명': s['name'], '코드': s['code'],
                             '시장': s.get('market', ''), '신호가': s['close'],
                             '거래량배수': s['vol_ratio'], '점수': s['score'],
                             '근거': ' / '.join(s.get('reasons', [])[:3])})
    if rows:
        st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True, height=520)
    else:
        st.info("아직 Stage2 신호 이력이 없습니다.")

with t4:
    st.markdown("**신호 성과 검증** — 과거 Stage2 신호의 이후 수익률")
    st.caption("신호가 대비 현재가 기준. 신호가 쌓일수록 정확해집니다. "
               "(가격은 조회 시 네이버에서 가져오며 30분 캐시)")
    rows = []
    for d in dates:
        for s in sig_all[d]['signals']:
            if s['stage'] == 2:
                rows.append((d, s['code'], s['name'], s['close'], s['score']))
    if not rows:
        st.info("검증할 신호가 아직 없습니다.")
    else:
        if st.button("🔄 성과 계산 (시세 조회)"):
            recs = []
            bar = st.progress(0.0)
            uniq = {}
            for i, (d, code, name, px, sc) in enumerate(rows):
                if code not in uniq:
                    uniq[code] = price_series(code)
                pdf = uniq[code]
                cur = float(pdf['close'].iloc[-1]) if pdf is not None and len(pdf) else np.nan
                ret = (cur / px - 1) * 100 if pd.notna(cur) else np.nan
                recs.append({'신호일': d, '종목명': name, '신호가': px, '현재가': cur,
                             '수익률%': round(ret, 1) if pd.notna(ret) else None, '점수': sc})
                bar.progress((i + 1) / len(rows))
            bar.empty()
            bt = pd.DataFrame(recs).sort_values('수익률%', ascending=False, na_position='last')
            r = pd.to_numeric(bt['수익률%'], errors='coerce').dropna()
            m1, m2, m3 = st.columns(3)
            m1.metric("신호 수", f"{len(bt)}건")
            m2.metric("평균 수익률", f"{r.mean():+.1f}%" if len(r) else "-")
            m3.metric("승률", f"{(r>0).mean()*100:.0f}%" if len(r) else "-")
            st.dataframe(bt, hide_index=True, use_container_width=True, height=420)
