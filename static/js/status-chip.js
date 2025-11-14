(() => {
  function getCsrf() {
    const meta = document.querySelector('meta[name="csrf-token"]');
    const token = meta ? meta.getAttribute('content') : '';
    console.log('CSRF token found:', token ? 'yes' : 'no');
    return token;
  }

  function setChipState(chip, status) {
    chip.dataset.status = status;
    chip.classList.toggle('is-done', status === 'done');
    chip.classList.toggle('is-scheduled', status === 'scheduled');
    const label = status === 'done' ? (chip.dataset.labelDone || 'Done') : (chip.dataset.labelScheduled || 'Scheduled');
    chip.textContent = label;
    chip.setAttribute('aria-pressed', status === 'done' ? 'true' : 'false');
  }

  function setToggleState(toggle, status) {
    toggle.dataset.status = status;
    toggle.querySelectorAll('[data-status-choice]').forEach((btn) => {
      const active = btn.dataset.statusChoice === status;
      btn.classList.toggle('is-active', active);
      btn.setAttribute('aria-pressed', active ? 'true' : 'false');
    });
  }

  async function updateStatus(targetEl, desiredStatus) {
    console.log('updateStatus called', targetEl, desiredStatus);
    const toggle = targetEl.classList && targetEl.classList.contains('status-toggle') ? targetEl : targetEl.closest('.status-toggle');
    const control = toggle || targetEl;
    if (!control) return;
    const apptId = control.dataset ? control.dataset.apptId : null;
    const endpoint =
      (control.dataset && control.dataset.statusUrl) ||
      (typeof control.getAttribute === 'function' ? control.getAttribute('action') : null) ||
      (apptId ? `/appointments/${apptId}/status` : null);
    if (!endpoint) return;

    const currentRaw = (toggle ? toggle.dataset.status : control.dataset.status) || 'scheduled';
    const current = currentRaw === 'done' ? 'done' : 'scheduled';
    const next = desiredStatus || (current === 'done' ? 'scheduled' : 'done');
    if (desiredStatus && next === current) return;

    if (control.dataset.saving === '1') return;
    control.dataset.saving = '1';

    if (toggle) {
      toggle.classList.add('saving');
      setToggleState(toggle, next);
    } else {
      control.classList.add('saving');
      setChipState(control, next);
    }

    try {
      const token = getCsrf();
      const nextField = toggle ? toggle.querySelector('input[name="next"]') : null;
      const nextParam = nextField && nextField.value ? `&next=${encodeURIComponent(nextField.value)}` : '';
      const res = await fetch(endpoint, {
        method: 'POST',
        credentials: 'same-origin',
        headers: {
          'Content-Type': 'application/x-www-form-urlencoded;charset=UTF-8',
          'X-CSRFToken': token,
          'Accept': 'application/json'
        },
        body: `status=${encodeURIComponent(next)}&csrf_token=${encodeURIComponent(token)}${nextParam}`
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok || !data.ok) throw new Error(data.error || 'save_failed');
      const finalStatus = data.status || next;
      if (toggle) {
        setToggleState(toggle, finalStatus === 'done' ? 'done' : 'scheduled');
      } else {
        setChipState(control, finalStatus === 'done' ? 'done' : 'scheduled');
      }
    } catch (e) {
      console.warn('AJAX status update failed, falling back to form submission:', e);
      // Fallback to traditional form submission
      if (toggle) {
        setToggleState(toggle, current);
        toggle.classList.add('error');
        setTimeout(() => toggle.classList.remove('error'), 1500);
      } else {
        setChipState(control, current);
        control.classList.add('error');
        setTimeout(() => control.classList.remove('error'), 1500);
      }

      // Try to submit the form traditionally
      const form = control.tagName === 'FORM' ? control : control.querySelector('form');
      if (form) {
        // Update the hidden status input
        const statusInput = form.querySelector('input[name="status"]');
        if (statusInput) {
          statusInput.value = next;
        }
        // Submit the form
        form.submit();
        return;
      }
    } finally {
      control.dataset.saving = '';
      if (toggle) {
        toggle.classList.remove('saving');
      } else {
        control.classList.remove('saving');
      }
    }
  }

  document.addEventListener('click', (e) => {
    console.log('Click detected', e.target);
    const option = e.target.closest('[data-status-choice]');
    if (option) {
      console.log('Status option clicked', option);
      e.preventDefault();
      const container = option.closest('.status-toggle');
      if (!container) return;
      const targetStatus = option.dataset.statusChoice;
      updateStatus(container, targetStatus);
      return;
    }
    const chip = e.target.closest('.status-chip[data-appt-id]');
    if (!chip) return;
    if (chip.closest('.status-toggle')) return;
    e.preventDefault();
    updateStatus(chip);
  });
})();
