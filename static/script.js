/* ─────────────────────────────────────────────────────────────────────────────
   NexBid — Frontend Script
   Handles: Countdown timers, AJAX bid placement, toast notifications
───────────────────────────────────────────────────────────────────────────── */

'use strict';

// ─── Countdown Timers ─────────────────────────────────────────────────────────

function parseDateUTC(dateStr) {
  // SQLite stores as "YYYY-MM-DD HH:MM:SS" — treat as UTC
  if (!dateStr) return null;
  const normalized = dateStr.replace(' ', 'T') + (dateStr.includes('Z') ? '' : 'Z');
  const d = new Date(normalized);
  return isNaN(d.getTime()) ? null : d;
}

function formatCountdown(ms) {
  if (ms <= 0) return { text: 'CLOSED', urgent: true };
  const s = Math.floor(ms / 1000);
  const days  = Math.floor(s / 86400);
  const hours = Math.floor((s % 86400) / 3600);
  const mins  = Math.floor((s % 3600) / 60);
  const secs  = s % 60;

  if (days > 0) return { text: `${days}d ${hours}h ${mins}m`, urgent: false };
  if (hours > 0) return { text: `${hours}h ${mins}m ${secs}s`, urgent: hours < 1 };
  const urgent = s < 300; // < 5 mins
  const timeStr = `${String(mins).padStart(2,'0')}:${String(secs).padStart(2,'0')}`;
  return { text: timeStr, urgent };
}

function initCountdownTimers() {
  const timers = document.querySelectorAll('[data-expires]');
  if (!timers.length) return;

  function tick() {
    const now = Date.now();
    timers.forEach(el => {
      const expires = parseDateUTC(el.dataset.expires);
      if (!expires) { el.textContent = 'Invalid date'; return; }

      const remaining = expires.getTime() - now;
      const { text, urgent } = formatCountdown(remaining);

      el.textContent = text;
      el.classList.toggle('urgent', urgent);

      // If just closed, reload page cards to update status
      if (remaining <= 0 && !el.dataset.closed) {
        el.dataset.closed = '1';
        const card = el.closest('.auction-card');
        if (card) {
          const overlay = document.createElement('div');
          overlay.className = 'closed-overlay';
          overlay.innerHTML = '<span>AUCTION CLOSED</span>';
          overlay.style.cssText = `
            position:absolute;inset:0;background:rgba(0,0,0,0.6);
            display:flex;align-items:center;justify-content:center;
            font-weight:800;font-size:1rem;letter-spacing:0.1em;
            color:#fca5a5;border-radius:16px;backdrop-filter:blur(4px);
          `;
          card.style.position = 'relative';
          card.appendChild(overlay);
        }
      }
    });
  }

  tick();
  setInterval(tick, 1000);
  
  // Also poll for price updates every 5 seconds on detail page
  const bidForm = document.getElementById('bid-form');
  if (bidForm) {
    const itemId = bidForm.dataset.itemId;
    const priceDisplay = document.getElementById('current-price-display');
    const bidInput     = document.getElementById('bid-amount');

    setInterval(async () => {
      try {
        const res = await fetch(`/api/item/${itemId}/status`);
        const data = await res.json();
        if (data.current_price && priceDisplay) {
          const newPrice = `₹${data.current_price.toFixed(2)}`;
          if (priceDisplay.textContent !== newPrice) {
            priceDisplay.textContent = newPrice;
            priceDisplay.style.animation = 'none';
            priceDisplay.offsetHeight; // reflow
            priceDisplay.style.animation = 'priceFlash 0.6s ease';
            
            // Update min bid if user is not currently typing
            if (bidInput && document.activeElement !== bidInput) {
              bidInput.min = (data.current_price + 0.01).toFixed(2);
              bidInput.placeholder = `Min: ₹${(data.current_price + 0.01).toFixed(2)}`;
            }
          }
        }
      } catch (err) {
        console.error('Price poll error:', err);
      }
    }, 5000);
  }
}

// ─── Toast Notifications ──────────────────────────────────────────────────────

let toastTimer = null;

function showToast(message, type = 'success') {
  let toast = document.getElementById('bid-toast');
  if (!toast) {
    toast = document.createElement('div');
    toast.id = 'bid-toast';
    toast.className = 'bid-result-toast';
    document.body.appendChild(toast);
  }

  toast.textContent = message;
  toast.className = `bid-result-toast ${type} show`;

  if (toastTimer) clearTimeout(toastTimer);
  toastTimer = setTimeout(() => {
    toast.classList.remove('show');
  }, 4000);
}

