import unittest
from unittest import mock

from app.routes import (
    LOBBIES,
    PLAYER_EXPIRATION_SECONDS,
    _expire_stale_lobbies,
    _expire_stale_players,
)


class BuzzerExpirationTestCase(unittest.TestCase):
    def setUp(self):
        LOBBIES.clear()

    def tearDown(self):
        LOBBIES.clear()

    def test_expire_stale_players_removes_from_roster_and_queue(self):
        code = "ABCD"
        stale_player_id = "player-1"
        lobby = {
            "code": code,
            "host_id": "host-1",
            "host_name": "Host",
            "host_token": "token",
            "created_at": 0,
            "updated_at": 0,
            "host_seen": 0,
            "locked": False,
            "players": {
                stale_player_id: {
                    "id": stale_player_id,
                    "name": "Player",
                    "joined_at": 0,
                    "last_seen": -PLAYER_EXPIRATION_SECONDS - 5,
                    "buzzed_at": None,
                }
            },
            "buzz_order": [stale_player_id],
        }

        _expire_stale_players(lobby, 0)

        self.assertEqual(lobby["players"], {})
        self.assertEqual(lobby["buzz_order"], [])
        self.assertEqual(lobby["updated_at"], 0)

    def test_expire_stale_lobbies_removes_expired_entries(self):
        active_code = "WXYZ"
        stale_code = "STAL"
        now = 1_000_000

        LOBBIES[active_code] = {
            "code": active_code,
            "host_id": "host-active",
            "host_name": "Host",
            "host_token": "token",
            "created_at": now,
            "updated_at": now,
            "host_seen": now,
            "locked": False,
            "players": {},
            "buzz_order": [],
        }

        LOBBIES[stale_code] = {
            "code": stale_code,
            "host_id": "host-stale",
            "host_name": "Host",
            "host_token": "token",
            "created_at": 0,
            "updated_at": -1,
            "host_seen": -1,
            "locked": False,
            "players": {},
            "buzz_order": [],
        }

        with mock.patch(
            "app.routes.time.time", return_value=now + PLAYER_EXPIRATION_SECONDS
        ):
            _expire_stale_lobbies()

        self.assertIn(active_code, LOBBIES)
        self.assertNotIn(stale_code, LOBBIES)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
