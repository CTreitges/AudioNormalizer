from audionormalizer.probe import parse_ffmpeg_stream_info, _parse_ffprobe_json


WAV_S16 = """
Input #0, wav, from 'x.wav':
  Duration: 00:03:21.41, bitrate: 1411 kb/s
  Stream #0:0: Audio: pcm_s16le ([1][0][0][0] / 0x0001), 44100 Hz, stereo, s16, 1411 kb/s
"""

FLAC_24 = """
Input #0, flac, from 'y.flac':
  Duration: 00:04:10.00, start: 0.000000, bitrate: 950 kb/s
  Stream #0:0: Audio: flac, 44100 Hz, stereo, s32 (24 bit)
"""

MP3_FILE = """
Input #0, mp3, from 'z.mp3':
  Duration: 00:02:00.00, start: 0.025057, bitrate: 320 kb/s
  Stream #0:0: Audio: mp3, 44100 Hz, stereo, fltp, 320 kb/s
"""

MONO_5_1 = """
  Stream #0:0: Audio: aac, 48000 Hz, 5.1, fltp, 384 kb/s
"""


def test_parse_wav_s16():
    info = parse_ffmpeg_stream_info(WAV_S16)
    assert info.codec_name == "pcm_s16le"
    assert info.sample_rate == 44100
    assert info.channels == 2
    assert info.sample_fmt == "s16"
    assert info.bits_per_sample == 16
    assert info.bit_rate == 1411000
    assert info.duration > 200


def test_parse_flac_24bit():
    info = parse_ffmpeg_stream_info(FLAC_24)
    assert info.codec_name == "flac"
    assert info.sample_rate == 44100
    assert info.channels == 2
    assert info.bits_per_sample == 24      # aus "(24 bit)"
    assert info.sample_fmt == "s32"


def test_parse_mp3_fltp():
    info = parse_ffmpeg_stream_info(MP3_FILE)
    assert info.codec_name == "mp3"
    assert info.bits_per_sample == 32      # fltp -> float 32
    assert info.bit_rate == 320000


def test_parse_5_1_channels():
    info = parse_ffmpeg_stream_info(MONO_5_1)
    assert info.channels == 6


def test_parse_empty_is_safe():
    info = parse_ffmpeg_stream_info("")
    assert info.channels == 0 and info.sample_rate == 0


def test_ffprobe_json():
    j = ('{"streams":[{"codec_name":"flac","channels":2,"sample_rate":"44100",'
         '"bits_per_sample":24,"sample_fmt":"s32","bit_rate":"950000",'
         '"duration":"250.0"}]}')
    info = _parse_ffprobe_json(j)
    assert info.codec_name == "flac"
    assert info.channels == 2
    assert info.sample_rate == 44100
    assert info.bits_per_sample == 24
    assert info.duration == 250.0
