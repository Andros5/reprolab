# The ReproLab demo video

A 101-second motion piece (1920×1080, 30 fps), with no voice-over. Every trace, number and verdict on screen comes from real runs of ReproLab. The music is “Ethereal” by Amarent, under CC BY 4.0.

The explanations sit in a band of their own at the bottom of the frame, so they never cover what the viewer has to see.

## Rebuild it

```bash
# 1. Data, from real runs. Use the CitaLab environment to include the re-execution results.
.venv-citalab/Scripts/python -m examples.video_data video/src/data.json

# 2. Music (needs numpy): download the track first (see below), then prepare and check it
python -m venv video/sound/.venv
video/sound/.venv/Scripts/python -m pip install -r video/sound/requirements.txt
video/sound/.venv/Scripts/python video/sound/prepare.py    # verifies, trims, fades, levels -> video/public/score.wav
video/sound/.venv/Scripts/python video/sound/analyze.py    # length, level, fade, gaps, balance, spectrogram

# 3. Picture and sound
cd video && npm install && npx remotion render ReproLab out/reprolab-demo.mp4 --crf=18 --audio-bitrate=256k
```

`npx remotion studio` opens an interactive preview.

## The music

[“Ethereal”](https://freemusicarchive.org/music/amarent/free-atmospheric-music/ethereal-2) by Amarent, from the album *Free Atmospheric Music*, licensed under [Creative Commons Attribution 4.0](https://creativecommons.org/licenses/by/4.0/). It is a slowly evolving instrumental ambient piece. On Free Music Archive it had about 2,700 plays when chosen, and its page says it is not AI-generated.

How it was chosen:
- **Candidates:** three tracks by human composers with an open licence, avoiding the most-used free libraries.
- **Excluded licences:** NC, ND and SA, because setting music to a video counts as an adaptation.
- **The comparison:** level stability, pulse, tonal balance and spectrogram. It preferred this track over a darker, more percussive one that had drops in level.

Download the MP3 from the track page into `video/sound/source/amarent-ethereal.mp3`; it is not committed. `sound/prepare.py` checks that it is the exact file that was reviewed (SHA-256), then makes the changes that the credit declares:
- it uses the first 1:41 of the piece;
- it fades the piece out over the last 4 seconds;
- it sets the level to −19 LUFS, so the music stays in the background.

The video credits the track in its closing frame.

`sound/analyze.py` checks the result:
- the length matches the picture and there is no clipping;
- the level suits a background;
- there are no holes under the picture and the fade reaches silence;
- the tonal balance is neither boomy nor harsh.

It also draws a spectrogram and a loudness envelope, with the chapter boundaries marked.

## Licences

The video is built with [Remotion](https://www.remotion.dev). Remotion is free for individuals and small teams; larger companies need a company licence. Fonts are IBM Plex, under the SIL Open Font License, loaded through `@remotion/google-fonts`. Music: “Ethereal” by Amarent, CC BY 4.0, trimmed, faded and levelled for this video.
