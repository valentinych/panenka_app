# Panenka Live Prototype

This repository contains a lightweight prototype inspired by [buzzin.live](https://buzzin.live/) where players can sign into pre-provisioned accounts before accessing the buzzer dashboard.

## Features

- Modern landing page reminiscent of BuzzIn's sleek lobby aesthetic.
- Login form that validates three-digit logins and four-digit passcodes.
- Server-side verification of credentials stored in a local `auth.json` file (not committed to version control).
- Placeholder dashboard ready for upcoming buzzer, lobby, and scoreboard functionality.

## Getting started

1. Create and activate a virtual environment (optional but recommended).
2. Install dependencies:

   ```bash
   pip install -r requirements.txt
   ```

3. Create an `auth.json` file in the project root with the following structure:

   ```json
   {
     "users": [
      { "login": "123", "password": "4567", "name": "Alex Morgan" },
      { "login": "234", "password": "5678", "name": "Jordan Smith" }
     ]
   }
   ```

   - Logins must be exactly three digits.
   - Passwords must be exactly four digits.
   - `name` is displayed on the dashboard and should include the player's first and last name.

4. Run the development server:

   ```bash
   flask --app run:app --debug run
   ```

   or

   ```bash
   python run.py
   ```

5. Open [http://localhost:5000](http://localhost:5000) in your browser and sign in with one of the configured accounts.

## Next steps

- Implement the real-time buzzer interactions.
- Add host-controlled game lobbies.
- Persist player stats and scores.

Feel free to extend this prototype as needed for future functionality.
