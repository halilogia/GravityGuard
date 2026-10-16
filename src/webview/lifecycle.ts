// Pure webview lifecycle state machine (no vscode dependency, timers injectable for tests).
// Owns every decision about WHEN webview.html may be assigned, so the host never hands HTML to an
// iframe whose document is hidden, detached, still loading or mid-teardown (the InvalidStateError
// "Failed to register a ServiceWorker: The document is in an invalid state" race).

export type WebviewPhase = 'unresolved' | 'hidden' | 'settling' | 'loading' | 'ready' | 'recovering' | 'failed' | 'disposed';

export interface LifecycleTimers {
  setTimeout(fn: () => void, ms: number): unknown;
  clearTimeout(handle: unknown): void;
}

export interface LifecycleHost {
  /** Assign a fresh document (webview.html). `nonce` identifies this document generation. */
  renderDocument(nonce: string): void;
  /** Push an in-place update into the already-ready document (no iframe reload). */
  postUpdate(): void;
  /** Recovery budget exhausted: escalate to the user. */
  onGiveUp(reason: string): void;
  isVisible(): boolean;
  log?(message: string): void;
}

export interface LifecycleOptions {
  /** Delay after the view becomes visible before the first html assignment (iframe document must settle). */
  settleMs: number;
  /** Max wait for the webview 'ready' handshake after html assignment. */
  readyTimeoutMs: number;
  /** Backoff schedule between recovery attempts; its length is the retry budget. */
  backoffMs: number[];
}

export const DEFAULT_LIFECYCLE_OPTIONS: LifecycleOptions = {
  settleMs: 150,
  readyTimeoutMs: 5000,
  backoffMs: [250, 1000, 3000]
};

const REAL_TIMERS: LifecycleTimers = {
  setTimeout: (fn, ms) => setTimeout(fn, ms),
  clearTimeout: (h) => clearTimeout(h as NodeJS.Timeout)
};

export class WebviewLifecycle {
  private _phase: WebviewPhase = 'unresolved';
  private _generation = 0;
  private _attempts = 0;
  private _settleTimer: unknown;
  private _readyTimer: unknown;
  private _recoveryTimer: unknown;
  private _dirty = false;

  constructor(
    private readonly host: LifecycleHost,
    private readonly opts: LifecycleOptions = DEFAULT_LIFECYCLE_OPTIONS,
    private readonly timers: LifecycleTimers = REAL_TIMERS,
    private readonly nonceFactory: () => string = () => Math.random().toString(36).slice(2)
  ) {}

  get phase(): WebviewPhase { return this._phase; }
  get generation(): number { return this._generation; }
  get attempts(): number { return this._attempts; }
  /** Current document nonce; a 'ready' message carrying any other nonce is stale and ignored. */
  currentNonce = '';

  /** True once a document is loaded and acknowledged, i.e. in-place updates are safe. */
  get isReady(): boolean { return this._phase === 'ready'; }

  /** A (re)resolved view starts from scratch; any previous generation is invalidated. */
  resolve(): void {
    this.cancelTimers();
    this._generation++;
    this._attempts = 0;
    this._dirty = false;
    this.currentNonce = '';
    this._phase = this.host.isVisible() ? 'settling' : 'hidden';
    if (this._phase === 'settling') {
      this.armSettle();
    }
  }

  visibilityChanged(visible: boolean): void {
    if (this._phase === 'disposed' || this._phase === 'unresolved') {
      return;
    }
    if (!visible) {
      // Never touch html while hidden; an in-flight settle is cancelled, loading/ready are left alone
      // (their watchdog is paused: a hidden iframe may legitimately defer script execution).
      if (this._phase === 'settling') {
        this.clearSettle();
        this._phase = 'hidden';
      } else if (this._phase === 'loading') {
        this.clearReady();
      } else if (this._phase === 'recovering') {
        this.clearRecovery();
        this._phase = 'hidden';
      }
      return;
    }
    if (this._phase === 'hidden') {
      this._phase = 'settling';
      this.armSettle();
    } else if (this._phase === 'ready' && this._dirty) {
      this._dirty = false;
      this.host.postUpdate();
    } else if (this._phase === 'loading' && this._readyTimer === undefined) {
      this.armReadyWatchdog();
    }
  }

