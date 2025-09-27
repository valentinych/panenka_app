(() => {
  const root = document.querySelector('[data-buzzer]');
  if (!root) {
    return;
  }

  const role = root.dataset.role;
  const stateUrl = root.dataset.stateUrl;
  const lockUrl = root.dataset.lockUrl;
  const resetUrl = root.dataset.resetUrl;
  const closeUrl = root.dataset.closeUrl;
  const buzzUrl = root.dataset.buzzUrl;
  const leaveUrl = root.dataset.leaveUrl;
  const leaveRedirect = root.dataset.leaveRedirect;

  const lockIndicator = root.querySelector('[data-lock-indicator]');
  const queueEl = root.querySelector('[data-queue]');
  const rosterEl = root.querySelector('[data-roster]');
  const emptyQueueEl = root.querySelector('[data-empty-queue]');
  const emptyRosterEl = root.querySelector('[data-empty-roster]');
  const statusEl = root.querySelector('[data-status]');
  const lockButton = root.querySelector('[data-lock-button]');
  const resetButton = root.querySelector('[data-reset-button]');
  const closeButton = root.querySelector('[data-close-button]');
  const buzzButton = root.querySelector('[data-buzz-button]');
  const leaveButton = root.querySelector('[data-leave-button]');

  let pollTimer = null;
  let pollInterval = 1500;
  let fetching = false;

  const safeRedirect = () => {
    clearPollingTimer();
    if (leaveRedirect) {
      window.location.href = leaveRedirect;
    }
  };

  const updateVisibility = (el, shouldShow) => {
    if (!el) {
      return;
    }
    el.style.display = shouldShow ? '' : 'none';
  };

  const postJson = async (url) => {
    if (!url) {
      return null;
    }
    try {
      const response = await fetch(url, {
        method: 'POST',
        credentials: 'same-origin',
        headers: {
          'Content-Type': 'application/json',
        },
      });

      if (response.status === 404) {
        safeRedirect();
        return null;
      }

      if (response.status === 403) {
        safeRedirect();
        return null;
      }

      if (!response.ok) {
        return null;
      }

      const contentLength = response.headers.get('content-length');
      if (contentLength === '0') {
        return null;
      }

      const text = await response.text();
      if (!text) {
        return null;
      }

      try {
        return JSON.parse(text);
      } catch (err) {
        return null;
      }
    } catch (error) {
      console.error('Unable to send request', error);
      return null;
    }
  };

  const applyQueue = (queue = []) => {
    if (!queueEl) {
      return;
    }
    queueEl.innerHTML = '';
    if (!queue.length) {
      updateVisibility(queueEl, false);
      updateVisibility(emptyQueueEl, true);
      return;
    }

    updateVisibility(queueEl, true);
    updateVisibility(emptyQueueEl, false);

    queue.forEach((entry) => {
      const item = document.createElement('li');
      const name = document.createElement('span');
      name.textContent = `#${entry.position}`;
      const label = document.createElement('strong');
      label.textContent = entry.name;
      item.appendChild(label);
      item.appendChild(name);
      queueEl.appendChild(item);
    });
  };

  const applyRoster = (players = []) => {
    if (!rosterEl) {
      return;
    }

    rosterEl.innerHTML = '';
    if (!players.length) {
      updateVisibility(rosterEl, false);
      updateVisibility(emptyRosterEl, true);
      return;
    }

    updateVisibility(rosterEl, true);
    updateVisibility(emptyRosterEl, false);

    players.forEach((player) => {
      const item = document.createElement('li');
      item.textContent = player.name;
      if (player.position) {
        const badge = document.createElement('span');
        badge.textContent = `#${player.position}`;
        item.appendChild(badge);
      }
      if (player.buzzed) {
        item.classList.add('is-buzzed');
      }
      if (player.is_self) {
        item.classList.add('is-self');
      }
      rosterEl.appendChild(item);
    });
  };

  const applyState = (state) => {
    if (!state) {
      return;
    }

    root.classList.toggle('is-locked', Boolean(state.locked));

    if (lockIndicator) {
      lockIndicator.textContent = state.locked ? 'Buzzers locked' : 'Buzzers open';
      lockIndicator.classList.toggle('status-pill--locked', Boolean(state.locked));
    }

    applyQueue(state.buzz_queue);
    applyRoster(state.players);

    if (role === 'player' && state.you) {
      if (statusEl) {
        if (typeof state.you.position === 'number') {
          statusEl.textContent = state.you.position === 1
            ? 'You rang in first!'
            : `You are #${state.you.position} in the queue.`;
        } else if (state.buzz_open) {
          statusEl.textContent = 'Buzzers are open!';
        } else if (state.buzz_queue && state.buzz_queue.length) {
          const leader = state.buzz_queue[0];
          statusEl.textContent = `${leader.name} buzzed in first.`;
        } else {
          statusEl.textContent = 'Waiting for buzzers to open…';
        }
      }

      if (buzzButton) {
        const position = typeof state.you.position === 'number' ? state.you.position : null;
        const isLocked = Boolean(state.locked);
        const buttonState = isLocked
          ? 'locked'
          : position
            ? 'queued'
            : 'ready';

        buzzButton.disabled = !state.you.can_buzz;
        buzzButton.dataset.state = buttonState;

        if (isLocked) {
          buzzButton.textContent = 'LOCKED';
        } else if (position) {
          buzzButton.textContent = `#${position}`;
        } else {
          buzzButton.textContent = 'BUZZ!';
        }
      }
    }

    if (role === 'host') {
      if (lockButton) {
        lockButton.textContent = state.locked ? 'Unlock buzzers' : 'Lock buzzers';
      }
      if (resetButton) {
        resetButton.disabled = !state.buzz_queue || !state.buzz_queue.length;
      }
    }
  };

  const fetchState = async () => {
    if (!stateUrl || fetching) {
      return;
    }
    fetching = true;
    try {
      const response = await fetch(stateUrl, {
        method: 'GET',
        credentials: 'same-origin',
        headers: {
          Accept: 'application/json',
        },
      });

      if (response.status === 404 || response.status === 403) {
        safeRedirect();
        return;
      }

      if (!response.ok) {
        return;
      }

      const data = await response.json();
      applyState(data);
    } catch (error) {
      console.error('Unable to refresh lobby state', error);
    } finally {
      fetching = false;
    }
  };

  if (lockButton && lockUrl) {
    lockButton.addEventListener('click', async () => {
      lockButton.disabled = true;
      await postJson(lockUrl);
      lockButton.disabled = false;
      fetchState();
    });
  }

  if (resetButton && resetUrl) {
    resetButton.addEventListener('click', async () => {
      resetButton.disabled = true;
      await postJson(resetUrl);
      resetButton.disabled = false;
      fetchState();
    });
  }

  if (closeButton && closeUrl) {
    closeButton.addEventListener('click', async () => {
      closeButton.disabled = true;
      await postJson(closeUrl);
      safeRedirect();
    });
  }

  const triggerBuzz = async () => {
    if (!buzzButton || !buzzUrl || buzzButton.disabled) {
      return;
    }
    buzzButton.disabled = true;
    await postJson(buzzUrl);
    fetchState();
  };

  if (buzzButton && buzzUrl) {
    buzzButton.addEventListener('click', triggerBuzz);

    if (role === 'player') {
      document.addEventListener('keydown', (event) => {
        const isSpace = event.code === 'Space' || event.key === ' ' || event.key === 'Spacebar';
        const isTypingTarget = ['INPUT', 'TEXTAREA', 'SELECT'].includes(event.target.tagName)
          || event.target.isContentEditable;

        if (!isSpace || isTypingTarget) {
          return;
        }

        event.preventDefault();
        triggerBuzz();
      });
    }
  }

  if (leaveButton && leaveUrl) {
    leaveButton.addEventListener('click', async () => {
      leaveButton.disabled = true;
      await postJson(leaveUrl);
      safeRedirect();
    });
  }

  const clearPollingTimer = () => {
    if (pollTimer) {
      clearInterval(pollTimer);
      pollTimer = null;
    }
  };

  const startPolling = (interval = pollInterval, { immediate = true } = {}) => {
    pollInterval = interval;
    clearPollingTimer();
    if (immediate) {
      fetchState();
    }
    pollTimer = setInterval(fetchState, pollInterval);
  };

  const setPollingInterval = (interval, options) => {
    startPolling(interval, options);
  };

  document.addEventListener('visibilitychange', () => {
    if (document.hidden) {
      setPollingInterval(8000, { immediate: true });
    } else {
      setPollingInterval(1500, { immediate: true });
    }
  });

  startPolling();
})();
