"""HLS Rendition profiles."""

from dataclasses import dataclass


@dataclass(frozen=True)
class RenditionConfig:
    label: str
    height: int
    crf: int
    audio_bitrate: str
    bandwidth: int
    resolution: str


RENDITIONS: dict[str, RenditionConfig] = {
    "360p": RenditionConfig(
        label="360p",
        height=360,
        crf=24,
        audio_bitrate="64k",
        bandwidth=800000,
        resolution="640x360",
    ),
    "480p": RenditionConfig(
        label="480p",
        height=480,
        crf=22,
        audio_bitrate="96k",
        bandwidth=1400000,
        resolution="842x480",
    ),
    "720p": RenditionConfig(
        label="720p",
        height=720,
        crf=20,
        audio_bitrate="128k",
        bandwidth=2800000,
        resolution="1280x720",
    ),
    "1080p": RenditionConfig(
        label="1080p",
        height=1080,
        crf=18,
        audio_bitrate="192k",
        bandwidth=5000000,
        resolution="1920x1080",
    ),
}

RENDITION_ORDER = ["360p", "480p", "720p", "1080p"]


def get_sorted_renditions(labels: list[str]) -> list[RenditionConfig]:
    """Return RenditionConfig list ordered by resolution ascending."""
    return [RENDITIONS[label] for label in RENDITION_ORDER if label in labels and label in RENDITIONS]

