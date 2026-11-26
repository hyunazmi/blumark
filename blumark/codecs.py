from __future__ import annotations

from dataclasses import dataclass

X26X_PRESETS = (
    "ultrafast", "superfast", "veryfast", "faster", "fast",
    "medium", "slow", "slower", "veryslow",
)
NVENC_PRESETS = tuple(f"p{number}" for number in range(1, 8))
RESOLUTION_STEPS = (4320, 2160, 1440, 1080, 720, 480, 360, 240, 144)
AUDIO_MODES = ("encode", "copy", "none")
DEFAULT_AUDIO = "encode"
DEFAULT_CONTAINER = "mp4"
DEFAULT_CODEC = "libx264"


@dataclass(frozen=True)
class Container:
    key: str
    label: str
    ext: str
    muxer: str
    audio_encoder: str
    audio_label: str
    audio_bitrate: str
    faststart: bool
    copy_audio: tuple[str, ...] = ()


@dataclass(frozen=True)
class Codec:
    key: str
    label: str
    containers: tuple[str, ...]
    speed_flag: str
    speeds: tuple[str, ...]
    default_speed: str
    q_flag: str
    q_name: str
    q_min: int
    q_max: int
    q_default: int
    extra: tuple[str, ...] = ()
    hvc1: bool = False


CONTAINERS: dict[str, Container] = {
    container.key: container
    for container in (
        Container(
            "mp4", "MP4 (.mp4)", ".mp4", "mp4", "aac", "AAC", "192k", True,
            ("aac", "mp3", "ac3", "eac3", "alac", "opus", "flac"),
        ),
        Container("mkv", "MKV (.mkv)", ".mkv", "matroska", "aac", "AAC", "192k", False),
        Container(
            "webm", "WebM (.webm)", ".webm", "webm", "libopus", "Opus", "160k", False,
            ("opus", "vorbis"),
        ),
        Container(
            "mov", "MOV (.mov)", ".mov", "mov", "aac", "AAC", "192k", True,
            ("aac", "mp3", "ac3", "eac3", "alac", "pcm_s16le", "pcm_s24le"),
        ),
    )
}


def _descending(first: int) -> tuple[str, ...]:
    return tuple(str(number) for number in range(first, -1, -1))


def _nvenc(key: str, label: str, containers: tuple[str, ...], hvc1: bool = False) -> Codec:
    return Codec(
        key, label, containers, "-preset", NVENC_PRESETS, "p5", "-cq", "CQ", 0, 51, 20,
        extra=("-rc", "vbr", "-b:v", "0"), hvc1=hvc1,
    )


CODECS: dict[str, Codec] = {
    codec.key: codec
    for codec in (
        Codec(
            "libx264", "H.264 (x264)", ("mp4", "mkv", "mov"),
            "-preset", X26X_PRESETS, "medium", "-crf", "CRF", 0, 51, 18,
        ),
        Codec(
            "libx265", "H.265 / HEVC (x265)", ("mp4", "mkv", "mov"),
            "-preset", X26X_PRESETS, "medium", "-crf", "CRF", 0, 51, 20,
            extra=("-x265-params", "log-level=error"), hvc1=True,
        ),
        Codec(
            "libsvtav1", "AV1 (SVT-AV1)", ("mp4", "mkv", "webm"),
            "-preset", _descending(13), "8", "-crf", "CRF", 0, 63, 28,
        ),
        Codec(
            "libaom-av1", "AV1 (libaom)", ("mp4", "mkv", "webm"),
            "-cpu-used", _descending(8), "6", "-crf", "CRF", 0, 63, 28,
            extra=("-b:v", "0", "-row-mt", "1"),
        ),
        Codec(
            "libvpx-vp9", "VP9 (libvpx)", ("webm", "mkv"),
            "-cpu-used", _descending(5), "2", "-crf", "CRF", 0, 63, 28,
            extra=("-b:v", "0", "-row-mt", "1", "-deadline", "good"),
        ),
        _nvenc("h264_nvenc", "H.264 (NVIDIA NVENC)", ("mp4", "mkv", "mov")),
        _nvenc("hevc_nvenc", "H.265 / HEVC (NVIDIA NVENC)", ("mp4", "mkv", "mov"), hvc1=True),
        _nvenc("av1_nvenc", "AV1 (NVIDIA NVENC)", ("mp4", "mkv")),
    )
}


