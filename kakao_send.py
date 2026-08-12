#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""돌파 신호 → 카카오톡 '나에게 보내기'. (ai2 저장소와 동일한 시크릿 사용)

환경변수: KAKAO_REST_KEY / KAKAO_REFRESH_TOKEN / KAKAO_CLIENT_SECRET(선택) / APP_URL(선택)
"""
import os
import sys
import json
import glob

import requests

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
SIG_DIR = os.path.join(HERE, 'signals')

REST_KEY = os.environ.get('KAKAO_REST_KEY', '').strip()
REFRESH_TOKEN = os.environ.get('KAKAO_REFRESH_TOKEN', '').strip()
CLIENT_SECRET = os.environ.get('KAKAO_CLIENT_SECRET', '').strip()
APP_URL = os.environ.get('APP_URL', '').strip() or \
    'https://github.com/perseus2133-ai/ai2-breakout'

TOP_N = 5


def access_token():
    payload = {'grant_type': 'refresh_token', 'client_id': REST_KEY,
               'refresh_token': REFRESH_TOKEN}
    if CLIENT_SECRET:
        payload['client_secret'] = CLIENT_SECRET
    j = requests.post('https://kauth.kakao.com/oauth/token', data=payload, timeout=15).json()
    if 'access_token' not in j:
        print(f'❌ 토큰 갱신 실패: {j}')
        return None
    return j['access_token']


def build_text():
    files = sorted(glob.glob(os.path.join(SIG_DIR, '*.json')))
    if not files:
        return None
    data = json.load(open(files[-1], encoding='utf-8'))
    d = data['date']
    sig = [s for s in data['signals'] if s['stage'] == 2]
    sig.sort(key=lambda s: -s['score'])
    head = f"🚀 돌파 포착 {d[5:].replace('-', '/')}"
    if not sig:
        return head + "\n오늘은 돌파 신호 없음 (조건 미달)"
    lines = [head]
    circled = '①②③④⑤⑥⑦⑧⑨⑩'
    for i, s in enumerate(sig[:TOP_N]):
        lines.append(f"{circled[i]} {s['name']} {s['ret1']:+.1f}% "
                     f"거래량{s['vol_ratio']:.1f}x 점수{s['score']:.0f}")
    n_more = len(sig) - TOP_N
    if n_more > 0:
        lines.append(f"외 {n_more}종목")
    txt = '\n'.join(lines)
    return txt[:196] + '…' if len(txt) > 197 else txt


def main():
    if not REST_KEY or not REFRESH_TOKEN:
        print('ℹ️ 카카오 시크릿 미설정 — 전송 건너뜀')
        return
    txt = build_text()
    if not txt:
        print('ℹ️ 신호 파일 없음 — 건너뜀')
        return
    tok = access_token()
    if not tok:
        return
    tpl = {'object_type': 'text', 'text': txt,
           'link': {'web_url': APP_URL, 'mobile_web_url': APP_URL},
           'button_title': '돌파 포착기 열기'}
    j = requests.post('https://kapi.kakao.com/v2/api/talk/memo/default/send',
                      headers={'Authorization': f'Bearer {tok}'},
                      data={'template_object': json.dumps(tpl, ensure_ascii=False)},
                      timeout=15).json()
    print('✅ 카톡 전송 완료' if j.get('result_code') == 0 else f'❌ 전송 실패: {j}')


if __name__ == '__main__':
    main()
