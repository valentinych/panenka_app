import unittest

from app import create_app
from app.lobby_store import lobby_store


LOGIN_CODE = "888"
PASSWORD_CODE = "6969"


class GameLobbyViewTestCase(unittest.TestCase):
    def setUp(self):
        lobby_store.clear_all()
        self.app = create_app()
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()
        with self.client:
            self.client.post("/", data={"login": LOGIN_CODE, "password": PASSWORD_CODE})

    def tearDown(self):
        lobby_store.clear_all()

    def test_game_lobby_renders_host_and_join_forms(self):
        response = self.client.get("/game-lobby")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Host a lobby", response.data)
        self.assertIn(b"Join a lobby", response.data)
        self.assertIn(b"name=\"code\"", response.data)

    def test_game_lobby_shows_host_summary_when_active(self):
        create_response = self.client.post("/buzzer/create", follow_redirects=False)
        self.assertEqual(create_response.status_code, 302)

        response = self.client.get("/game-lobby")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"You're hosting", response.data)
        self.assertIn(b"Open host view", response.data)

    def test_game_lobby_shows_player_summary(self):
        host_response = self.client.post("/buzzer/create", follow_redirects=False)
        host_code = host_response.headers["Location"].rstrip("/").rsplit("/", 1)[-1]

        player_app = create_app()
        player_app.config["TESTING"] = True
        player_client = player_app.test_client()

        with player_client:
            player_client.post(
                "/",
                data={"login": LOGIN_CODE, "password": PASSWORD_CODE},
            )
            join_response = player_client.post(
                "/buzzer/join",
                data={"code": host_code, "display_name": "Player One"},
                follow_redirects=False,
            )
            self.assertEqual(join_response.status_code, 302)

            lobby_view = player_client.get("/game-lobby")
            self.assertEqual(lobby_view.status_code, 200)
            self.assertIn(b"You're in a lobby", lobby_view.data)
            self.assertIn(host_code.encode(), lobby_view.data)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
