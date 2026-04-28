// deck.js — Trove cassette deck behavior
(function () {
  'use strict';

  const STORAGE_KEY = 'trove-deck';
  const SHELF_LIMIT = 12;

  function readPersisted() {
    try {
      return JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}');
    } catch (_) { return {}; }
  }
  function writePersisted(patch) {
    const cur = readPersisted();
    Object.assign(cur, patch);
    try { localStorage.setItem(STORAGE_KEY, JSON.stringify(cur)); } catch (_) {}
  }

  window.trove = window.trove || {};

  window.trove.deck = function () {
    const persisted = readPersisted();
    return {
      mode: persisted.mode || 'tape',          // 'tape' | 'vinyl'
      status: 'ready',                         // 'ready' | 'load' | 'rec' | 'done' | 'err'
      jobId: null,
      videoTitle: '',
      thumbnail: '',
      formats: [],
      formatId: null,
      counter: '0:00',
      _tickerHandle: null,
      _tickerStart: 0,
      shelf: persisted.shelf || [],
      soundOn: !!persisted.soundOn,
      reducedMotion: window.matchMedia('(prefers-reduced-motion: reduce)').matches,

      init() {
        this._wireHtmxListeners();
        this._wireUnloadCancel();
      },

      _gsap() { return window.gsap || null; },

      _wireHtmxListeners() {
        const target = document.getElementById('card-target');
        if (!target) return;
        target.addEventListener('htmx:afterSwap', () => {
          const card = target.querySelector('[data-card]');
          if (!card) return;
          this._consumeCard(card);
        });
      },

      _consumeCard(card) {
        const status = card.dataset.status;
        if (status === 'error') {
          this.status = 'err';
          this.videoTitle = card.dataset.title || '';
          return;
        }
        if (status === 'ready') {
          this.status = 'load';
          this.videoTitle = card.dataset.title || 'Untitled';
          this.thumbnail = card.dataset.thumbnail || '';
          this.formats = JSON.parse(card.dataset.formats || '[]');
          this.formatId = (this.formats[0] && this.formats[0].id) || null;
          return;
        }
        if (status === 'queued' || status === 'downloading') {
          this.status = 'rec';
          this.jobId = card.dataset.jobId || null;
          return;
        }
        if (status === 'done') {
          this.status = 'done';
          this.jobId = card.dataset.jobId || this.jobId;
          this._addToShelf({
            id: this.jobId,
            title: this.videoTitle,
            filename: card.dataset.filename || '',
            kind: this.mode === 'vinyl' ? 'vinyl' : 'cassette',
          });
          return;
        }
        if (status === 'cancelled') {
          this.status = 'ready';
          return;
        }
      },

      _wireUnloadCancel() {
        window.addEventListener('beforeunload', () => {
          if (this.jobId && this.status === 'rec') {
            try { navigator.sendBeacon('/api/job/' + this.jobId + '/cancel'); } catch (_) {}
          }
        });
      },

      _addToShelf(item) {
        if (!item.id) return;
        // dedupe by id
        this.shelf = this.shelf.filter(s => s.id !== item.id);
        this.shelf.unshift(item);
        if (this.shelf.length > SHELF_LIMIT) this.shelf.length = SHELF_LIMIT;
        writePersisted({ shelf: this.shelf });
      },

      setMode(mode) {
        if (mode !== 'tape' && mode !== 'vinyl' || mode === this.mode) return;
        const tl = this._gsap()?.timeline();
        if (tl && !this.reducedMotion) {
          tl.to('.deck-window', { rotateX: 90, duration: 0.4, ease: 'power2.in' })
            .add(() => { this.mode = mode; })
            .to('.deck-window', { rotateX: 0, duration: 0.4, ease: 'power2.out' });
        } else {
          this.mode = mode;
        }
        writePersisted({ mode });
      },

      toggleSound() {
        this.soundOn = !this.soundOn;
        writePersisted({ soundOn: this.soundOn });
      },

      // Action methods
      rec() {
        if (this.status !== 'load') return;
        const tl = this._gsap()?.timeline();
        if (tl) {
          tl.to('.deck-btn--rec', { y: 2, duration: 0.05 })
            .to('.cassette', { scale: 1.0, duration: 0.1 })
            .add(() => this._submitDownload());
        } else {
          this._submitDownload();
        }
        this._startCounter();
      },

      _startCounter() {
        this.counter = '0:00';
        this._tickerStart = Date.now();
        if (this._tickerHandle) clearInterval(this._tickerHandle);
        this._tickerHandle = setInterval(() => {
          if (this.status !== 'rec') {
            clearInterval(this._tickerHandle);
            this._tickerHandle = null;
            return;
          }
          const sec = Math.floor((Date.now() - this._tickerStart) / 1000);
          const m = Math.floor(sec / 60);
          const s = sec % 60;
          this.counter = `${m}:${s.toString().padStart(2, '0')}`;
        }, 250);
      },

      stop() { /* future: cancel + reset */ },

      eject() {
        const tl = this._gsap()?.timeline();
        if (tl) {
          tl.to('.cassette', { y: -8, duration: 0.4, ease: 'power2.out' })
            .to('.cassette', { y: 0, duration: 0.6, ease: 'power2.in', delay: 0.2 });
        }
        this.status = 'ready';
        this.videoTitle = '';
        this.jobId = null;
        if (this._tickerHandle) { clearInterval(this._tickerHandle); this._tickerHandle = null; }
      },

      _submitDownload() {
        if (this.status !== 'load') return;
        const form = new FormData();
        form.append('url', document.querySelector('.deck-url-input').value || '');
        form.append('title', this.videoTitle);
        form.append('format', this.mode === 'vinyl' ? 'audio' : 'video');
        if (this.formatId) form.append('format_id', this.formatId);
        fetch('/api/download-card', { method: 'POST', body: form })
          .then(r => r.text())
          .then(html => {
            const target = document.getElementById('card-target');
            if (target) {
              target.innerHTML = html;
              const card = target.querySelector('[data-card]');
              if (card) this._consumeCard(card);
              if (this.jobId) this._startStatusPoll();
            }
          });
      },

      _startStatusPoll() {
        const tick = () => {
          if (this.status !== 'rec' || !this.jobId) return;
          fetch('/api/status-card/' + this.jobId)
            .then(r => r.text())
            .then(html => {
              const target = document.getElementById('card-target');
              if (!target) return;
              target.innerHTML = html;
              const card = target.querySelector('[data-card]');
              if (card) this._consumeCard(card);
              if (this.status === 'rec') setTimeout(tick, 1000);
            })
            .catch(() => { setTimeout(tick, 2000); });
        };
        setTimeout(tick, 1000);
      },
    };
  };
})();
