#!/usr/bin/env bash
set -euo pipefail

APP_NAME=${HEROKU_APP_NAME:-""}
LOCAL_BRANCH=${HEROKU_DEPLOY_BRANCH:-""}
REMOTE_BRANCH=${HEROKU_REMOTE_BRANCH:-"main"}
COMMIT_MESSAGE=""
AUTO_CONFIRM=0
SKIP_COMMIT=0

print_usage() {
  local default_branch_display=${LOCAL_BRANCH:-"(current branch)"}
  cat <<USAGE
Usage: $0 [options]

Options:
  -a, --app NAME        Override the Heroku app name (defaults to HEROKU_APP_NAME env or detected remote)
  -b, --branch NAME     Git branch to push from (default: ${default_branch_display})
  -r, --remote-branch NAME  Remote branch on Heroku (default: ${REMOTE_BRANCH})
  -m, --message TEXT    Commit message to use when uncommitted changes are present
      --no-commit       Skip auto committing local changes (script will abort if dirty)
  -y, --yes             Run without interactive confirmations
  -h, --help            Show this help message and exit
USAGE
}

info() { printf "\033[1;36m[INFO]\033[0m %s\n" "$1"; }
success() { printf "\033[1;32m[SUCCESS]\033[0m %s\n" "$1"; }
warn() { printf "\033[1;33m[WARN]\033[0m %s\n" "$1"; }
error() { printf "\033[1;31m[ERROR]\033[0m %s\n" "$1"; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    -a|--app)
      APP_NAME="$2"
      shift 2
      ;;
    -b|--branch)
      LOCAL_BRANCH="$2"
      shift 2
      ;;
    -r|--remote-branch)
      REMOTE_BRANCH="$2"
      shift 2
      ;;
    -m|--message)
      COMMIT_MESSAGE="$2"
      shift 2
      ;;
    --no-commit)
      SKIP_COMMIT=1
      shift
      ;;
    -y|--yes)
      AUTO_CONFIRM=1
      shift
      ;;
    -h|--help)
      print_usage
      exit 0
      ;;
    *)
      error "Unknown argument: $1"
      echo
      print_usage
      exit 1
      ;;
  esac
done

if ! command -v git >/dev/null 2>&1; then
  error "git is required. Install git and retry."
  exit 1
fi

if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  error "This command must be run inside a git repository."
  exit 1
fi

if [[ -z "$LOCAL_BRANCH" ]]; then
  LOCAL_BRANCH=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "main")
fi

if ! command -v heroku >/dev/null 2>&1; then
  error "Heroku CLI not found. Install it from https://devcenter.heroku.com/articles/heroku-cli"
  exit 1
fi

HEROKU_USER=$(heroku auth:whoami 2>/dev/null || true)
if [[ -z "$HEROKU_USER" ]]; then
  error "You are not logged into the Heroku CLI. Run 'heroku login' and try again."
  exit 1
fi
info "Heroku CLI authenticated as ${HEROKU_USER}."

if git remote get-url heroku >/dev/null 2>&1; then
  REMOTE_URL=$(git remote get-url heroku)
  APP_FROM_REMOTE=$(basename "${REMOTE_URL%.git}")
  if [[ -z "$APP_NAME" ]]; then
    APP_NAME="$APP_FROM_REMOTE"
  fi
else
  if [[ -z "$APP_NAME" ]]; then
    error "Heroku remote not configured. Provide --app NAME or set HEROKU_APP_NAME."
    exit 1
  fi
  info "Configuring 'heroku' git remote for app ${APP_NAME}..."
  heroku git:remote -a "$APP_NAME"
fi

if [[ -z "$APP_NAME" ]]; then
  error "Unable to determine Heroku app name."
  exit 1
fi

info "Preparing to deploy branch '${LOCAL_BRANCH}' to Heroku app '${APP_NAME}' (remote branch '${REMOTE_BRANCH}')."

GIT_STATUS=$(git status --porcelain)
if [[ -n "$GIT_STATUS" ]]; then
  if [[ $SKIP_COMMIT -eq 1 ]]; then
    error "Uncommitted changes detected but --no-commit was supplied. Commit manually and rerun."
    echo "$GIT_STATUS"
    exit 1
  fi

  if [[ -z "$COMMIT_MESSAGE" ]]; then
    if [[ $AUTO_CONFIRM -eq 1 ]]; then
      COMMIT_MESSAGE="Magic deploy $(date '+%Y-%m-%d %H:%M:%S')"
    else
      echo
      warn "Uncommitted changes detected:"
      echo "$GIT_STATUS"
      echo
      read -r -p "Enter commit message [Magic deploy $(date '+%Y-%m-%d %H:%M:%S')]: " USER_MESSAGE
      if [[ -n "$USER_MESSAGE" ]]; then
        COMMIT_MESSAGE="$USER_MESSAGE"
      else
        COMMIT_MESSAGE="Magic deploy $(date '+%Y-%m-%d %H:%M:%S')"
      fi
    fi
  fi

  info "Committing local changes..."
  git add -A
  git commit -m "$COMMIT_MESSAGE"
else
  info "Working tree clean."
fi

echo
info "Syncing with origin/${LOCAL_BRANCH}..."
if git fetch origin >/dev/null 2>&1; then
  if git rev-parse --verify "origin/${LOCAL_BRANCH}" >/dev/null 2>&1; then
    LOCAL_HASH=$(git rev-parse HEAD)
    REMOTE_HASH=$(git rev-parse "origin/${LOCAL_BRANCH}")
    if [[ "$LOCAL_HASH" != "$REMOTE_HASH" ]]; then
      info "Merging latest changes from origin/${LOCAL_BRANCH}..."
      git pull origin "$LOCAL_BRANCH" --no-edit
    else
      info "Already up to date with origin/${LOCAL_BRANCH}."
    fi
  else
    warn "origin/${LOCAL_BRANCH} does not exist. Skipping auto-merge."
  fi
else
  warn "Unable to fetch origin. Continuing with local branch."
fi

echo
info "Pushing to Heroku..."
if git push heroku "${LOCAL_BRANCH}:${REMOTE_BRANCH}"; then
  success "Deployment finished!"
else
  error "git push to Heroku failed."
  exit 1
fi

echo
info "Top Heroku dyno status:"
heroku ps -a "$APP_NAME" || warn "Unable to retrieve dyno status."

echo
info "Recent Heroku release info:"
heroku releases:info -a "$APP_NAME" | head -n 20 || warn "Unable to retrieve release info."

echo
success "Magic Heroku deploy complete for ${APP_NAME}."
info "Use 'heroku logs --tail -a ${APP_NAME}' to stream logs if needed."
