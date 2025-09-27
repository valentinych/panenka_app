# Panenka Live Prototype

This repository contains a lightweight prototype inspired by [buzzin.live](https://buzzin.live/) where players can sign into pre-provisioned accounts before accessing the buzzer dashboard.

## Features

- Modern landing page reminiscent of BuzzIn's sleek lobby aesthetic.
- Login form that validates three-digit logins and four-digit passcodes.
- Server-side verification of credentials stored in a local `auth.json` file (not committed to version control) or the `AUTH_JSON` environment variable for hosted deployments.
- Placeholder dashboard ready for upcoming buzzer, lobby, and scoreboard functionality.

## Getting started

1. Create and activate a virtual environment (optional but recommended).
2. Install dependencies:

   ```bash
   pip install -r requirements.txt
   ```

3. Provide credentials via one of the supported methods:

   - **Environment variable (recommended for production):** set `AUTH_JSON` to a JSON payload that follows the structure below. This is the preferred approach for Heroku so credentials are kept out of the repository.
   - **Local file:** create an `auth.json` file in the project root with the following structure:

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

   - **Amazon S3 or remote URL:**
     - Set the `AUTH_JSON_S3_BUCKET` environment variable to the bucket name that contains `auth.json`. If the object key is
       not `auth.json`, set `AUTH_JSON_S3_KEY` accordingly. The application will download the file at startup using your
       configured AWS credentials (for example, `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY`).
     - Alternatively, set `AUTH_JSON_S3_URI` (for example, `s3://my-bucket/path/to/auth.json`) or `AUTH_JSON_URL`
       (`https://my-bucket.s3.amazonaws.com/auth.json`) if you prefer to provide the location as a single value. When
       `AUTH_JSON_URL` is used, the file is downloaded over HTTPS, which is useful for public buckets that do not require
       AWS credentials.

   If no credentials source is configured, the application falls back to a built-in demo
   account (`888` / `6969`) so the interface remains usable in hosted environments. You
   should still provide your own credentials for production deployments.

4. Run the development server:

   ```bash
   flask --app run:app --debug run
   ```

   or

   ```bash
   python run.py
   ```

5. Open [http://localhost:5000](http://localhost:5000) in your browser and sign in with one of the configured accounts.

## Importing project questions

The trivia questions that power the in-game rounds are stored in the same SQLite
database as the lobby data. Because binary database files are not tracked in
the repository, you should populate your local database by running the importer
script once after setting up the project:

```bash
python -m app.question_importer
```

The script downloads every season from the shared Google Sheet, normalizes the
fields, and replaces the contents of the `questions` table. A fresh
`app/lobbies.sqlite3` file will be created automatically if it does not already
exist.

## Deploying to Heroku

The project is configured for the [Heroku Python buildpack](https://devcenter.heroku.com/articles/getting-started-with-python). The steps below assume you already have the [Heroku CLI](https://devcenter.heroku.com/articles/heroku-cli) installed and are logged in.

1. Create the application once (or reuse an existing one):

   ```bash
   heroku apps:create panenka-live-prototype
   ```

   Replace `panenka-live-prototype` with the actual name of your app or skip this step if it already exists.

2. Configure the secret key and player credentials as environment variables:

   ```bash
   heroku config:set SECRET_KEY="change-me" \
                     AUTH_JSON='{"users":[{"login":"123","password":"4567","name":"Alex Morgan"}]}'
   ```

   The JSON value can include as many user entries as needed.

3. Add the Heroku Git remote (replace the app name if needed):

   ```bash
   heroku git:remote -a panenka-live-prototype
   ```

4. Deploy the code:

   ```bash
   git push heroku main
   ```

   Heroku will detect the Python project, install dependencies from `requirements.txt`, use `runtime.txt` to pin the Python version, and run the `web` process specified in `Procfile` (`gunicorn run:app`).

5. Once the build succeeds, open the app:

   ```bash
   heroku open
   ```

6. Monitor logs as needed:

   ```bash
   heroku logs --tail
   ```

These steps cover a full manual deployment from your local environment. Subsequent updates can be deployed with `git push heroku main` after committing changes.

## Next steps

- Implement the real-time buzzer interactions.
- Add host-controlled game lobbies.
- Persist player stats and scores.

Feel free to extend this prototype as needed for future functionality.
