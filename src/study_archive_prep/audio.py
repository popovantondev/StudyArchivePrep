"""FFprobe inspection and lossless single-track FFmpeg extraction."""
from __future__ import annotations

import json
import hashlib
import os
import selectors
import shutil
import signal
import stat
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


class AudioProcessingError(RuntimeError):
    """A media file could not be inspected or safely stream-copied."""


class AudioStreamSelectionRequired(AudioProcessingError):
    def __init__(self, streams: tuple["AudioStream", ...]):
        super().__init__("Choose an audio track before extraction.")
        self.streams = streams


class AudioOperationCancelled(AudioProcessingError):
    """The extraction was stopped before the output was installed."""


@dataclass(frozen=True)
class AudioStream:
    index: int
    codec: str
    channels: int | None
    sample_rate: int | None
    language: str | None
    title: str | None
    duration_seconds: float | None

    @property
    def label(self) -> str:
        details = [f"Audio {self.index}: {self.codec}"]
        if self.channels:
            details.append(f"{self.channels} ch")
        if self.sample_rate:
            details.append(f"{self.sample_rate} Hz")
        if self.language:
            details.append(self.language)
        if self.title:
            details.append(self.title)
        return " · ".join(details)


@dataclass(frozen=True)
class MediaInfo:
    path: str
    duration_seconds: float | None
    audio_streams: tuple[AudioStream, ...]


@dataclass(frozen=True)
class AudioExtractionResult:
    output_path: str
    stream_index: int
    codec: str
    duration_seconds: float | None
    size: int
    output_sha256: str
    source_size: int
    source_mtime_ns: int
    source_sha256: str | None


_SUFFIXES = {
    "aac": ".m4a",
    "alac": ".m4a",
    "mp3": ".mp3",
    "opus": ".opus",
    "vorbis": ".ogg",
    "flac": ".flac",
    "ac3": ".mka",
    "eac3": ".mka",
    "dts": ".mka",
    "truehd": ".mka",
}


def output_suffix(codec: str) -> str:
    if codec.startswith("pcm_"):
        return ".wav"
    return _SUFFIXES.get(codec.casefold(), ".mka")


def _optional_int(value) -> int | None:
    try:
        parsed = int(value)
        return parsed if parsed > 0 else None
    except (TypeError, ValueError):
        return None


def _optional_duration(value) -> float | None:
    try:
        parsed = float(value)
        return parsed if parsed >= 0 else None
    except (TypeError, ValueError):
        return None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _resolve_tool(value: str | Path | None, bundled_name: str) -> str:
    if value is not None:
        path = Path(value).expanduser()
        if path.is_file() and os.access(path, os.X_OK):
            return str(path)
        raise AudioProcessingError(f"The configured {bundled_name} tool is unavailable.")
    bundled = Path(__file__).parent / "tools" / bundled_name
    if bundled.is_file() and os.access(bundled, os.X_OK):
        return str(bundled)
    found = shutil.which(bundled_name)
    if found:
        return found
    raise AudioProcessingError(f"{bundled_name} is not installed. Add the bundled media tools to the app.")


