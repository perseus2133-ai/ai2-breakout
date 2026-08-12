#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
돌파 신호 계산 + Stage 분류.

설계 근거 (코스메카코리아 241710 실측, 2026-08 검증):
  - '20일 신고가' 단독 신호는 헛발이 많았다 (4/24·6/29·7/7·7/9 …).
  - 신고가 + 거래량 급증(3배↑) 조합에서 실제 돌파(8/11 8.5배)가 선명해졌다.
  → 단일 조건이 아니라 다중 조건 가중 스코어로 판정한다.

Stage
  1 준비 : 변동성 수축(스퀴즈) · 아직 안 터짐        → 관심종목
  2 돌파 : D+0~3, 신고가 + 거래량 폭발               → ★ 알림 대상
  3 진행 : D+4~20, 이미 상승 중                      → 추격 주의
  4 과열 : 단기 급등/RSI 과열                        → 관망
"""
from __future__ import annotations

import numpy as np
import pandas as pd

# 스코어 가중 (합 100)
W = {'breakout': 30, 'volume': 25, 'squeeze': 15, 'trend': 10, 'flow': 10, 'revision': 10}

BREAKOUT_LOOKBACK = 20      # 신고가 판정 기준일
FRESH_DAYS = 3              # Stage2로 볼 최대 경과일 (D+0~3)
STAGE3_MAX_DAYS = 20
MIN_VOL_RATIO = 2.0         # Stage2 기본 거래량배수 문턱
# 가격이 강하게 뚫은 날은 거래량 문턱을 완화한다.
# (코스메카코리아 8/06: +8.1% 신고가인데 거래량 1.7배라 기본 문턱에 걸려
#  놓쳤고, 그날이 실제로는 +28.7%의 시작점이었다. 반대로 헛발 신호들
#  4/24·6/29·7/7·7/9 는 돌파폭이 1.3% 미만이라 이 완화에 걸리지 않는다.)
STRONG_BREAK_PCT = 5.0      # 이 이상 뚫으면
STRONG_BREAK_VOL = 1.5      # 거래량은 이 배수만 넘어도 인정
OVERHEAT_RET20 = 60.0       # 20일 수익률 %
OVERHEAT_RSI = 80.0


def _rsi(close: np.ndarray, period: int = 14) -> float:
    if len(close) < period + 1:
        return np.nan
    d = np.diff(close[-(period + 1):])
    up = d[d > 0].sum() / period
    dn = -d[d < 0].sum() / period
    if dn == 0:
        return 100.0
    rs = up / dn
    return 100 - 100 / (1 + rs)


def compute_indicators(df: pd.DataFrame) -> dict | None:
    """일봉 DataFrame(date/close/volume, 오름차순) → 지표 dict."""
    if df is None or len(df) < 40:
        return None
    c = df['close'].to_numpy(dtype=float)
    v = df['volume'].to_numpy(dtype=float)
    n = len(c)

    ma5 = c[-5:].mean()
    ma20 = c[-20:].mean()
    ma60 = c[-60:].mean() if n >= 60 else c.mean()

    prev = c[:-1]
    high20 = prev[-BREAKOUT_LOOKBACK:].max()
    high60 = prev[-60:].max() if n > 60 else prev.max()
    high120 = prev[-120:].max() if n > 120 else prev.max()

    vol_avg20 = v[-21:-1].mean() if n > 21 else v[:-1].mean()
    vol_ratio = float(v[-1] / vol_avg20) if vol_avg20 > 0 else 0.0

    # 볼린저 밴드폭(20일) 시계열 → 스퀴즈 판정
    bw = []
    for i in range(max(20, n - 60), n + 1):
        w = c[i - 20:i]
        m = w.mean()
        bw.append((w.std() * 4) / m * 100 if m else np.nan)   # (상단-하단)/중심 %
    bw = np.array(bw, dtype=float)
    bw_now = bw[-1]
    # 돌파 직전(최근 20일 중 최소) 밴드폭이 얼마나 좁았는지 → 수축 강도
    bw_recent_min = np.nanmin(bw[-20:]) if len(bw) >= 20 else bw_now
    bw_pctile = float((bw < bw_recent_min).mean() * 100) if len(bw) > 5 else 50.0

    # 신고가 돌파 경과일: 오늘부터 거슬러 올라가며 '그날의 20일 신고가' 첫 발생일
    days_since = None
    for k in range(0, min(STAGE3_MAX_DAYS + 1, n - BREAKOUT_LOOKBACK - 1)):
        idx = n - 1 - k
        hi = c[idx - BREAKOUT_LOOKBACK:idx].max()
        if c[idx] > hi:
            days_since = k
            # 연속 돌파면 가장 이른 날을 시작점으로
            j = k
            while j + 1 < min(STAGE3_MAX_DAYS + 1, n - BREAKOUT_LOOKBACK - 1):
                idx2 = n - 1 - (j + 1)
                if c[idx2] > c[idx2 - BREAKOUT_LOOKBACK:idx2].max():
                    j += 1
                else:
                    break
            days_since = j
            break

    ret1 = (c[-1] / c[-2] - 1) * 100 if n >= 2 else np.nan
    ret5 = (c[-1] / c[-6] - 1) * 100 if n >= 6 else np.nan
    ret20 = (c[-1] / c[-21] - 1) * 100 if n >= 21 else np.nan

    return {
        'date': str(df['date'].iloc[-1]),
        'close': float(c[-1]),
        'volume': float(v[-1]),
        'ma5': float(ma5), 'ma20': float(ma20), 'ma60': float(ma60),
        'high20': float(high20), 'high60': float(high60), 'high120': float(high120),
        'above_high20_pct': float((c[-1] / high20 - 1) * 100),
        'is_high60': bool(c[-1] > high60),
        'is_high120': bool(c[-1] > high120),
        'vol_ratio': vol_ratio,
        'bandwidth': float(bw_now),
        'squeeze_pctile': bw_pctile,          # 낮을수록 최근 수축이 강했음
        'days_since_breakout': days_since,    # None = 최근 20일 내 돌파 없음
        'rsi': float(_rsi(c)),
        'ret1': float(ret1), 'ret5': float(ret5), 'ret20': float(ret20),
        'ma_align': bool(ma5 > ma20 > ma60),
    }


def classify_stage(ind: dict) -> int:
    """1 준비 / 2 돌파 / 3 진행 / 4 과열 / 0 해당없음"""
    ds = ind['days_since_breakout']
    ret20, rsi = ind['ret20'], ind['rsi']

    # 과열: 단기 급등 후 (추격 위험)
    if (pd.notna(ret20) and ret20 >= OVERHEAT_RET20) or \
       (pd.notna(rsi) and rsi >= OVERHEAT_RSI):
        return 4

    if ds is not None and ds <= FRESH_DAYS:
        vr, brk = ind['vol_ratio'], ind['above_high20_pct']
        vol_ok = (vr >= MIN_VOL_RATIO) or (brk >= STRONG_BREAK_PCT and vr >= STRONG_BREAK_VOL)
        if vol_ok and ind['close'] > ind['ma20']:
            return 2                                  # ★ 돌파 초기
        return 3 if ind['close'] > ind['ma20'] else 0
    if ds is not None and ds <= STAGE3_MAX_DAYS and ind['close'] > ind['ma20']:
        return 3
    # 준비: 아직 안 터졌고, 변동성 수축 + 추세 붕괴 아님
    if ds is None and ind['squeeze_pctile'] <= 30 and ind['close'] > ind['ma60'] * 0.92:
        return 1
    return 0


def _clip01(x, lo, hi):
    if pd.isna(x):
        return 0.0
    return float(np.clip((x - lo) / (hi - lo), 0, 1) * 100)


def score(ind: dict, flow_pct: float = np.nan, rev_pct: float = np.nan) -> dict:
    """0~100 종합 점수 + 축별 점수.
    flow_pct / rev_pct 는 유니버스 내 백분위(0~100). 없으면 중립(50) 처리."""
    s_break = _clip01(ind['above_high20_pct'], 0, 10)
    if ind['is_high60']:
        s_break = min(100, s_break + 15)
    if ind['is_high120']:
        s_break = min(100, s_break + 15)

    s_vol = _clip01(ind['vol_ratio'], 1.0, 5.0)
    s_squeeze = float(np.clip(100 - ind['squeeze_pctile'], 0, 100))

    s_trend = 20.0
    if ind['ma_align']:
        s_trend = 100.0
    elif ind['ma5'] > ind['ma20']:
        s_trend = 60.0
    if ind['close'] < ind['ma60']:
        s_trend *= 0.5

    s_flow = 50.0 if pd.isna(flow_pct) else float(flow_pct)
    s_rev = 50.0 if pd.isna(rev_pct) else float(rev_pct)

    total = (s_break * W['breakout'] + s_vol * W['volume'] + s_squeeze * W['squeeze'] +
             s_trend * W['trend'] + s_flow * W['flow'] + s_rev * W['revision']) / 100
    return {
        'score': round(float(total), 1),
        's_breakout': round(s_break, 1), 's_volume': round(s_vol, 1),
        's_squeeze': round(s_squeeze, 1), 's_trend': round(s_trend, 1),
        's_flow': round(s_flow, 1), 's_revision': round(s_rev, 1),
    }


def reasons(ind: dict, rev_score=None) -> list[str]:
    out = []
    if ind['is_high120']:
        out.append('120일 신고가')
    elif ind['is_high60']:
        out.append('60일 신고가')
    elif ind['above_high20_pct'] > 0:
        out.append(f"20일 신고가 +{ind['above_high20_pct']:.1f}%")
    if ind['vol_ratio'] >= 3:
        out.append(f"거래량 {ind['vol_ratio']:.1f}배 폭증")
    elif ind['vol_ratio'] >= 2:
        out.append(f"거래량 {ind['vol_ratio']:.1f}배")
    if ind['squeeze_pctile'] <= 25:
        out.append('변동성 수축 해소')
    if ind['ma_align']:
        out.append('이평 정배열')
    if pd.notna(ind['ret5']) and ind['ret5'] > 0:
        out.append(f"5일 {ind['ret5']:+.1f}%")
    if rev_score is not None and pd.notna(rev_score) and rev_score > 3:
        out.append(f'컨센 상향 {rev_score:+.1f}%')
    return out[:5]
