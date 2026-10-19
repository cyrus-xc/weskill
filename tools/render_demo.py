"""Render the README walkthrough from fictional content, without opening WeChat.

Requires Pillow (already a project dependency) and a CJK font. Override the font
with --font when generating on a different Linux distribution.
"""
from argparse import ArgumentParser
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
WIDTH, HEIGHT = 1080, 624
INK, MUTED, MINT = '#F0F7F8', '#9AAEBB', '#74E7C4'
SCENES = [
    ('消息与媒体', 'weskill', '把项目介绍和 logo 发给林然，再读取最近 5 条消息。',
     [('search_contacts', '找到联系人 · 林然'),
      ('send_text_message · send_image', '发送项目介绍与本机图片'),
      ('get_messages', '读取最近 5 条聊天记录')],
     '消息与图片已发送', '最近 5 条记录已整理，发送返回 client_success。'),
    ('群协作', 'weskill-group', '在产品协作群发布周会公告，@林然，并置顶公告消息。',
     [('get_group_info · get_group_members', '确定群聊、成员与管理权限'),
      ('set_group_announcement · send_group_mention', '发布纯文本公告并提及指定成员'),
      ('pin_group_message', '按服务器消息 ID 置顶')],
     '群协作，一次交代', '公告、真实 @ 提及与消息置顶均已完成。'),
    ('表情与朋友圈', 'weskill-emoji + $weskill-moments', '找一个开心的表情发给林然，再发布这张图，仅自己可见。',
     [('list_saved_stickers · search_stickers', '浏览收藏与在线搜索表情'),
      ('send_sticker', '把选定的表情发给林然'),
      ('publish_moments', '使用本机图片 · 仅自己可见')],
     '从表情到朋友圈', '选定表情已发送，图文动态按指定可见范围发布。'),
]


def font(path, size):
    return ImageFont.truetype(str(path), size, index=2 if path.suffix == '.ttc' else 0)


