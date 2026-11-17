"""Export quality options and presets."""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Optional


@dataclass
class EncryptionOptions:
    user_password: str = ""
    owner_password: str = ""
    allow_print: bool = True
    allow_copy: bool = True
    allow_modify: bool = True
    allow_annotate: bool = True


@dataclass
class ExportOptions:
    # --- image rewriting (lossy) ---
    downsample: bool = False
    dpi_target: int = 150          # images above dpi_threshold are resampled to this
    dpi_threshold: int = 225       # usually 1.5 * dpi_target
    recompress: bool = False       # re-encode images as JPEG
    jpeg_quality: int = 85         # 1..100
    include_lossless_images: bool = True   # also convert PNG-like images to JPEG
    include_bitonal_images: bool = False   # black & white scans (risky for legibility)
    # --- lossless optimization ---
    garbage: int = 3               # 0..4  (4 also merges duplicate streams)
    deflate: bool = True
    deflate_images: bool = True
    deflate_fonts: bool = True
    clean: bool = False            # sanitize content streams
    use_objstms: bool = True       # pack objects into object streams (smaller xref)
    # --- content ---
    sanitize: bool = False         # drop links, forms, JavaScript, attachments, XMP metadata
    # --- security ---
    encryption: Optional[EncryptionOptions] = None

    @property
    def rewrites_images(self) -> bool:
        return self.downsample or self.recompress

    def to_dict(self) -> dict:
        d = asdict(self)
        d.pop("encryption")   # never persist passwords
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "ExportOptions":
        known = {k: v for k, v in d.items() if k in cls.__dataclass_fields__ and k != "encryption"}
        opts = cls()
        for k, v in known.items():
            default = getattr(opts, k)
            try:
                if isinstance(default, bool):
                    v = v if isinstance(v, bool) else str(v).lower() in ("1", "true", "yes")
                elif isinstance(default, int):
                    v = int(v)
            except (TypeError, ValueError):
                continue
            setattr(opts, k, v)
        return opts


# preset key -> (dpi_target or None, jpeg quality or None)
PRESETS: dict[str, tuple[Optional[int], Optional[int]]] = {
    "original": (None, None),
    "print": (300, 90),
    "ebook": (150, 80),
    "screen": (72, 60),
}
PRESET_ORDER = ["original", "print", "ebook", "screen", "custom"]


def apply_preset(opts: ExportOptions, preset: str) -> ExportOptions:
    """Return a copy of ``opts`` with the image settings of ``preset``.

    Lossless optimization and encryption settings are preserved.
    """
    if preset not in PRESETS:
        return opts
    dpi, quality = PRESETS[preset]
    new = ExportOptions(**{**asdict(opts), "encryption": opts.encryption})
    if dpi is None:
        new.downsample = False
        new.recompress = False
    else:
        new.downsample = True
        new.dpi_target = dpi
        new.dpi_threshold = int(dpi * 1.5)
        new.recompress = True
        new.jpeg_quality = quality
    return new


def detect_preset(opts: ExportOptions) -> str:
    for key, (dpi, quality) in PRESETS.items():
        if dpi is None:
            if not opts.rewrites_images:
                return key
        elif (opts.downsample and opts.recompress and opts.dpi_target == dpi
              and opts.dpi_threshold == int(dpi * 1.5) and opts.jpeg_quality == quality):
            return key
    return "custom"
