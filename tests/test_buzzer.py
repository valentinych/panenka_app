import unittest

from app import create_app
from app.routes import LOBBIES, LOBBY_CODE_LENGTH


LOGIN_CODE = "888"
PASSWORD_CODE = "6969"


class BuzzerFlowTestCase(unittest.TestCase):
    def setUp(self):
        LOBBIES.clear()
        self.app = create_app()
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()
        with self.client:
            self.client.post(
                "/",
                data={"login": LOGIN_CODE, "password": PASSWORD_CODE},
            )

    def tearDown(self):
        LOBBIES.clear()

    def test_host_can_create_lobby(self):
        response = self.client.post("/buzzer/create", follow_redirects=False)
        self.assertEqual(response.status_code, 302)
        self.assertIn("/buzzer/host/", response.headers["Location"])

        code = response.headers["Location"].rstrip("/").rsplit("/", 1)[-1]
        self.assertEqual(len(code), LOBBY_CODE_LENGTH)
        self.assertIn(code, LOBBIES)

        with self.client:
            state_response = self.client.get(f"/buzzer/api/lobbies/{code}/state")
            self.assertEqual(state_response.status_code, 200)
            payload = state_response.get_json()
            self.assertEqual(payload["code"], code)
            self.assertTrue(payload["buzz_open"])

    def test_host_landing_page_renders_after_creation(self):
        response = self.client.post("/buzzer/create", follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Lobby", response.data)
        self.assertIn(b"Buzzers open", response.data)

    def test_host_without_token_gets_redirected(self):
        response = self.client.post("/buzzer/create", follow_redirects=False)
        code = response.headers["Location"].rstrip("/").rsplit("/", 1)[-1]

        with self.client.session_transaction() as sess:
            sess.clear()

        with self.client:
            self.client.post(
                "/",
                data={"login": LOGIN_CODE, "password": PASSWORD_CODE},
            )
            host_response = self.client.get(
                f"/buzzer/host/{code}", follow_redirects=False
            )
            self.assertEqual(host_response.status_code, 302)
            self.assertIn("/buzzer", host_response.headers["Location"])

            redirected = self.client.get(f"/buzzer/host/{code}", follow_redirects=True)
            self.assertEqual(redirected.status_code, 200)
            self.assertIn(b"You&#39;re not hosting this lobby.", redirected.data)

    def test_host_can_rejoin_with_token(self):
        response = self.client.post("/buzzer/create", follow_redirects=False)
        code = response.headers["Location"].rstrip("/").rsplit("/", 1)[-1]
        lobby = LOBBIES[code]
        host_token = lobby["host_token"]

        with self.client.session_transaction() as sess:
            sess.clear()

        with self.client:
            self.client.post(
                "/",
                data={"login": LOGIN_CODE, "password": PASSWORD_CODE},
            )
            rejoin_response = self.client.get(
                f"/buzzer/host/{code}?token={host_token}", follow_redirects=False
            )
            self.assertEqual(rejoin_response.status_code, 200)
            state_response = self.client.get(f"/buzzer/api/lobbies/{code}/state")
            self.assertEqual(state_response.status_code, 200)

    def test_player_can_join_and_buzz(self):
        response = self.client.post("/buzzer/create", follow_redirects=False)
        code = response.headers["Location"].rstrip("/").rsplit("/", 1)[-1]

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
                data={"code": code, "display_name": "Player One"},
                follow_redirects=False,
            )
            self.assertEqual(join_response.status_code, 302)
            lobby = LOBBIES[code]
            self.assertEqual(len(lobby["players"]), 1)

            buzz_response = player_client.post(f"/buzzer/api/lobbies/{code}/buzz")
            self.assertEqual(buzz_response.status_code, 200)
            payload = buzz_response.get_json()
            self.assertIn(payload["status"], {"ok", "already"})
            self.assertEqual(lobby["buzz_order"], list(lobby["players"].keys()))

        with self.client:
            reset_response = self.client.post(f"/buzzer/api/lobbies/{code}/reset")
            self.assertEqual(reset_response.status_code, 200)
            state_response = self.client.get(f"/buzzer/api/lobbies/{code}/state")
            state_payload = state_response.get_json()
            self.assertEqual(state_payload["buzz_queue"], [])
            self.assertTrue(state_payload["buzz_open"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
