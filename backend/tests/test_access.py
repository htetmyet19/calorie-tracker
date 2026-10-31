"""Access policy for client data."""
import pytest

from app.access import Viewer, can_read_client_data, can_write_own

CLIENT = "client-1"
OWNER = Viewer(id=CLIENT, role="client")
TRAINER = Viewer(id="trainer-1", role="trainer")
ADMIN = Viewer(id="admin-1", role="admin")
STRANGER = Viewer(id="stranger-1", role="client")

LINKS = [None, "requested", "active", "declined", "ended"]


@pytest.mark.parametrize("link", LINKS)
@pytest.mark.parametrize(
    "viewer, expected",
    [
        (OWNER, lambda link: True),
        (TRAINER, lambda link: link == "active"),
        (ADMIN, lambda link: False),
        (STRANGER, lambda link: False),
    ],
    ids=["owner", "trainer", "admin", "stranger"],
)
def test_read_matrix(viewer, expected, link):
    assert can_read_client_data(viewer, CLIENT, link) is expected(link)


def test_write_only_owner():
    assert can_write_own(OWNER, CLIENT) is True
    assert can_write_own(TRAINER, CLIENT) is False
    assert can_write_own(ADMIN, CLIENT) is False
