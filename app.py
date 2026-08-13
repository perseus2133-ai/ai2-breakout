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
/* 반응형 그리드: 넓은 화면 2~3열, 폰 1열 — 빈 공간 최소화 */
.bk-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(390px,1fr));
         gap:12px;margin-top:8px;}

/* 밝은 카드 + 3D 입체감 */
.bk-card{position:relative;background:linear-gradient(160deg,#FFFFFF 0%,#F1F5F9 100%);
         border:1px solid #D7DEE8;border-top:3px solid var(--c,#22A06B);
         border-radius:12px;padding:11px 14px 10px;
         box-shadow:0 1px 2px rgba(16,24,40,.06),0 4px 10px rgba(16,24,40,.08);
         transition:transform .16s ease, box-shadow .16s ease, border-color .16s ease;}
.bk-card:hover{transform:translateY(-4px) scale(1.012);
               box-shadow:0 10px 22px rgba(16,24,40,.16),0 3px 6px rgba(16,24,40,.10);
               border-color:var(--c,#22A06B);}

.bk-hd{display:flex;align-items:center;gap:7px;flex-wrap:wrap;}
.bk-rk{display:inline-flex;align-items:center;justify-content:center;
       width:21px;height:21px;border-radius:6px;font-family:'JetBrains Mono',monospace;
       font-size:.72rem;font-weight:800;color:#fff;background:var(--c,#22A06B);
       box-shadow:0 2px 4px rgba(16,24,40,.18);}
a.bk-name{font-size:1.06rem;font-weight:800;color:#0F172A;text-decoration:none;
          transition:color .15s ease;}
a.bk-name:hover{color:#1D6FE0;text-decoration:underline;}
a.bk-name::after{content:'↗';font-size:.66rem;color:#94A3B8;margin-left:3px;
                 vertical-align:super;}
.bk-meta{font-family:monospace;color:#7A879B;font-size:.7rem;}
.bk-score{margin-left:auto;font-family:'JetBrains Mono',monospace;font-weight:800;
          font-size:.8rem;color:#fff;background:var(--c,#22A06B);
          border-radius:7px;padding:2px 9px;box-shadow:0 2px 5px rgba(16,24,40,.20);}

/* 기업개요 */
.bk-desc{margin-top:6px;font-size:.76rem;line-height:1.4;color:#4A5768;
         background:#EEF2F7;border-left:2px solid #C6D2E1;border-radius:0 6px 6px 0;
         padding:5px 8px;}

/* 지표 수평 배열 */
.bk-mt{display:flex;flex-wrap:wrap;gap:0 13px;margin-top:7px;
       font-family:'JetBrains Mono',monospace;font-size:.79rem;}
.bk-mt b{font-weight:800;}
.bk-mt s{text-decoration:none;color:#8A95A6;font-size:.65rem;margin-right:3px;}

.bk-chips{margin-top:7px;display:flex;flex-wrap:wrap;gap:4px;}
.bk-chip{background:#EDF1F6;border:1px solid #D5DDE8;border-radius:6px;
         color:#475569;font-size:.69rem;font-weight:600;padding:2px 7px;}
.bk-chip.hot{background:linear-gradient(180deg,#E7F8F0,#D6F2E6);
             border-color:#8FD9BC;color:#0E7A55;
             box-shadow:0 1px 2px rgba(14,122,85,.12);}
</style>""", unsafe_allow_html=True)


@st.cache_data(ttl=3600, show_spinner=False)
def _is_mobile_ua(ua: str) -> bool:
    """폰만 '모바일'로 본다. 태블릿은 화면이 커서 일반(데스크톱) 화면이 더 낫다."""
    ua = (ua or '').lower()
    if 'ipad' in ua or 'tablet' in ua:
        return False
    if any(k in ua for k in ('iphone', 'ipod', 'windows phone', 'iemobile')):
        return True
    # 안드로이드 폰은 UA에 'mobile' 토큰이 있고, 태블릿은 없다
    return 'android' in ua and 'mobile' in ua


def is_mobile() -> bool:
    """접속 기기 판별 (User-Agent). 판별 실패 시 PC로 간주."""
    try:
        return _is_mobile_ua(st.context.headers.get('User-Agent', ''))
    except Exception:
        return False


IS_MOBILE = is_mobile()


def naver_url(code: str) -> str:
    """네이버 증권 종목 페이지.
    PC → 일반(데스크톱) 화면, 모바일 → 모바일 화면."""
    if IS_MOBILE:
        return f'https://m.stock.naver.com/domestic/stock/{code}/total'
    return f'https://finance.naver.com/item/main.naver?code={code}'


def add_link_col(df: pd.DataFrame) -> pd.DataFrame:
    """표에 네이버 링크 컬럼 추가."""
    out = df.copy()
    out['네이버'] = out['code'].map(naver_url) if 'code' in out.columns \
        else out['코드'].map(naver_url)
    return out


LINK_CFG = st.column_config.LinkColumn('네이버', display_text='📈 보기', width='small')


@st.cache_data(ttl=600)
def load_profiles_cached() -> dict:
    try:
        return json.load(open(os.path.join(HERE, 'profiles.json'), encoding='utf-8'))
    except Exception:
        return {}


PROFILES = load_profiles_cached()


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


def card_html(s, rank=None) -> str:
    """컴팩트 카드 1개의 HTML. 종목명 자체가 네이버 증권 링크."""
    c = STAGE_META[s['stage']][1]
    # 밝은 배경용 대비 색 (상승 레드 / 하락 블루 — 국내 증권사 관행)
    up = lambda v: '#D42C2C' if (pd.notna(v) and v >= 0) else '#1D6FE0'

    def m(label, val, color='#1F2937'):
        return f'<span><s>{label}</s><b style="color:{color};">{val}</b></span>'

    mets = [
        m('', f'{s["close"]:,.0f}'),
        m('D', f'{s["ret1"]:+.1f}%', up(s['ret1'])),
        m('5일', f'{s["ret5"]:+.1f}%', up(s['ret5'])),
        m('20일', f'{s["ret20"]:+.1f}%', up(s['ret20'])),
        m('거래량', f'{s["vol_ratio"]:.1f}x',
          '#B45309' if s['vol_ratio'] >= 3 else '#1F2937'),
        m('RSI', f'{s["rsi"]:.0f}'),
    ]
    if s.get('rev_score') is not None:
        mets.append(m('컨센', f'{s["rev_score"]:+.1f}%', up(s['rev_score'])))

    chips = ''.join(
        f'<span class="bk-chip{" hot" if ("신고가" in r or "폭증" in r) else ""}">{r}</span>'
        for r in s.get('reasons', []))
    rk = f'<span class="bk-rk">{rank}</span>' if rank else ''
    # 신호 파일에 profile 이 없던 시기(구버전)에는 profiles.json 캐시로 보완
    prof = (s.get('profile') or PROFILES.get(s['code'], {}).get('summary', '') or '').strip()
    desc = f'<div class="bk-desc">{prof}</div>' if prof else ''
    return (
        f'<div class="bk-card" style="--c:{c};">'
        f'<div class="bk-hd">{rk}'
        f'<a class="bk-name" href="{naver_url(s["code"])}" target="_blank" '
        f'title="네이버 증권에서 열기">{s["name"]}</a>'
        f'<span class="bk-meta">{s["code"]}·{s.get("market","")}'
        f'{"·"+s["sector"] if s.get("sector") else ""}</span>'
        f'<span class="bk-score">{s["score"]:.0f}</span></div>'
        f'{desc}'
        f'<div class="bk-mt">{"".join(mets)}</div>'
        f'<div class="bk-chips">{chips}</div></div>')


def render_grid(items):
    """카드들을 반응형 그리드로 한 번에 렌더."""
    html = ''.join(card_html(s, i) for i, (_, s) in enumerate(items.iterrows(), 1))
    st.markdown(f'<div class="bk-grid">{html}</div>', unsafe_allow_html=True)


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
        top = d2.head(24)
        if show_chart:
            for i, (_, s) in enumerate(top.iterrows(), 1):
                st.markdown(card_html(s, i), unsafe_allow_html=True)
                spark(s['code'])
        else:
            render_grid(top)
        st.caption("종목명을 누르면 네이버 증권으로 이동합니다.")
    with st.expander(f"📈 진행 중 {int((df['stage']==3).sum())}종목 · 🔥 과열 {int((df['stage']==4).sum())}종목"):
        for stg in (3, 4):
            sub = df[df['stage'] == stg].sort_values('score', ascending=False).head(10)
            if not sub.empty:
                st.markdown(f"**{STAGE_META[stg][0]}** — {STAGE_META[stg][2]}")
                st.dataframe(add_link_col(sub)[['name', 'code', '네이버', 'close', 'ret1',
                                                'ret5', 'ret20', 'vol_ratio', 'rsi', 'score']],
                             hide_index=True, use_container_width=True,
                             column_config={'네이버': LINK_CFG})

with t2:
    d1 = df[df['stage'] == 1].sort_values('score', ascending=False)
    st.markdown(f"**{STAGE_META[1][2]}** — {len(d1)}종목")
    st.caption("변동성이 크게 수축한 상태. 아직 안 터졌으므로 관심종목에 넣고 돌파를 기다리는 용도.")
    if d1.empty:
        st.info("스퀴즈 조건을 만족하는 종목이 없습니다.")
    else:
        st.dataframe(
            add_link_col(d1.head(50))[['name', 'code', '네이버', 'market', 'sector', 'close',
                                       'ret20', 'squeeze_pctile', 'rsi', 'rev_score', 'score']],
            hide_index=True, use_container_width=True, height=520,
            column_config={
                '네이버': LINK_CFG,
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
                             '네이버': naver_url(s['code']),
                             '시장': s.get('market', ''), '신호가': s['close'],
                             '거래량배수': s['vol_ratio'], '점수': s['score'],
                             '근거': ' / '.join(s.get('reasons', [])[:3])})
    if rows:
        st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True,
                     height=520, column_config={'네이버': LINK_CFG})
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
                recs.append({'신호일': d, '종목명': name, '네이버': naver_url(code),
                             '신호가': px, '현재가': cur,
                             '수익률%': round(ret, 1) if pd.notna(ret) else None, '점수': sc})
                bar.progress((i + 1) / len(rows))
            bar.empty()
            bt = pd.DataFrame(recs).sort_values('수익률%', ascending=False, na_position='last')
            r = pd.to_numeric(bt['수익률%'], errors='coerce').dropna()
            m1, m2, m3 = st.columns(3)
            m1.metric("신호 수", f"{len(bt)}건")
            m2.metric("평균 수익률", f"{r.mean():+.1f}%" if len(r) else "-")
            m3.metric("승률", f"{(r>0).mean()*100:.0f}%" if len(r) else "-")
            st.dataframe(bt, hide_index=True, use_container_width=True, height=420,
                         column_config={
                             '네이버': LINK_CFG,
                             '수익률%': st.column_config.NumberColumn('수익률', format='%+.1f%%'),
                         })