def probe_media(path: str | Path, ffprobe_path: str | Path | None = None) -> MediaInfo:
    source = Path(path).expanduser()
    try:
        metadata = source.lstat()
    except OSError as exc:
        raise AudioProcessingError("The media source is unavailable.") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise AudioProcessingError("The media source must be a regular file, not a link.")
    ffprobe = _resolve_tool(ffprobe_path, "ffprobe")
    command = [ffprobe, "-v", "error", "-show_streams", "-show_format", "-of", "json", str(source)]
    try:
        completed = subprocess.run(command, capture_output=True, text=True, timeout=180, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise AudioProcessingError("FFprobe could not inspect this media file.") from exc
    if completed.returncode != 0:
        raise AudioProcessingError("FFprobe could not read the media container.")
    try:
        payload = json.loads(completed.stdout)
        streams = payload.get("streams", [])
        format_duration = _optional_duration(payload.get("format", {}).get("duration"))
        audio_streams = []
        for stream in streams:
            if stream.get("codec_type") != "audio":
                continue
            index = stream.get("index")
            codec = stream.get("codec_name")
            if not isinstance(index, int) or index < 0 or not isinstance(codec, str) or not codec:
                raise ValueError("incomplete stream metadata")
            tags = stream.get("tags") or {}
            audio_streams.append(AudioStream(
                index=index,
                codec=codec,
                channels=_optional_int(stream.get("channels")),
                sample_rate=_optional_int(stream.get("sample_rate")),
                language=tags.get("language") if isinstance(tags.get("language"), str) else None,
                title=tags.get("title") if isinstance(tags.get("title"), str) else None,
                duration_seconds=_optional_duration(stream.get("duration")) or format_duration,
            ))
        if not isinstance(streams, list):
            raise ValueError("stream list is invalid")
    except (json.JSONDecodeError, AttributeError, TypeError, ValueError) as exc:
        raise AudioProcessingError("FFprobe returned invalid media information.") from exc
    return MediaInfo(str(source), format_duration, tuple(audio_streams))


def _run_ffmpeg(command: list[str], cancelled: Callable[[], bool] | None,
                progress: Callable[[float | None], None] | None = None,
                duration: float | None = None) -> None:
    try:
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                   bufsize=0, close_fds=True)
    except OSError as exc:
        raise AudioProcessingError("FFmpeg could not be started.") from exc
    assert process.stdout is not None
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ)
    pending = b""
    output_time: float | None = None
    messages: list[str] = []
    try:
        while process.poll() is None:
            if cancelled is not None and cancelled():
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
                raise AudioOperationCancelled("Audio extraction was cancelled.")
            for key, _ in selector.select(timeout=0.2):
                chunk = os.read(key.fd, 8192)
                if not chunk:
                    continue
                pending += chunk
                while b"\n" in pending:
                    raw, pending = pending.split(b"\n", 1)
                    line = raw.decode("utf-8", errors="replace").strip()
                    if line.startswith("out_time_ms="):
                        try:
                            output_time = int(line.split("=", 1)[1]) / 1_000_000
                        except ValueError:
                            pass
                        if progress is not None:
                            progress(min(output_time / duration, 1.0) if duration else None)
                    elif line and not line.startswith(("frame=", "fps=", "bitrate=", "total_size=", "out_time=", "dup_frames=", "drop_frames=", "speed=", "progress=")):
                        messages.append(line[-1000:])
        remaining = process.stdout.read()
        pending += remaining or b""
        if pending.strip():
            messages.append(pending.decode("utf-8", errors="replace")[-1000:])
        return_code = process.wait()
    finally:
        selector.close()
        process.stdout.close()
        if process.poll() is None:
            process.kill()
            process.wait()
    if return_code != 0:
        detail = " ".join(messages).strip()
        raise AudioProcessingError("FFmpeg failed to copy the audio stream." + (f" {detail}" if detail else ""))


