#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
네이버 일별시세에서 종목별 일봉(날짜/종가/거래량)을 병렬 수집한다.

- 1페이지 = 10거래일. 기본 12페이지(~120거래일 ≈ 6개월).
- 2600종목 × 0.6초 ÷ 병렬40 ≈ 1분이면 전량 수집되므로 저장 없이 매번 새로 받는다
  (git에 시세를 커밋하지 않아 저장소가 가벼움).
"""
from __future__ import annotations

import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd
import requests
from bs4 import BeautifulSoup

HEADERS = {
    'User-Agent': ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                   '(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'),
    'Accept-Language': 'ko-KR,ko;q=0.9',
}

_local = threading.local()


def _session() -> requests.Session:
    if not hasattr(_local, 's'):
        _local.s = requests.Session()
        _local.s.headers.update(HEADERS)
    return _local.s


def fetch_one(code: str, pages: int = 12, retries: int = 2) -> pd.DataFrame:
    """한 종목의 일봉. 반환: DataFrame[date, close, volume] (날짜 오름차순)."""
    rows = []
    s = _session()
    for page in range(1, pages + 1):
        url = (f'https://finance.naver.com/item/sise_day.naver'
               f'?code={code}&page={page}')
        html = None
        for _ in range(retries):
            try:
                r = s.get(url, timeout=(4, 10))
                if r.status_code == 200:
                    r.encoding = 'euc-kr'
                    html = r.text
                    break
            except Exception:
                time.sleep(0.2)
        if html is None:
            break
        soup = BeautifulSoup(html, 'lxml')
        table = soup.find('table', class_='type2')
        if table is None:
            break
        added = 0
        for tr in table.find_all('tr'):
            tds = tr.find_all('td')
            if len(tds) < 7:
                continue
            d = tds[0].get_text(strip=True)
            if not re.match(r'\d{4}\.\d{2}\.\d{2}', d):
                continue
            close = tds[1].get_text(strip=True).replace(',', '')
            vol = tds[6].get_text(strip=True).replace(',', '')
            if not (close.isdigit() and vol.isdigit()):
                continue
            c, v = int(close), int(vol)
            if c <= 0 or v <= 0:          # 거래정지/이상치 행 제외
                continue
            rows.append((d.replace('.', '-'), c, v))
            added += 1
        if added == 0:                     # 더 이상 데이터 없음
            break
    if not rows:
        return pd.DataFrame(columns=['date', 'close', 'volume'])
    df = (pd.DataFrame(rows, columns=['date', 'close', 'volume'])
          .drop_duplicates('date')
          .sort_values('date')
          .reset_index(drop=True))
    return df


def fetch_many(codes, pages: int = 12, workers: int = 40, verbose: bool = True) -> dict:
    """여러 종목 병렬 수집. 반환: {code: DataFrame}"""
    out, done = {}, 0
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(fetch_one, c, pages): c for c in codes}
        for f in as_completed(futs):
            c = futs[f]
            try:
                df = f.result()
                if len(df) >= 30:          # 신규상장 등 이력 부족 종목 제외
                    out[c] = df
            except Exception:
                pass
            done += 1
            if verbose and done % 200 == 0:
                print(f'  ...{done}/{len(codes)} ({time.time()-t0:.0f}s)', flush=True)
    if verbose:
        print(f'  일봉 수집 완료: {len(out)}종목 / {time.time()-t0:.0f}초', flush=True)
    return out
