"""Shared application state passed between workflow pages."""

from __future__ import annotations

from dataclasses import dataclass, field

from ..core.image import AstroImage
from ..grade.metrics import FrameQuality
from ..ingest.session import DwarfSession


@dataclass
class AppState:
    session: DwarfSession | None = None
    dark_session: DwarfSession | None = None
    qualities: list[FrameQuality] = field(default_factory=list)
    accepted_paths: list = field(default_factory=list)
    stacked: AstroImage | None = None
    # processing undo stack: [0] is the stack result, [-1] is current
    edits: list = field(default_factory=list)

    @property
    def current(self) -> AstroImage | None:
        if self.edits:
            return self.edits[-1]
        return self.stacked

    def push_edit(self, img: AstroImage, cap: int = 12):
        self.edits.append(img)
        while len(self.edits) > cap:
            self.edits.pop(0)

    def undo(self) -> AstroImage | None:
        if len(self.edits) > 1:
            self.edits.pop()
        elif self.edits:
            self.edits.pop()
        return self.current

    def reset_edits(self):
        self.edits = [self.stacked.copy()] if self.stacked else []