def _install_without_overwrite(temporary: Path, destination: Path) -> None:
    if destination.exists() or destination.is_symlink():
        raise AudioProcessingError("The audio output already exists; it was not overwritten.")
    try:
        os.link(temporary, destination)
        temporary.unlink(missing_ok=True)
        directory_fd = os.open(destination.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except FileExistsError as exc:
        raise AudioProcessingError("The audio output appeared during extraction; it was not overwritten.") from exc
    except OSError as exc:
        raise AudioProcessingError("The checked audio could not be installed safely.") from exc


def extract_audio_lossless(input_path: str | Path, output_stem: str | Path,
                           stream_index: int | None = None,
                           ffmpeg_path: str | Path | None = None,
                           ffprobe_path: str | Path | None = None,
                           cancelled: Callable[[], bool] | None = None,
                           progress: Callable[[float | None], None] | None = None,
                           capture_source_hash: bool = False) -> AudioExtractionResult:
    """Copy one selected stream without encoding, validate it, then install it."""
    source = Path(input_path).expanduser()
    try:
        source_stat = source.lstat()
    except OSError as exc:
        raise AudioProcessingError("The media source is unavailable.") from exc
    source_info = probe_media(source, ffprobe_path)
    try:
        after_probe = source.lstat()
    except OSError as exc:
        raise AudioProcessingError("The source changed while FFprobe was inspecting it.") from exc
    if (after_probe.st_size, after_probe.st_mtime_ns) != (source_stat.st_size, source_stat.st_mtime_ns):
        raise AudioProcessingError("The source changed while FFprobe was inspecting it.")
    source_digest = _sha256(source) if capture_source_hash else None
    if capture_source_hash:
        current = source.lstat()
        if (current.st_size, current.st_mtime_ns) != (source_stat.st_size, source_stat.st_mtime_ns):
            raise AudioProcessingError("The source changed while its deletion fingerprint was being recorded.")
    if not source_info.audio_streams:
        raise AudioProcessingError("This file has no audio streams.")
    if stream_index is None:
        if len(source_info.audio_streams) > 1:
            raise AudioStreamSelectionRequired(source_info.audio_streams)
        selected = source_info.audio_streams[0]
    else:
        selected = next((item for item in source_info.audio_streams if item.index == stream_index), None)
        if selected is None:
            raise AudioProcessingError("The selected audio track is not present in the source.")

    destination_stem = Path(output_stem).expanduser()
    destination = destination_stem.with_suffix(output_suffix(selected.codec))
    if destination.parent.is_symlink():
        raise AudioProcessingError("The audio output folder must not be a symbolic link.")
    destination = destination.parent.resolve(strict=False) / destination.name
    if destination.resolve(strict=False) == source.resolve(strict=False):
        raise AudioProcessingError("The audio output cannot replace the source recording.")
    if destination.exists() or destination.is_symlink():
        raise AudioProcessingError("The audio output already exists; it was not overwritten.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=".study-audio-", suffix=destination.suffix,
                                          dir=destination.parent)
    os.close(fd)
    temporary = Path(temporary_name)
    temporary.unlink()
    ffmpeg = _resolve_tool(ffmpeg_path, "ffmpeg")
    copy_command = [ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error", "-i", str(source),
                    "-map", f"0:{selected.index}", "-vn", "-sn", "-dn", "-c:a", "copy",
                    "-map_metadata", "0", "-progress", "pipe:1", "-nostats", str(temporary)]
    try:
        _run_ffmpeg(copy_command, cancelled, progress, selected.duration_seconds)
        if not temporary.exists() or temporary.stat().st_size <= 0:
            raise AudioProcessingError("FFmpeg did not produce a usable audio file.")
        after_source = source.lstat()
        if (after_source.st_size, after_source.st_mtime_ns) != (source_stat.st_size, source_stat.st_mtime_ns):
            raise AudioProcessingError("The source changed during audio extraction.")
        if capture_source_hash and _sha256(source) != source_digest:
            raise AudioProcessingError("The source contents changed during audio extraction.")
        extracted = probe_media(temporary, ffprobe_path)
        if len(extracted.audio_streams) != 1:
            raise AudioProcessingError("The output does not contain exactly one audio track.")
        if extracted.audio_streams[0].codec.casefold() != selected.codec.casefold():
            raise AudioProcessingError("The output codec changed; stream copy was not preserved.")
        if _probe_stream_types(temporary, ffprobe_path) != ("audio",):
            raise AudioProcessingError("The output contains an unexpected non-audio stream.")
        if selected.duration_seconds is not None and extracted.duration_seconds is not None:
            tolerance = max(1.0, selected.duration_seconds * 0.01)
            if abs(selected.duration_seconds - extracted.duration_seconds) > tolerance:
                raise AudioProcessingError("The extracted audio duration differs from the selected track.")
        verify_command = [ffmpeg, "-nostdin", "-hide_banner", "-v", "error", "-i", str(temporary),
                          "-map", "0:a:0", "-f", "null", "-"]
        _run_ffmpeg(verify_command, cancelled)
        if cancelled is not None and cancelled():
            raise AudioOperationCancelled("Audio extraction was cancelled.")
        output_digest = _sha256(temporary)
        _install_without_overwrite(temporary, destination)
        return AudioExtractionResult(str(destination), selected.index, selected.codec,
                                     selected.duration_seconds, destination.stat().st_size,
                                     output_digest, source_stat.st_size, source_stat.st_mtime_ns,
                                     source_digest)
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def _probe_stream_types(path: Path, ffprobe_path: str | Path | None) -> tuple[str, ...]:
    ffprobe = _resolve_tool(ffprobe_path, "ffprobe")
    command = [ffprobe, "-v", "error", "-show_entries", "stream=codec_type", "-of", "json", str(path)]
    try:
        completed = subprocess.run(command, capture_output=True, text=True, timeout=180, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise AudioProcessingError("FFprobe could not verify output streams.") from exc
    if completed.returncode != 0:
        raise AudioProcessingError("FFprobe could not verify output streams.")
    try:
        streams = json.loads(completed.stdout).get("streams", [])
        return tuple(stream.get("codec_type", "") for stream in streams)
    except (json.JSONDecodeError, AttributeError, TypeError) as exc:
        raise AudioProcessingError("FFprobe returned invalid output stream information.") from exc