  /** Data changed. Updates in place when ready, coalesces otherwise; `force` additionally acts as a manual retry from 'failed'. */
  requestRender(force = false): void {
    switch (this._phase) {
      case 'ready':
        // Ready documents are only ever updated in place; a new document is created by reset() alone
        if (this.host.isVisible()) {
          this.host.postUpdate();
        } else {
          this._dirty = true;
        }
        break;
      case 'hidden':
      case 'settling':
      case 'loading':
      case 'recovering':
        // Coalesced: the pending / upcoming load renders the freshest state anyway
        this._dirty = true;
        break;
      case 'failed':
        // A user-driven forced render is a manual retry
        if (force && this.host.isVisible()) {
          this._attempts = 0;
          this._phase = 'settling';
          this.armSettle();
        }
        break;
      default:
        break;
    }
  }

  /** Webview handshake. Only the nonce of the current document generation is accepted (idempotent). */
  ready(nonce?: string): boolean {
    if (this._phase !== 'loading') {
      return false;
    }
    if (nonce !== undefined && nonce !== this.currentNonce) {
      return false;
    }
    this.clearReady();
    this._attempts = 0;
    this._phase = 'ready';
    if (this._dirty && this.host.isVisible()) {
      this._dirty = false;
      this.host.postUpdate();
    }
    return true;
  }

  /** Manual or automatic reset: forget attempts and rebuild the document from scratch. */
  reset(reason: string): void {
    if (this._phase === 'disposed' || this._phase === 'unresolved') {
      return;
    }
    this.cancelTimers();
    this._attempts = 0;
    this.scheduleRecovery(reason);
  }

  dispose(): void {
    this.cancelTimers();
    this._generation++;
    this._phase = 'disposed';
    this.currentNonce = '';
  }

  // --- internals ---

  private beginLoad(): void {
    this.clearSettle();
    this.clearRecovery();
    this.currentNonce = this.nonceFactory();
    this._phase = 'loading';
    this._dirty = false;
    this.host.renderDocument(this.currentNonce);
    if (this.host.isVisible()) {
      this.armReadyWatchdog();
    }
  }

  private armReadyWatchdog(): void {
    this.clearReady();
    const gen = this._generation;
    this._readyTimer = this.timers.setTimeout(() => {
      this._readyTimer = undefined;
      if (gen === this._generation && this._phase === 'loading') {
        this.scheduleRecovery('ready timeout');
      }
    }, this.opts.readyTimeoutMs);
  }

  private scheduleRecovery(reason: string): void {
    this.clearReady();
    this.clearSettle();
    this.clearRecovery();
    if (this._attempts >= this.opts.backoffMs.length) {
      this._phase = 'failed';
      this.host.log?.(`recovery gave up (${reason})`);
      this.host.onGiveUp(reason);
      return;
    }
    const delay = this.opts.backoffMs[this._attempts++];
    this.host.log?.(`recovering (${reason}), attempt ${this._attempts}, backoff ${delay}ms`);
    this._phase = 'recovering';
    const gen = this._generation;
    this._recoveryTimer = this.timers.setTimeout(() => {
      this._recoveryTimer = undefined;
      if (gen !== this._generation || this._phase !== 'recovering') {
        return;
      }
      if (this.host.isVisible()) {
        this.beginLoad();
      } else {
        this._phase = 'hidden';
        this._dirty = true;
      }
    }, delay);
  }

  private armSettle(): void {
    this.clearSettle();
    const gen = this._generation;
    this._settleTimer = this.timers.setTimeout(() => {
      this._settleTimer = undefined;
      if (gen !== this._generation || this._phase !== 'settling') {
        return;
      }
      if (this.host.isVisible()) {
        this.beginLoad();
      } else {
        this._phase = 'hidden';
      }
    }, this.opts.settleMs);
  }

  private clearSettle(): void { if (this._settleTimer !== undefined) { this.timers.clearTimeout(this._settleTimer); this._settleTimer = undefined; } }
  private clearReady(): void { if (this._readyTimer !== undefined) { this.timers.clearTimeout(this._readyTimer); this._readyTimer = undefined; } }
  private clearRecovery(): void { if (this._recoveryTimer !== undefined) { this.timers.clearTimeout(this._recoveryTimer); this._recoveryTimer = undefined; } }
  private cancelTimers(): void { this.clearSettle(); this.clearReady(); this.clearRecovery(); }
}
