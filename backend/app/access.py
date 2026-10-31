"""Access policy for client data. Pure functions: no I/O, no app imports."""
from dataclasses import dataclass
from typing import Literal

Role = Literal["client", "trainer", "admin"]
LinkStatus = Literal["requested", "active", "declined", "ended"] | None


@dataclass(frozen=True)
class Viewer:
    id: str
    role: Role


def can_read_client_data(viewer: Viewer, client_id: str, link_status: LinkStatus) -> bool:
    # Owner sees their own data regardless of link state. Admins get no
    # implicit read access; trainers only while the link is active.
    if viewer.id == client_id:
        return True
    return viewer.role == "trainer" and link_status == "active"


def can_write_own(viewer: Viewer, owner_id: str) -> bool:
    return viewer.id == owner_id
