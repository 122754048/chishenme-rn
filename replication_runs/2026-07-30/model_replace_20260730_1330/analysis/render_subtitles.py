from pathlib import Path
import subprocess

RUN = Path(__file__).resolve().parents[1]
ASS = RUN / "analysis" / "live_subtitles.ass"
SOURCE = RUN / "seedance" / "S01" / "result.mp4"
OUTPUT = RUN / "seedance" / "S01" / "result_with_subtitles.mp4"

line_1 = "\u0646\u0641\u0633\u0643 \u062a\u062a\u0639\u0631\u0641 \u0639\u0644\u0649 \u0635\u062d\u0627\u0628 \u062c\u062f\u0627\u062f \u0643\u062f\u0647\u061f"
line_2a = "\u0639\u0627\u064a\u0632 \u062a\u0628\u0642\u0649 \u0645\u0634 \u0644\u0648\u062d\u062f\u0643 \u0648\u0633\u0639\u064a\u062f"
line_2b = "\u0648\u062a\u062a\u0648\u0627\u0635\u0644 \u0645\u0639 \u0646\u0627\u0633 \u0632\u064a\u0643\u061f"
line_3 = "\u064a\u0628\u0642\u0649 \u0644\u0627\u0632\u0645 \u062a\u062c\u0631\u0628 SUGO!"

ass = f'''[Script Info]\nScriptType: v4.00+\nPlayResX: 720\nPlayResY: 1280\nWrapStyle: 2\nScaledBorderAndShadow: yes\n\n[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\nStyle: SourceArabic,Noto Sans Arabic,46,&H00FDB804,&H00FDB804,&H00000000,&H00000000,-1,0,0,0,100,100,0,0,1,5,0,5,20,20,20,1\n\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\nDialogue: 0,0:00:00.00,0:00:03.24,SourceArabic,,0,0,0,,{{\\an5\\pos(360,578)}}{line_1}\nDialogue: 0,0:00:03.24,0:00:06.48,SourceArabic,,0,0,0,,{{\\an5\\pos(360,578)}}{line_2a}\\N{line_2b}\nDialogue: 0,0:00:06.48,0:00:06.80,SourceArabic,,0,0,0,,{{\\an5\\pos(360,546)}}{line_3}\n'''
ASS.write_text(ass, encoding="utf-8")

subprocess.run([
    "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
    "-i", str(SOURCE),
    "-vf", "fps=30,trim=start=0:end=6.8,setpts=PTS-STARTPTS,ass=analysis/live_subtitles.ass:fontsdir='C\\:/Windows/Fonts'",
    "-af", "atrim=start=0:end=6.8,asetpts=PTS-STARTPTS",
    "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p",
    "-c:a", "aac", "-ar", "48000", "-ac", "2", "-t", "6.8", str(OUTPUT)
], cwd=str(RUN), check=True)
print(ASS)
print(OUTPUT)
