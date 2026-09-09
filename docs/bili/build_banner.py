# -*- coding: utf-8 -*-
"""生成 ZCode × DeepSeek 合成横幅 SVG（1280x720，16:9）。v2：DeepSeek 鲸鱼取 Simple Icons 官方路径。"""
import json
import os
import re

REF_DIR = r'C:\Users\frank\Desktop\BONC\zcode_tps\docs\bili\refs'

# 1) DeepSeek 鲸鱼（Simple Icons 官方，viewBox 0 0 24 24）
si = open(os.path.join(REF_DIR, 'deepseek_simpleicons.svg'), encoding='utf-8').read()
whale_d = re.search(r'<path d="([^"]+)"', si).group(1)
whale = f'<path fill="#4d6bfe" d="{whale_d}"/>'

# 2) ZCode 白色 Z 三笔轮廓（应用图标像素提取，1024 画布）
z_strokes = json.load(open(os.path.join(REF_DIR, 'z_path.json')))
z_glyph = ''
for s in z_strokes:
    pts = ' '.join(f'{x},{y}' for x, y in s['eps3'])
    z_glyph += f'<polygon points="{pts}" fill="#ffffff"/>'

tile = '<rect x="91" y="96" width="842" height="847" rx="193" fill="#0b0c0c"/>'

svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="720" viewBox="0 0 1280 720">
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="#fafcff"/>
      <stop offset="1" stop-color="#e7eefc"/>
    </linearGradient>
  </defs>
  <rect width="1280" height="720" fill="url(#bg)"/>
  <path d="M-80,730 C280,560 720,782 1360,560 L1360,730 Z" fill="#e3ebfb" opacity="0.85"/>
  <path d="M-60,730 C300,640 780,800 1360,660 L1360,730 Z" fill="#d5e1f8" opacity="0.7"/>

  <!-- DeepSeek：鲸鱼 + 字标 -->
  <g transform="translate(64,248) scale(9.5)">{whale}</g>
  <text x="330" y="428" font-family="Segoe UI, Arial, sans-serif" font-size="96" font-weight="700" fill="#4d6bfe" letter-spacing="1">deepseek</text>

  <!-- 中间的 × -->
  <g transform="translate(806,363)" fill="#8fa3d9">
    <rect x="-45" y="-12" width="90" height="24" rx="12" transform="rotate(45)"/>
    <rect x="-45" y="-12" width="90" height="24" rx="12" transform="rotate(-45)"/>
  </g>

  <!-- ZCode 应用图标（黑方块 + 白色 Z） -->
  <g transform="translate(872,226) scale(0.27)">{tile}{z_glyph}</g>
  <text x="995" y="560" text-anchor="middle" font-family="Segoe UI, Arial, sans-serif" font-size="46" font-weight="700" fill="#14161c">ZCode</text>

  <text x="640" y="650" text-anchor="middle" font-family="Microsoft YaHei, Segoe UI, sans-serif" font-size="26" fill="#6e7fa6" letter-spacing="2">DeepSeek v4.1 公测 · 用 ZCode 实测速度</text>
</svg>
'''
open(r'C:\Users\frank\Desktop\BONC\zcode_tps\docs\bili\zcode-deepseek.svg', 'w', encoding='utf-8').write(svg)
print('ok')