def even_floor(value: int) -> int:
    return max(2, value - value % 2)


def output_size(width: int, height: int, target: int) -> tuple[int, int]:
    short_side = min(width, height)
    if target <= 0 or target >= short_side:
        return even_floor(width), even_floor(height)
    scale = target / short_side
    return max(2, round(width * scale / 2) * 2), max(2, round(height * scale / 2) * 2)


def resolution_choices(width: int, height: int) -> list[tuple[int, str]]:
    short_side = min(width, height)
    choices = [(0, f"Original ({short_side}p, {width}x{height})")]
    for target in RESOLUTION_STEPS:
        if target < short_side:
            scaled_width, scaled_height = output_size(width, height, target)
            choices.append((target, f"{target}p ({scaled_width}x{scaled_height})"))
    return choices


def compatible_codecs(container_key: str, available: frozenset[str] | None = None) -> list[Codec]:
    return [
        codec
        for codec in CODECS.values()
        if container_key in codec.containers and (available is None or codec.key in available)
    ]


@dataclass(frozen=True)
class ExportOptions:
    container: str = DEFAULT_CONTAINER
    codec: str = DEFAULT_CODEC
    speed: str = CODECS[DEFAULT_CODEC].default_speed
    quality: int = CODECS[DEFAULT_CODEC].q_default
    audio: str = DEFAULT_AUDIO
    target: int = 0

    def validated(self) -> ExportOptions:
        container = self.container if self.container in CONTAINERS else DEFAULT_CONTAINER
        codec = CODECS.get(self.codec)
        if codec is None or container not in codec.containers:
            fallback = compatible_codecs(container)
            codec = fallback[0] if fallback else CODECS[DEFAULT_CODEC]
        replaced = codec.key != self.codec
        speed = self.speed if self.speed in codec.speeds and not replaced else codec.default_speed
        try:
            quality = codec.q_default if replaced else int(self.quality)
        except (TypeError, ValueError):
            quality = codec.q_default
        quality = max(codec.q_min, min(codec.q_max, quality))
        audio = self.audio if self.audio in AUDIO_MODES else DEFAULT_AUDIO
        try:
            target = max(0, int(self.target))
        except (TypeError, ValueError):
            target = 0
        return ExportOptions(container, codec.key, speed, quality, audio, target)

    @property
    def container_info(self) -> Container:
        return CONTAINERS[self.container]

    @property
    def codec_info(self) -> Codec:
        return CODECS[self.codec]

    def required_encoders(self) -> list[str]:
        encoders = [self.codec]
        if self.audio == "encode":
            encoders.append(self.container_info.audio_encoder)
        return encoders


def video_args(options: ExportOptions) -> list[str]:
    codec = options.codec_info
    args = [
        "-c:v", codec.key,
        codec.speed_flag, options.speed,
        codec.q_flag, str(options.quality),
        *codec.extra,
        "-pix_fmt", "yuv420p",
    ]
    if codec.hvc1 and options.container in ("mp4", "mov"):
        args += ["-tag:v", "hvc1"]
    return args


def audio_args(options: ExportOptions) -> list[str]:
    if options.audio == "none":
        return ["-an"]
    if options.audio == "copy":
        return ["-c:a", "copy"]
    container = options.container_info
    return ["-c:a", container.audio_encoder, "-b:a", container.audio_bitrate, "-af", "apad"]


def container_args(options: ExportOptions) -> list[str]:
    container = options.container_info
    args = ["-f", container.muxer]
    if container.faststart:
        args += ["-movflags", "+faststart"]
    return args
