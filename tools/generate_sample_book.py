from __future__ import annotations

import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


PAGES = [
    "ミナは雨上がりの灯台で、止まった時計を見つけた。針は昨日の夕方を示している。管理人は、時計は朝まで動いていたと言った。",
    "古い記録帳には、同じ時刻に船の灯が消えたと書かれていた。だが、その日の海は穏やかだったらしい。ミナは偶然だと考えた。",
    "友人のソウは、記録帳の紙だけが新しいことに気づく。誰かが後から差し替えた可能性がある。二人の見方に初めて違いが生まれた。",
    "管理人は記録の話を避け、地下倉庫の鍵を隠した。ミナは疑いながらも、彼の疲れた表情が気にかかった。",
    "地下では壊れた無線機が見つかった。最後の受信時刻は、灯台の時計と同じだった。ミナの偶然という解釈が揺らぐ。",
    "ソウは管理人が事件を隠していると断じる。ミナは、隠していることと犯人であることは同じではないと反論した。",
    "記録帳の筆跡は、行方不明になった前任者のものだった。ただし末尾の一行だけ、筆圧が違っていた。",
    "管理人は前任者から『灯を消すな』と頼まれていたと明かす。沈黙は罪を隠すためではなく、約束を守るためだった可能性が出る。",
    "時計を直すと、内部から小さな写真が落ちた。そこには前任者と幼い管理人が写っている。二人が親子だった事実が判明する。",
    "夜、沖に一度だけ灯が見えた。ミナは事件の答えより、約束が人の判断をどう縛るかを考えた。記録の改変者はまだ確定していない。",
]


def find_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        Path("C:/Windows/Fonts/YuGothM.ttc"),
        Path("C:/Windows/Fonts/meiryo.ttc"),
        Path("C:/Windows/Fonts/msgothic.ttc"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return ImageFont.truetype(str(candidate), size)
    return ImageFont.load_default()


def main() -> None:
    output = Path(__file__).resolve().parents[1] / "samples" / "generated"
    output.mkdir(parents=True, exist_ok=True)
    body_font = find_font(34)
    small_font = find_font(20)
    for index, text in enumerate(PAGES, 1):
        image = Image.new("RGB", (900, 1200), "#f5f0e8")
        draw = ImageDraw.Draw(image)
        draw.rectangle((55, 55, 845, 1145), outline="#c3b9a6", width=2)
        draw.text((90, 85), "自作サンプル『灯台の止まった時計』", fill="#6c6253", font=small_font)
        wrapped = textwrap.wrap(text, width=23)
        y = 210
        for line in wrapped:
            draw.text((105, y), line, fill="#251f19", font=body_font)
            y += 62
        draw.text((430, 1090), str(index), fill="#756b5b", font=small_font)
        image.save(output / f"page_{index:02d}.png", optimize=True)
        image.close()
    print(f"Generated {len(PAGES)} original sample pages in {output}")


if __name__ == "__main__":
    main()