def render(scene_index, tick, fonts):
    title, skill, prompt, steps, result, detail = SCENES[scene_index]
    canvas = Image.new('RGB', (WIDTH, HEIGHT), '#0B141D')
    draw = ImageDraw.Draw(canvas)
    for y in range(HEIGHT):
        t = y / HEIGHT
        draw.line((0, y, WIDTH, y), fill=(int(12+6*t), int(23+7*t), int(33+7*t)))
    draw.rounded_rectangle((22, 18, 1058, 604), radius=24, fill='#101F2B', outline='#2D414D')
    draw.line((22, 78, 1058, 78), fill='#2D414D')
    for x, color in ((47, '#FA827B'), (66, '#F1C36D'), (85, '#68D7B1')):
        draw.ellipse((x, 44, x+10, 54), fill=color)
    draw.text((454, 35), 'weSkill', font=fonts['brand'], fill=INK)
    draw.rounded_rectangle((922, 35, 1034, 62), radius=13, fill='#193C37')
    draw.ellipse((935, 45, 941, 51), fill=MINT)
    draw.text((950, 35), '本机原生', font=fonts['small'], fill=MINT)
    # Skill navigation stays fixed while each workflow plays.
    draw.line((243, 78, 243, 604), fill='#2D414D')
    draw.text((46, 106), '微信操作，一句话', font=fonts['body'], fill=INK)
    nav = ['weskill', 'weskill-group', 'weskill-friends', 'weskill-emoji', 'weskill-moments']
    active = ([0], [1], [3, 4])[scene_index]
    for i, label in enumerate(nav):
        y = 161+i*54
        if i in active:
            draw.rounded_rectangle((37, y-6, 228, y+34), radius=10, fill='#1A3D3B')
        draw.ellipse((49, y+8, 55, y+14), fill=MINT if i in active else '#526876')
        draw.text((67, y), label, font=fonts['nav'], fill=MINT if i in active else MUTED)
    draw.text((46, 510), 'Skill → MCP → 微信', font=fonts['small'], fill=MUTED)
    draw.text((46, 538), '无需切换桌面焦点', font=fonts['small'], fill=MUTED)
    draw.text((274, 96), f'0{scene_index+1}  /  {title}', font=fonts['small'], fill=MINT)
    draw.text((274, 127), '把任务交给 weSkill', font=fonts['heading'], fill=INK)
    draw.rounded_rectangle((273, 179, 1027, 244), radius=15, fill='#1D3343', outline='#36505F')
    text_count = min(len(prompt), max(0, int((tick+1)*len(prompt)/7)))
    visible = prompt[:text_count]
    # Two lines keep CJK prompts readable at GitHub's normal content width.
    split = 30
    draw.text((293, 187), visible[:split], font=fonts['body'], fill=INK)
    if len(visible) > split:
        draw.text((293, 214), visible[split:], font=fonts['body'], fill=INK)
    completed = min(3, max(0, (tick-8)//5))
    for i, (tool, description) in enumerate(steps):
        y = 264+i*65
        done = i < completed
        running = i == completed and tick >= 8
        draw.rounded_rectangle((274, y, 1026, y+55), radius=11,
                               fill='#182E34' if done else '#132530', outline='#29454B' if done else '#233945')
        draw.ellipse((290, y+18, 308, y+36), fill='#244D43' if done else '#29404C')
        if done:
            draw.line([(295, y+27), (299, y+31), (305, y+23)], fill=MINT, width=2)
        elif running:
            draw.ellipse((296, y+24, 302, y+30), fill=MINT)
        draw.text((322, y+5), tool, font=fonts['mono'], fill=MINT if done else INK)
        draw.text((322, y+29), description, font=fonts['small'], fill=MUTED)
        if done:
            draw.text((959, y+17), '完成', font=fonts['small'], fill=MINT)
    if completed == 3:
        draw.rounded_rectangle((274, 475, 1026, 550), radius=13, fill='#1B3C35', outline='#326657')
        draw.text((292, 482), result, font=fonts['body'], fill=MINT)
        draw.text((292, 515), detail, font=fonts['small'], fill='#D4E9E2')
    else:
        draw.text((277, 489), f'由 ${skill} 编排 · 原生执行', font=fonts['small'], fill=MUTED)
    for i in range(3):
        draw.rounded_rectangle((275+i*42, 574, 307+i*42, 578), radius=2,
                               fill=MINT if i == scene_index else '#354A56')
    draw.text((852, 562), 'Linux · Codex / Claude', font=fonts['small'], fill=MUTED)
    return canvas


def main():
    parser = ArgumentParser(description=__doc__)
    parser.add_argument('--font', type=Path, default=Path('/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc'))
    parser.add_argument('--output', type=Path, default=ROOT/'assets/weskill-demo.gif')
    args = parser.parse_args()
    if not args.font.is_file():
        parser.error('Choose an installed CJK font with --font')
    fonts = {name: font(args.font, size) for name, size in
             [('brand', 23), ('heading', 30), ('body', 20), ('small', 16), ('nav', 17), ('mono', 17)]}
    frames = [render(scene, tick, fonts) for scene in range(3) for tick in range(38)]
    # One palette avoids color flicker between animation frames.
    sheet = Image.new('RGB', (WIDTH, HEIGHT*3))
    for scene in range(3):
        sheet.paste(frames[scene*38+30], (0, HEIGHT*scene))
    palette = sheet.quantize(colors=192)
    encoded = [frame.quantize(palette=palette, dither=Image.Dither.NONE) for frame in frames]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    encoded[0].save(args.output, save_all=True, append_images=encoded[1:],
                    duration=140, loop=0, optimize=True, disposal=1)
    print(f'{args.output.name}: {len(frames)} source frames, {args.output.stat().st_size:,} bytes')


if __name__ == '__main__':
    main()