// ─── AJAX Bid Placement ───────────────────────────────────────────────────────

function initBidForm() {
  const bidForm = document.getElementById('bid-form');
  if (!bidForm) return;

  const priceDisplay = document.getElementById('current-price-display');
  const bidInput     = document.getElementById('bid-amount');
  const submitBtn    = document.getElementById('bid-submit-btn');
  const hashDisplay  = document.getElementById('latest-hash');

  bidForm.addEventListener('submit', async (e) => {
    e.preventDefault();

    const itemId = bidForm.dataset.itemId;
    const amount = parseFloat(bidInput.value);

    if (!amount || amount <= 0) {
      showToast('Please enter a valid bid amount.', 'error');
      return;
    }

    submitBtn.disabled = true;
    submitBtn.textContent = 'Placing Bid...';

    try {
      const res = await fetch('/bid', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ item_id: itemId, amount })
      });

      const data = await res.json();

      if (data.success) {
        showToast(`✓ Bid of ₹${amount.toFixed(2)} placed!`, 'success');

        // Update price display without reload
        if (priceDisplay) {
          priceDisplay.textContent = `₹${data.new_price.toFixed(2)}`;
          priceDisplay.style.animation = 'none';
          priceDisplay.offsetHeight; // reflow
          priceDisplay.style.animation = 'priceFlash 0.6s ease';
        }

        // Show hash
        if (hashDisplay && data.hash) {
          hashDisplay.textContent = data.hash;
          hashDisplay.parentElement.style.display = 'block';
        }

        bidInput.value = '';

        // Add to bid history table live
        addBidRow(data.new_price, amount);

      } else {
        showToast(data.message || 'Bid failed.', 'error');
      }

    } catch (err) {
      showToast('Network error. Please try again.', 'error');
      console.error(err);
    } finally {
      submitBtn.disabled = false;
      submitBtn.textContent = 'Place Bid →';
    }
  });

  // Min bid hint
  if (bidInput && priceDisplay) {
    bidInput.addEventListener('focus', () => {
      const current = parseFloat(priceDisplay.textContent.replace(/[^0-9.]/g, ''));
      if (!isNaN(current)) {
        bidInput.min = (current + 0.01).toFixed(2);
        bidInput.placeholder = `Min: ₹${(current + 0.01).toFixed(2)}`;
      }
    });
  }
}

function addBidRow(newPrice, amount) {
  const tbody = document.getElementById('bid-history-tbody');
  if (!tbody) return;
  const row = document.createElement('tr');
  row.style.animation = 'fadeSlideDown 0.5s ease';
  row.innerHTML = `
    <td><strong>You</strong></td>
    <td>₹${amount.toFixed(2)}</td>
    <td>Just now</td>
  `;
  tbody.insertBefore(row, tbody.firstChild);
}

// ─── Image fallback ───────────────────────────────────────────────────────────
function initImageFallbacks() {
  document.querySelectorAll('img.auction-img').forEach(img => {
    img.addEventListener('error', () => {
      img.style.display = 'none';
      const parent = img.parentElement;
      if (parent) parent.innerHTML = '<span style="font-size:3rem">🏷️</span>';
    });
  });
}

// ─── Admin: Confirm Deletes ───────────────────────────────────────────────────
function initConfirmForms() {
  document.querySelectorAll('[data-confirm]').forEach(btn => {
    btn.addEventListener('click', e => {
      if (!confirm(btn.dataset.confirm)) e.preventDefault();
    });
  });
}

// ─── Price flash animation ────────────────────────────────────────────────────
const priceStyle = document.createElement('style');
priceStyle.textContent = `
  @keyframes priceFlash {
    0%   { color: #6ee7b7; transform: scale(1.1); }
    100% { color: white;   transform: scale(1); }
  }
  @keyframes fadeSlideDown {
    from { opacity:0; transform:translateY(-12px); }
    to   { opacity:1; transform:translateY(0); }
  }
`;
document.head.appendChild(priceStyle);

// ─── Init ─────────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  initCountdownTimers();
  initBidForm();
  initImageFallbacks();
  initConfirmForms();

  // Auto-dismiss flash messages
  document.querySelectorAll('.flash').forEach(el => {
    setTimeout(() => {
      el.style.transition = '0.5s';
      el.style.opacity = '0';
      setTimeout(() => el.remove(), 500);
    }, 5000);
  });
});