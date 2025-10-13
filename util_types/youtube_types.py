from typing import TypedDict, Literal, Any, Callable

class FFmpegExtractAudioPP(TypedDict, total=False):
    key: Literal["FFmpegExtractAudio"]
    preferredcodec: Literal["mp3", "aac", "vorbis", "opus", "m4a"]
    preferredquality: str  # "192" и т.п.

class YdlParams(TypedDict, total=False):
    format: str
    noplaylist: bool
    default_search: Literal["ytsearch", "ytsearch1", "ytsearch10"]
    quiet: bool
    outtmpl: str
    postprocessors: list[FFmpegExtractAudioPP]
    progress_hooks: list[Callable[[dict[str, Any]], None]]