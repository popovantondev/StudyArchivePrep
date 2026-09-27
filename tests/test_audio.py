import json
import os
import shutil
import struct
import tempfile
import unittest
from pathlib import Path
import wave

from study_archive_prep.audio import (
    AudioOperationCancelled,
    AudioProcessingError,
    AudioStreamSelectionRequired,
    extract_audio_lossless,
    output_suffix,
    probe_media,
)


class AudioTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary.name)
        self.input = self.base / "source.mkv"
        self.input.write_bytes(b"not a real media file; fake tools provide metadata")
        self.ffprobe = self.base / "ffprobe"
        self.ffmpeg = self.base / "ffmpeg"
        self.log = self.base / "ffmpeg-args.jsonl"
        self._write_tools()

    def tearDown(self):
        self.temporary.cleanup()

    def _write_tools(self):
        ffprobe_script = '''#!/usr/bin/env python3
import json, pathlib, sys
path = pathlib.Path(sys.argv[-1])
if "-show_entries" in sys.argv:
    streams = [{"codec_type": "audio"}] if path.suffix == ".m4a" else [{"codec_type": "video"}, {"codec_type": "audio"}, {"codec_type": "audio"}]
else:
    if path.suffix == ".m4a":
        streams = [{"index": 0, "codec_type": "audio", "codec_name": "aac", "channels": 2, "sample_rate": "48000", "duration": "2.5", "tags": {"language": "de", "title": "Main"}}]
    else:
        streams = [{"index": 0, "codec_type": "video", "codec_name": "h264"},
                   {"index": 1, "codec_type": "audio", "codec_name": "aac", "channels": 2, "sample_rate": "48000", "duration": "2.5", "tags": {"language": "de", "title": "Main"}},
                   {"index": 2, "codec_type": "audio", "codec_name": "aac", "channels": 1, "sample_rate": "44100", "duration": "2.5", "tags": {"language": "ru", "title": "Alternative"}}]
print(json.dumps({"streams": streams, "format": {"duration": "2.5"}}))
'''
        ffmpeg_script = '''#!/usr/bin/env python3
import json, os, pathlib, sys, time
args = sys.argv[1:]
with open(os.environ["AUDIO_TEST_LOG"], "a", encoding="utf-8") as log:
    log.write(json.dumps(args) + "\\n")
if "-f" in args and args[args.index("-f") + 1] == "null":
    sys.exit(0)
pathlib.Path(args[-1]).write_bytes(b"losslessly copied audio packets")
print("out_time_ms=1000000", flush=True)
print("progress=continue", flush=True)
if os.environ.get("AUDIO_TEST_SLEEP"):
    time.sleep(5)
'''
        self.ffprobe.write_text(ffprobe_script)
        self.ffmpeg.write_text(ffmpeg_script)
        self.ffprobe.chmod(0o755)
        self.ffmpeg.chmod(0o755)
        os.environ["AUDIO_TEST_LOG"] = str(self.log)

    def test_probe_returns_stream_indexes_labels_and_duration(self):
        result = probe_media(self.input, self.ffprobe)
        self.assertEqual(result.duration_seconds, 2.5)
        self.assertEqual([item.index for item in result.audio_streams], [1, 2])
        self.assertEqual(result.audio_streams[0].language, "de")
        self.assertEqual(result.audio_streams[1].title, "Alternative")
        self.assertIn("ru", result.audio_streams[1].label)

    def test_probe_uses_matroska_audio_duration_tag_before_container_duration(self):
        self.ffprobe.write_text('''#!/usr/bin/env python3
import json
print(json.dumps({"streams": [{"index": 1, "codec_type": "audio", "codec_name": "aac",
    "tags": {"DURATION": "00:00:05.023000000"}}], "format": {"duration": "6.5"}}))
''')
        self.ffprobe.chmod(0o755)
        result = probe_media(self.input, self.ffprobe)
        self.assertEqual(result.audio_streams[0].duration_seconds, 5.023)

    def test_multiple_audio_tracks_require_an_explicit_choice(self):
        with self.assertRaises(AudioStreamSelectionRequired) as caught:
            extract_audio_lossless(self.input, self.base / "out" / "lesson", ffmpeg_path=self.ffmpeg,
                                   ffprobe_path=self.ffprobe)
        self.assertEqual(len(caught.exception.streams), 2)
        self.assertFalse((self.base / "out").exists())

    def test_extraction_uses_stream_copy_and_preserves_selected_codec(self):
        output = self.base / "out" / "lesson"
        progress = []
        result = extract_audio_lossless(self.input, output, stream_index=2,
                                        ffmpeg_path=self.ffmpeg, ffprobe_path=self.ffprobe,
                                        progress=progress.append)
        self.assertEqual(Path(result.output_path).suffix, ".m4a")
        self.assertEqual(result.stream_index, 2)
        self.assertEqual(result.codec, "aac")
        self.assertEqual(Path(result.output_path).read_bytes(), b"losslessly copied audio packets")
        commands = [json.loads(line) for line in self.log.read_text().splitlines()]
        self.assertEqual(commands[0][commands[0].index("-map") + 1], "0:2")
        self.assertEqual(commands[0][commands[0].index("-c:a") + 1], "copy")
        self.assertEqual(commands[0][-1].split(".")[-1], "m4a")
        self.assertIn("-f", commands[1])
        self.assertTrue(progress)
        self.assertTrue(self.input.exists())

    def test_existing_audio_output_is_never_overwritten(self):
        output = self.base / "out" / "lesson.m4a"
        output.parent.mkdir()
        output.write_bytes(b"keep")
        with self.assertRaises(AudioProcessingError):
            extract_audio_lossless(self.input, self.base / "out" / "lesson", stream_index=1,
                                   ffmpeg_path=self.ffmpeg, ffprobe_path=self.ffprobe)
        self.assertEqual(output.read_bytes(), b"keep")

    def test_cancellation_removes_partial_output_and_keeps_source(self):
        os.environ["AUDIO_TEST_SLEEP"] = "1"
        try:
            with self.assertRaises(AudioOperationCancelled):
                extract_audio_lossless(self.input, self.base / "out" / "lesson", stream_index=1,
                                       ffmpeg_path=self.ffmpeg, ffprobe_path=self.ffprobe,
                                       cancelled=lambda: True)
        finally:
            os.environ.pop("AUDIO_TEST_SLEEP", None)
        self.assertTrue(self.input.exists())
        self.assertFalse(list((self.base / "out").glob(".study-audio-*")))
        self.assertFalse((self.base / "out" / "lesson.m4a").exists())

    def test_missing_audio_streams_and_bad_indexes_fail_closed(self):
        with self.assertRaises(AudioProcessingError):
            extract_audio_lossless(self.input, self.base / "out" / "lesson", stream_index=99,
                                   ffmpeg_path=self.ffmpeg, ffprobe_path=self.ffprobe)

    def test_codec_suffixes_choose_containers_without_transcoding(self):
        self.assertEqual(output_suffix("aac"), ".m4a")
        self.assertEqual(output_suffix("alac"), ".m4a")
        self.assertEqual(output_suffix("pcm_s16le"), ".wav")
        self.assertEqual(output_suffix("opus"), ".opus")
        self.assertEqual(output_suffix("unknown"), ".mka")

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"),
                         "real FFmpeg tools are not installed in this development environment")
    def test_real_ffmpeg_stream_copy_preserves_pcm_samples(self):
        source = self.base / "tone.wav"
        expected_samples = [int(12000 * ((index % 80) / 80 - 0.5)) for index in range(8000)]
        with wave.open(str(source), "wb") as stream:
            stream.setnchannels(1)
            stream.setsampwidth(2)
            stream.setframerate(8000)
            stream.writeframes(b"".join(struct.pack("<h", value) for value in expected_samples))
        actual_tools = shutil.which("ffmpeg"), shutil.which("ffprobe")
        result = extract_audio_lossless(source, self.base / "real-out" / "tone",
                                        ffmpeg_path=actual_tools[0], ffprobe_path=actual_tools[1])
        with wave.open(result.output_path, "rb") as stream:
            actual = list(struct.unpack("<" + "h" * stream.getnframes(), stream.readframes(stream.getnframes())))
        self.assertEqual(actual, expected_samples)

    def test_opt_in_deletion_fingerprint_covers_unchanged_source_and_output(self):
        import hashlib
        original = self.input.read_bytes()
        before = self.input.stat()
        result = extract_audio_lossless(self.input, self.base / "hashed-out" / "lesson",
                                        stream_index=1, ffmpeg_path=self.ffmpeg,
                                        ffprobe_path=self.ffprobe, capture_source_hash=True)
        self.assertEqual(result.source_sha256, hashlib.sha256(original).hexdigest())
        self.assertEqual(result.source_size, before.st_size)
        self.assertEqual(result.source_mtime_ns, before.st_mtime_ns)
        self.assertEqual(result.output_sha256,
                         hashlib.sha256(Path(result.output_path).read_bytes()).hexdigest())


if __name__ == "__main__":
    unittest.main()
