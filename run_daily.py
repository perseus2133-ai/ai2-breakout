#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
매일 실행: ai2 데이터로 유니버스 구성 → 일봉 수집 → 돌파 신호 계산 → 저장 → 카톡.

ai2(공개 저장소)의 데이터는 raw.githubusercontent 에서 받아 쓴다.
시세는 매번 새로 수집하므로 이 저장소에는 시세 파일을 커밋하지 않는다
(신호 JSON만 누적 → 저장소가 가볍고 성과 추적이 가능).
"""
from __future__ import annotations

import io
import json
import os
import sys
import datetime
import argparse

import numpy as np
import pandas as pd
import requests

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

from fetch_prices import fetch_many
import breakout as bo

HERE = os.path.dirname(os.path.abspath(__file__))
SIG_DIR = os.path.join(HERE, 'signals')
AI2_RAW = 'https://raw.githubusercontent.com/perseus2133-ai/ai2/main'
AI2_API = 'https://api.github.com/repos/perseus2133-ai/ai2/contents'

MIN_MCAP = 1000          # 억
MIN_TURNOVER_WON = 1_000_000_000   # 10억
REV_WEIGHTS = {2026: 0.5, 2027: 0.3, 2028: 0.2}


def kst_today() -> datetime.date:
    return datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9))).date()


def load_ai2_csv() -> pd.DataFrame:
    r = requests.get(f'{AI2_RAW}/data/consensus_data.csv', timeout=60)
    r.raise_for_status()
    df = pd.read_csv(io.BytesIO(r.content), encoding='utf-8-sig', dtype={'종목코드': str})
    df['종목코드'] = df['종목코드'].astype(str).str.zfill(6)
    return df


def load_ai2_snapshot(days_ago: int = 30) -> dict:
    """days_ago일 이전 중 가장 가까운 컨센 스냅샷 (없으면 {})."""
    try:
        r = requests.get(f'{AI2_API}/data/consensus_snapshots', timeout=30)
        r.raise_for_status()
        names = sorted(x['name'][:-5] for x in r.json() if x['name'].endswith('.json'))
    except Exception:
        return {}
    cutoff = (kst_today() - datetime.timedelta(days=days_ago)).isoformat()
    cand = [n for n in names if n <= cutoff]
    pick = cand[-1] if cand else (names[0] if names else None)
    if not pick:
        return {}
    try:
        s = requests.get(f'{AI2_RAW}/data/consensus_snapshots/{pick}.json', timeout=60)
        s.raise_for_status()
        print(f'  컨센 비교 스냅샷: {pick}')
        return s.json()
    except Exception:
        return {}


def revision_scores(df: pd.DataFrame, snap: dict) -> pd.Series:
    """30일 전 대비 영업이익 컨센 가중 변화율(%)."""
    ws = pd.Series(0.0, index=df.index)
    wu = pd.Series(0.0, index=df.index)
    for y, w in REV_WEIGHTS.items():
        new = pd.to_numeric(df.get(f'영업이익_{y}'), errors='coerce')
        old = pd.to_numeric(
            df['종목코드'].map(lambda c, _y=y: (snap.get(c, {}) or {}).get(f'영업이익_{_y}')),
            errors='coerce')
        m = new.notna() & old.notna() & (old > 0)
        r = pd.Series(np.nan, index=df.index)
        r.loc[m] = (new[m] - old[m]) / old[m] * 100
        ws.loc[m] += r[m] * w
        wu.loc[m] += w
    return pd.Series(np.where(wu > 0, ws / wu, np.nan), index=df.index)


def build_universe(df: pd.DataFrame) -> pd.DataFrame:
    num = lambda c: pd.to_numeric(df.get(c), errors='coerce')
    mcap, price, vol = num('시가총액'), num('현재가'), num('Recent_Volume')
    has_consensus = num('영업이익_2027').notna() | num('영업이익_2028').notna()
    name = df['종목명'].astype(str)
    keep = (
        has_consensus &
        mcap.notna() & (mcap >= MIN_MCAP) &
        price.notna() & (price > 0) &
        ((vol * price) >= MIN_TURNOVER_WON) &
        ~name.str.endswith(('우', '우B')) &
        ~name.str.contains('스팩')
    )
    return df[keep].copy()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--pages', type=int, default=12, help='일봉 페이지 수 (1p=10거래일)')
    ap.add_argument('--limit', type=int, default=0, help='테스트용 종목 수 제한')
    ap.add_argument('--no-save', action='store_true')
    args = ap.parse_args()

    print('1) ai2 데이터 로드...')
    df = load_ai2_csv()
    snap = load_ai2_snapshot(30)
    print(f'  전체 {len(df)}종목')

    uni = build_universe(df)
    uni['_rev'] = revision_scores(uni, snap)
    if args.limit:
        uni = uni.nlargest(args.limit, '시가총액')
    print(f'2) 유니버스 {len(uni)}종목 (컨센 보유·시총{MIN_MCAP}억↑·거래대금10억↑)')

    print('3) 일봉 수집...')
    prices = fetch_many(uni['종목코드'].tolist(), pages=args.pages)

    print('4) 신호 계산...')
    # 수급/컨센 백분위 (유니버스 내)
    fl = (pd.to_numeric(uni.get('외인_5d'), errors='coerce').fillna(0) +
          pd.to_numeric(uni.get('기관_5d'), errors='coerce').fillna(0))
    flow_amt = fl * pd.to_numeric(uni['현재가'], errors='coerce') / \
        (pd.to_numeric(uni['시가총액'], errors='coerce') * 1e8) * 100
    uni['_flow_pct'] = flow_amt.rank(pct=True) * 100
    uni['_rev_pct'] = uni['_rev'].rank(pct=True) * 100

    rows = []
    for _, r in uni.iterrows():
        code = r['종목코드']
        pdf = prices.get(code)
        ind = bo.compute_indicators(pdf)
        if ind is None:
            continue
        stage = bo.classify_stage(ind)
        if stage == 0:
            continue
        sc = bo.score(ind, r.get('_flow_pct'), r.get('_rev_pct'))
        rows.append({
            'code': code, 'name': str(r['종목명']),
            'market': str(r.get('시장', '')), 'sector': str(r.get('업종', '')),
            'stage': stage,
            'close': ind['close'], 'ret1': round(ind['ret1'], 2),
            'ret5': round(ind['ret5'], 2), 'ret20': round(ind['ret20'], 2),
            'vol_ratio': round(ind['vol_ratio'], 2),
            'above_high20_pct': round(ind['above_high20_pct'], 2),
            'is_high60': ind['is_high60'], 'is_high120': ind['is_high120'],
            'days_since_breakout': ind['days_since_breakout'],
            'squeeze_pctile': round(ind['squeeze_pctile'], 1),
            'rsi': round(ind['rsi'], 1), 'ma_align': ind['ma_align'],
            'mcap': float(pd.to_numeric(pd.Series([r['시가총액']]), errors='coerce').iloc[0]),
            'rev_score': None if pd.isna(r['_rev']) else round(float(r['_rev']), 1),
            **sc,
            'reasons': bo.reasons(ind, r['_rev']),
        })

    res = pd.DataFrame(rows)
    if res.empty:
        print('  신호 없음'); return
    res = res.sort_values(['stage', 'score'], ascending=[True, False])

    for s, label in [(2, '🚀 돌파(D+0~3)'), (1, '🔵 준비(스퀴즈)'),
                     (3, '📈 진행'), (4, '🔥 과열')]:
        n = int((res['stage'] == s).sum())
        print(f'  Stage{s} {label}: {n}종목')

    top = res[res['stage'] == 2].head(10)
    if not top.empty:
        print('\n  ── 오늘의 돌파 TOP ──')
        for _, t in top.iterrows():
            print(f"   {t['name']}({t['code']}) 점수{t['score']} "
                  f"{t['ret1']:+.1f}% 거래량{t['vol_ratio']:.1f}x — {' · '.join(t['reasons'][:3])}")

    if not args.no_save:
        os.makedirs(SIG_DIR, exist_ok=True)
        d = kst_today().isoformat()
        path = os.path.join(SIG_DIR, f'{d}.json')
        json.dump({'date': d, 'universe': len(uni), 'signals': res.to_dict('records')},
                  open(path, 'w', encoding='utf-8'), ensure_ascii=False)
        print(f'\n✅ 저장: signals/{d}.json ({len(res)}건)')


if __name__ == '__main__':
    main()
